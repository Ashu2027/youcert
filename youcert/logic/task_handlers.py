"""
task_handlers.py - Task Handler Registration (Gemini API)

This module registers all background task handlers with the TaskManager.
Import this module in your __init__.py to ensure handlers are registered
before tasks are queued.

IMPORTANT: Uses centralized functions from youcert/__init__.py:
- secure_log() for all logging
- decrypt_token() for credential decryption
- download_file_content() for file access
- execute_query() for database operations

Gemini API:
- YouTubeProcessor uses Gemini REST API internally
- Gevent compatible out of the box

Handlers are functions that process specific task types:
- video_processing: Process YouTube videos/playlists
- chunk_generation: Generate text chunks for AI processing

Usage in logic/__init__.py:
    # Register task handlers
    from . import task_handlers  # noqa: F401
"""

import json
from typing import Dict, Any
from config import Config

# ============================================================================
# CENTRALIZED IMPORTS FROM YOUCERT
# ============================================================================

from youcert import (
    secure_log,
    decrypt_token,
    download_file_content,
    execute_query
)

# Import the task handler decorator
from youcert.logic.task_manager import task_handler


# ============================================================================
# VIDEO PROCESSING HANDLER (Gemini API)
# ============================================================================

@task_handler('video_processing')
def handle_video_processing(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a YouTube video or playlist using Gemini API.
    
    This handler is called by TaskManager in local mode,
    or by the worker endpoint in Cloudflare Containers.
    
    Uses centralized:
    - secure_log() for logging
    - decrypt_token() for credential decryption
    - YouTubeProcessor with Gemini REST API
    
    Args:
        payload: {
            'video_id': Optional[str],
            'playlist_id': Optional[str],
            'channel_id': str,
            'url': str,
            'credentials_json': str (encrypted),
            'openai_api_key': str  # NOTE: No longer used, kept for compatibility
        }
    
    Returns:
        dict: Processing result with success status
    """
    channel_id = payload.get('channel_id')
    secure_log("Video processing handler started (Gemini API)", 'info', channel_id=channel_id)
    
    try:
        # Import required modules
        from flask import current_app
        from youcert.logic.video_processor import YouTubeProcessor
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        import os
        
        # Extract payload
        url = payload.get('url')
        credentials_json = payload.get('credentials_json')
        # openai_api_key is no longer used (Gemini API now), but kept for compatibility
        
        if not all([channel_id, url, credentials_json]):
            raise ValueError("Missing required fields: channel_id, url, credentials_json")
        
        # Decrypt credentials using centralized function
        decrypted_creds = decrypt_token(credentials_json)
        if not decrypted_creds:
            secure_log("Failed to decrypt credentials", 'error', channel_id=channel_id)
            raise ValueError("Failed to decrypt credentials")
        
        creds_data = json.loads(decrypted_creds)
        
        # Build YouTube service
        credentials = Credentials(
            token=creds_data.get('token'),
            refresh_token=creds_data.get('refresh_token'),
            token_uri=creds_data.get('token_uri', 'https://oauth2.googleapis.com/token'),
            client_id=creds_data.get('client_id'),
            client_secret=creds_data.get('client_secret'),
        )
        
        youtube_service = build('youtube', 'v3', credentials=credentials)
        
        # Process the content using Gemini API
        processor = YouTubeProcessor(
            channel_id=channel_id,
            youtube_service=youtube_service,
        )
        
        result = processor.process_url(url)
        
        secure_log(
            f"Video processing handler completed: {result.get('success')}", 
            'info', 
            channel_id=channel_id
        )
        return result
        
    except Exception as e:
        secure_log(f"Video processing handler error: {e}", 'error', channel_id=channel_id)
        return {
            'success': False,
            'message': str(e)
        }


# ============================================================================
# CHUNK GENERATION HANDLER (NO CHANGES NEEDED)
# ============================================================================

@task_handler('chunk_generation')
def handle_chunk_generation(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate text chunks from a transcript.
    
    NO CHANGES NEEDED - This handler doesn't use AI directly.
    
    Uses centralized:
    - secure_log() for logging
    - download_file_content() for file access
    - execute_query() for database operations
    
    Args:
        payload: {
            'content_id': str,
            'content_type': str (video, playlist),
            'channel_id': str,
            'text_path': str
        }
    
    Returns:
        dict: Result with chunk count
    """
    channel_id = payload.get('channel_id')
    content_id = payload.get('content_id')
    
    secure_log(
        "Chunk generation handler started", 
        'info', 
        channel_id=channel_id,
        context={'content_id': content_id}
    )
    
    try:
        # Import chunker (uses centralized logging)
        from youcert.logic.chunk_generator import TranscriptChunker
        
        content_type = payload.get('content_type')
        text_path = payload.get('text_path')
        
        if not all([content_id, content_type, text_path]):
            raise ValueError("Missing required fields")
        
        # Download transcript using centralized function
        content = download_file_content(text_path)
        
        if not content:
            secure_log(f"Transcript not found: {text_path}", 'error', channel_id=channel_id)
            raise ValueError(f"Transcript not found: {text_path}")
        
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='ignore')
        
        # Generate chunks
        chunker = TranscriptChunker()
        chunks = chunker.chunk_text(content)
        
        secure_log(
            f"Chunk generation completed", 
            'info', 
            channel_id=channel_id,
            context={'content_id': content_id, 'chunk_count': len(chunks)}
        )
        
        # Update database using centralized execute_query and dynamic table selection
        try:
            # Determine which status table to update (video vs playlist)
            table_name = 'video_processing_status' if content_type == 'video' else 'playlist_processing_status'
            
            execute_query(f"""
                UPDATE creator_base.{table_name} 
                SET status = 'chunks_generated', chunk_count = %s, updated_at = NOW()
                WHERE content_id = %s AND channel_id = %s
            """, (len(chunks), content_id, channel_id), commit=True)
            
        except Exception as db_error:
            secure_log(f"Database update failed (non-critical): {db_error}", 'warning', channel_id=channel_id)
        
        return {
            'success': True,
            'message': 'Chunks generated',
            'chunk_count': len(chunks),
            'chunks': chunks  # Return for local processing
        }
        
    except Exception as e:
        secure_log(f"Chunk generation handler error: {e}", 'error', channel_id=channel_id)
        return {
            'success': False,
            'message': str(e)
        }


# ============================================================================
# INITIALIZATION LOG
# ============================================================================

secure_log("Task handlers registered successfully (Gemini API compatible)", 'info')


