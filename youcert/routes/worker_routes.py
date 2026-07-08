"""
worker_routes.py - Internal Worker Endpoints for Cloudflare Queues

These endpoints are called by Cloudflare Queue consumers to execute background jobs.
They are protected and should only be accessible from queue consumers.

IMPORTANT: Uses centralized functions from youcert/__init__.py:
- secure_log() for logging
- execute_query() for database operations
- decrypt_token() for credential decryption
- download_file_content() for file access

Gemini API:
- YouTubeProcessor uses Gemini REST API internally
- Gevent compatible out of the box

Security:
- Validates queue headers in production
- Returns proper HTTP status codes for retry handling

Endpoints:
- POST /internal/worker/video_processing
- POST /internal/worker/chunk_generation
"""

import os
import json
from functools import wraps
from flask import Blueprint, request, jsonify, current_app

# ============================================================================
# CENTRALIZED IMPORTS FROM YOUCERT
# ============================================================================

from youcert import (
    secure_log,
    execute_query,
    decrypt_token,
    download_file_content,
    get_db_connection
)


# ============================================================================
# BLUEPRINT SETUP
# ============================================================================

worker_bp = Blueprint('worker', __name__, url_prefix='/internal/worker')


# ============================================================================
# ENVIRONMENT DETECTION (Consistent with youcert/__init__.py)
# ============================================================================

def is_cloud_run() -> bool:
    """Check if running in Cloudflare Containers (production)"""
    from config import Config
    return Config.IS_CLOUDFLARE


# ============================================================================
# SECURITY MIDDLEWARE
# ============================================================================

def validate_cloud_tasks_request():
    """
    Validate that the request is from Cloudflare Queues.

    In Cloudflare Containers, queue consumer requests arrive as HTTP POSTs
    with specific headers. In production, we validate these headers.
    In local development, validation is skipped.

    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    # In local development, skip validation
    if not is_cloud_run():
        secure_log("Local mode - skipping queue request validation", 'debug')
        return True, None

    # Check for queue task headers (CF Queues set these automatically)
    task_name = request.headers.get('X-CloudTasks-TaskName') or request.headers.get('CF-Queue-Message-Id')
    queue_name = request.headers.get('X-CloudTasks-QueueName') or request.headers.get('CF-Queue-Name')

    if not task_name or not queue_name:
        secure_log("Missing queue headers in request", 'warning')
        return False, "Invalid request: Missing queue headers"

    secure_log(f"Valid queue request received", 'info', context={'task': task_name, 'queue': queue_name})
    return True, None


def cloud_tasks_only(f):
    """
    Decorator to protect endpoints - only allows queue consumer requests.
    In local development, allows direct calls for testing.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        is_valid, error = validate_cloud_tasks_request()
        
        if not is_valid:
            secure_log(f"Unauthorized worker request: {error}", 'error')
            return jsonify({
                'success': False,
                'error': error
            }), 403
        
        return f(*args, **kwargs)
    
    return decorated_function


def get_retry_count() -> int:
    """Get current retry count from queue headers"""
    return int(request.headers.get('X-CloudTasks-TaskRetryCount', request.headers.get('CF-Queue-Retry-Count', 0)))


def get_task_name() -> str:
    """Get task name from queue headers"""
    return request.headers.get('X-CloudTasks-TaskName', request.headers.get('CF-Queue-Message-Id', 'local-task'))


# ============================================================================
# VIDEO PROCESSING WORKER (Gemini API)
# ============================================================================

@worker_bp.route('/video_processing', methods=['POST'])
@cloud_tasks_only
def handle_video_processing():
    """
    Background worker for video/playlist processing using Gemini API.
    
    Uses centralized:
    - secure_log() for logging
    - decrypt_token() for credential decryption
    - YouTubeProcessor with Gemini REST API
    
    Expected payload:
    {
        "video_id": "abc123",  # Optional
        "playlist_id": "PL...",  # Optional
        "channel_id": "UC...",
        "url": "https://youtube.com/...",
        "credentials_json": "{...}",  # Encrypted OAuth credentials
    }
    
    Returns:
        200: Success - task completed
        400: Bad request - invalid payload
        500: Error - task should be retried
    """
    task_name = get_task_name()
    retry_count = get_retry_count()
    
    secure_log(
        f"Video processing worker started (Gemini API)", 
        'info', 
        context={'task': task_name, 'retry': retry_count}
    )
    
    payload = None
    try:
        payload = request.get_json()
        
        if not payload:
            secure_log("Empty payload received", 'error')
            return jsonify({'success': False, 'error': 'Empty payload'}), 400
        
        # Extract required fields
        channel_id = payload.get('channel_id')
        url = payload.get('url')
        credentials_json = payload.get('credentials_json')
        # openai_api_key is no longer used (Gemini API now), but kept for compatibility
        
        if not all([channel_id, url, credentials_json]):
            secure_log("Missing required fields in video processing request", 'error', channel_id=channel_id)
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        # Import video processor (uses Gemini API)
        from youcert.logic.video_processor import YouTubeProcessor
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        
        # Decrypt credentials using centralized decrypt_token
        try:
            decrypted_creds = decrypt_token(credentials_json)
            if not decrypted_creds:
                secure_log("Failed to decrypt credentials", 'error', channel_id=channel_id)
                return jsonify({'success': False, 'error': 'Invalid credentials'}), 400
            
            creds_data = json.loads(decrypted_creds)
            credentials = Credentials(
                token=creds_data.get('token'),
                refresh_token=creds_data.get('refresh_token'),
                token_uri=creds_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
                client_id=creds_data.get('client_id'),
                client_secret=creds_data.get('client_secret'),
            )
            
            youtube_service = build('youtube', 'v3', credentials=credentials)
            
        except Exception as e:
            secure_log(f"Credential error: {e}", 'error', channel_id=channel_id)
            return jsonify({'success': False, 'error': 'Credential error'}), 400
        
        # Project ID no longer needed — Gemini API uses API key
        
        # Process the video/playlist using Gemini API
        processor = YouTubeProcessor(
            channel_id=channel_id,
            youtube_service=youtube_service,
        )
        
        result = processor.process_url(url)
        
        if result.get('success'):
            secure_log(f"Video processing completed successfully", 'info', channel_id=channel_id)
            return jsonify({
                'success': True,
                'message': 'Processing completed',
                'data': result.get('data', {})
            }), 200
        else:
            error_message = result.get('message', 'Processing failed')
            secure_log(f"Video processing failed: {error_message}", 'warning', channel_id=channel_id)

            # Check if this is a business logic rejection (don't retry) vs actual error (retry)
            # Business logic failures: already processed, invalid URL, no transcript, etc.
            no_retry_keywords = [
                'already processed',
                'regenerat',  # matches "regeneration" and "regenerated"
                'invalid url',
                'no transcript',
                'not found',
                'private video',
                'unavailable',
            ]

            is_business_logic_failure = any(
                keyword in error_message.lower() for keyword in no_retry_keywords
            )

            if is_business_logic_failure:
                # Return 400 for business logic failures - queue won't retry
                return jsonify({
                    'success': False,
                    'error': error_message,
                    'retry': False
                }), 400
            else:
                # Return 500 for actual errors - queue will retry
                return jsonify({
                    'success': False,
                    'error': error_message,
                    'retry': True
                }), 500
            
    except Exception as e:
        secure_log(f"Video processing exception: {e}", 'error', channel_id=payload.get('channel_id') if payload else None)
        
        # Return 500 to trigger queue retry
        return jsonify({
            'success': False,
            'error': str(e),
            'retry_count': retry_count
        }), 500


# ============================================================================
# CHUNK GENERATION WORKER (NO CHANGES NEEDED)
# ============================================================================

@worker_bp.route('/chunk_generation', methods=['POST'])
@cloud_tasks_only
def handle_chunk_generation():
    """
    Background worker for text chunking.
    
    NO CHANGES NEEDED - This worker doesn't use AI directly.
    
    Uses centralized:
    - secure_log() for logging
    - download_file_content() for file access
    - execute_query() for database operations
    
    Expected payload:
    {
        "content_id": "abc123",
        "content_type": "video",  # video or playlist
        "channel_id": "UC...",
        "text_path": "transcripts/videos/abc123.txt"
    }
    
    Returns:
        200: Success
        400: Bad request
        500: Error (retry)
    """
    task_name = get_task_name()
    retry_count = get_retry_count()
    
    secure_log(f"Chunk generation worker started", 'info', context={'task': task_name})
    
    payload = None
    try:
        payload = request.get_json()
        
        if not payload:
            return jsonify({'success': False, 'error': 'Empty payload'}), 400
        
        content_id = payload.get('content_id')
        content_type = payload.get('content_type')
        channel_id = payload.get('channel_id')
        text_path = payload.get('text_path')
        
        if not all([content_id, content_type, channel_id, text_path]):
            secure_log("Chunk generation missing required fields", 'error', channel_id=channel_id)
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        # Import chunker (uses centralized logging)
        from youcert.logic.chunk_generator import TranscriptChunker
        
        # Download transcript using centralized function
        content = download_file_content(text_path)
        
        if not content:
            secure_log(f"Transcript not found: {text_path}", 'error', channel_id=channel_id)
            return jsonify({'success': False, 'error': 'Transcript not found'}), 400
        
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='ignore')
        
        # Chunk the text
        chunker = TranscriptChunker()
        chunks = chunker.chunk_text(content)
        
        secure_log(
            f"Chunk generation completed", 
            'info', 
            channel_id=channel_id,
            context={'content_id': content_id, 'chunk_count': len(chunks)}
        )
        
        # Update database status using whitelist mapping (safer than f-string)
        try:
            # Use whitelist mapping to prevent any potential SQL injection risk
            TABLE_MAP = {
                'video': 'video_processing_status',
                'playlist': 'playlist_processing_status'
            }

            table_name = TABLE_MAP.get(content_type)
            if not table_name:
                raise ValueError(f"Invalid content_type: {content_type}")

            # Build query using verified table name
            query = f"""
                UPDATE creator_base.{table_name}
                SET status = 'chunks_generated', chunk_count = %s, updated_at = NOW()
                WHERE content_id = %s AND channel_id = %s
            """
            execute_query(query, (len(chunks), content_id, channel_id), commit=True)
            
        except Exception as db_error:
            secure_log(f"Database update failed (non-critical): {db_error}", 'warning', channel_id=channel_id)
        
        return jsonify({
            'success': True,
            'message': 'Chunks generated',
            'chunk_count': len(chunks)
        }), 200
        
    except Exception as e:
        secure_log(f"Chunk generation exception: {e}", 'error', channel_id=payload.get('channel_id') if payload else None)
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# HEALTH CHECK ENDPOINT
# ============================================================================

@worker_bp.route('/health', methods=['GET'])
def worker_health():
    """Health check endpoint for worker routes"""
    return jsonify({
        'status': 'healthy',
        'service': 'worker',
        'environment': 'cloudflare' if is_cloud_run() else 'local',
        'ai_backend': 'gemini_api'
    }), 200


# ============================================================================
# MANUAL TASK TRIGGER (Development Only)
# ============================================================================

@worker_bp.route('/trigger/<task_type>', methods=['POST'])
def manual_trigger(task_type):
    """
    Manually trigger a task (development/testing only).
    
    In production, this endpoint returns 403.
    """
    if is_cloud_run():
        secure_log("Manual trigger attempted in production", 'warning')
        return jsonify({
            'success': False,
            'error': 'Manual trigger disabled in production'
        }), 403
    
    payload = request.get_json() or {}
    
    # Import task manager
    from youcert.logic.task_manager import TaskManager
    
    secure_log(f"Manual trigger: {task_type}", 'info')
    result = TaskManager.queue_task(task_type, payload)
    
    return jsonify(result), 200 if result.get('success') else 400

