"""
============================================================================
YouTube Video Processor - GEMINI API VERSION (v9 - COMPLETE)
============================================================================

COMPREHENSIVE UPGRADE:
- Gemini API via REST (API key authentication)
- Smart chunking: 30K tokens (up to 120K total)
- Random sampling for >120K transcripts (first 1K + last 1K + random middle)
- Combined summary + JSON questions in single API call
- ALL functions from old video_processor.py preserved
- Exact prompts preserved (summarization + Bloom's taxonomy)
- Centralized logging, database, storage
- Playlist combined transcripts
- Async processing for speed
- Task system compatible with Cloudflare Containers

CHUNKING LOGIC:
- ≤30K tokens: Single API call (summary + questions)
- 30K-120K tokens: Split into 30K chunks, process each (30,30,30,10 example)
- >120K tokens: Random sample (first 1K + last 1K + random to 120K total)

============================================================================
"""

import os
import json
import io
import time
import random
import string
import hashlib
import isodate
import mimetypes
import json_repair
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
from typing import Optional, List, Dict, Any, Tuple
from functools import wraps
from concurrent.futures import ThreadPoolExecutor

import tiktoken
from PIL import Image
import requests
from googleapiclient.errors import HttpError

# NOTE: google.auth / Vertex AI SDK removed — Gemini API key used directly.
# API key is injected at runtime via Cloudflare Workers Secret (GEMINI_API_KEY env var).

# Centralized imports
from youcert import (
    execute_query, 
    execute_many, 
    secure_log as centralized_log,
    save_file,
    get_file_url,
    download_file_content,
    get_db_connection,
    STORAGE_PATHS,
    get_project_id,
)


# ============================================================================
# CONFIGURATION CONSTANTS
# ============================================================================

# Import Config to get project settings
from config import Config

# Gemini API Configuration
# Using Google AI Studio REST API (no GCP project, no Vertex AI SDK, no OAuth tokens)
VERTEX_AI_MODEL = Config.GEMINI_MODEL  # gemini-2.5-flash-lite
VERTEX_AI_LOCATION = 'global'  # Gemini API is global — no regional endpoint needed
GEMINI_API_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"

# Token limits
MAX_INPUT_TOKENS = 272000  # Gemini's context window
MAX_OUTPUT_TOKENS = 32768  # Gemini's max output

# Chunking configuration (EXACT from requirements)
CHUNK_SIZE_SMALL = 30000  # 30K token chunks
CHUNK_SIZE_MAX = 120000   # Maximum 120K total
SAMPLE_CHUNK_SIZE = 1000  # For random sampling: first 1K, last 1K, random 1K chunks

# Questions per API call
QUESTIONS_PER_CHUNK_30K = 25  # 25 questions per 30K chunk

# Retry configuration
MAX_RETRIES = 3
BASE_DELAY = 1.0
MAX_DELAY = 10.0


# ============================================================================
# LOGGING WRAPPER
# ============================================================================

def mask_channel_id(channel_id):
    """Mask channel_id for logging - show first 4 and last 4 characters"""
    if not channel_id or len(channel_id) <= 8:
        return channel_id
    return f"{channel_id[:4]}...{channel_id[-4:]}"


def secure_log(message, level='info', video_id=None, playlist_id=None, channel_id=None):
    """Wrapper for centralized secure_log with backward compatibility"""
    context = {}
    if video_id:
        context['video_id'] = video_id
    if playlist_id:
        context['playlist_id'] = playlist_id

    # Mask the channel_id for privacy
    masked_channel_id = mask_channel_id(channel_id) if channel_id else None

    centralized_log(message, level=level, channel_id=masked_channel_id, context=context)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def call_stored_procedure(proc_name, params):
    """
    TiDB Compatible: Stored procedures are NOT supported in TiDB Cloud.
    This function is kept as a stub for backward compatibility.
    All callers should be migrated to use execute_query() directly.
    Raises NotImplementedError to guide migration.
    """
    raise NotImplementedError(
        f"Stored procedures are not supported in TiDB Cloud. "
        f"Please refactor '{proc_name}' logic into Python using execute_query()."
    )


def upload_file_to_storage(local_path_or_data, storage_folder, filename):
    """
    Centralized file upload using youcert.save_file

    Supports subfolder notation in filename:
    - 'videos/video123.txt' -> saves to storage_folder/videos/video123.txt
    - 'playlists/playlist456.txt' -> saves to storage_folder/playlists/playlist456.txt
    """
    try:
        storage_type = storage_folder
        subfolder = None
        target_filename = filename

        # Extract subfolder from filename if present (e.g., 'videos/file.txt')
        clean_filename = filename.replace('\\', '/')
        if '/' in clean_filename:
            parts = clean_filename.split('/')
            if len(parts) == 2:
                # Single level subfolder (e.g., 'videos/file.txt')
                subfolder = parts[0]
                target_filename = parts[1]
            elif len(parts) > 2:
                # Multiple levels (e.g., 'videos/subdir/file.txt')
                subfolder = '/'.join(parts[:-1])
                target_filename = parts[-1]

        # Convert data to file object
        file_obj = None
        if isinstance(local_path_or_data, str) and os.path.exists(local_path_or_data):
            with open(local_path_or_data, 'rb') as f:
                file_data = f.read()
            file_obj = io.BytesIO(file_data)
        elif isinstance(local_path_or_data, bytes):
            file_obj = io.BytesIO(local_path_or_data)
        elif hasattr(local_path_or_data, 'read'):
            file_obj = local_path_or_data
            if hasattr(file_obj, 'seek'):
                file_obj.seek(0)
        else:
            secure_log(f"Invalid file input type: {type(local_path_or_data)}", 'error')
            return None

        # Call save_file with storage_type and subfolder as separate parameters
        result = save_file(file_obj, storage_type, target_filename, subfolder=subfolder)

        if not result:
            secure_log(f"Centralized save_file failed for {filename}", 'error')

        return result

    except Exception as e:
        secure_log(f"Error uploading file to storage: {e}", 'error')
        return None


def retry_with_backoff(max_retries=MAX_RETRIES, base_delay=BASE_DELAY, max_delay=MAX_DELAY):
    """Retry decorator with exponential backoff"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (HttpError, requests.exceptions.RequestException) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        jitter = random.uniform(0, delay * 0.1)
                        sleep_time = delay + jitter
                        secure_log(
                            f"Retry {attempt + 1}/{max_retries} after {sleep_time:.2f}s: {str(e)}", 
                            'warning'
                        )
                        time.sleep(sleep_time)
                    else:
                        secure_log(f"All retries exhausted: {str(e)}", 'error')
                except Exception as e:
                    secure_log(f"Non-retryable error: {str(e)}", 'error')
                    raise
            raise last_exception
        return wrapper
    return decorator


# ============================================================================
# SMART REGENERATION HELPERS (15-DAY RULE)
# ============================================================================

def can_regenerate_questions(exam_number):
    """
    Check if questions can be regenerated (15-day rule).

    Returns:
        tuple: (can_regenerate: bool, days_remaining: int, last_updated: datetime)
    """
    try:
        result = execute_query("""
            SELECT updated_at
            FROM exam.exam_questions
            WHERE unique_exam_number = %s
        """, (exam_number,), fetch_one=True)

        if not result or not result.get('updated_at'):
            # No questions exist, can generate
            return (True, 0, None)

        last_updated = result['updated_at']
        days_since_update = (datetime.now() - last_updated).days
        days_remaining = max(0, 15 - days_since_update)

        can_regenerate = days_since_update >= 15

        return (can_regenerate, days_remaining, last_updated)

    except Exception as e:
        secure_log(f"Error checking regeneration eligibility: {e}", 'error')
        # On error, allow regeneration to be safe
        return (True, 0, None)


def get_existing_video_data(video_id, channel_id):
    """Check if video was previously processed"""
    try:
        result = execute_query("""
            SELECT v.video_id, v.title, v.video_description, v.transcript_path,
                   v.thumbnail_image, v.duration_seconds,
                   e.unique_exam_number, eq.updated_at as questions_updated_at
            FROM creator_base.videos v
            LEFT JOIN exam.listed_exams e ON v.video_id = e.video_id AND v.channel_id = e.channel_id
            LEFT JOIN exam.exam_questions eq ON e.unique_exam_number = eq.unique_exam_number
            WHERE v.video_id = %s AND v.channel_id = %s
        """, (video_id, channel_id), fetch_one=True)

        return result
    except Exception as e:
        secure_log(f"Error checking existing video: {e}", 'error')
        return None


def get_existing_playlist_data(playlist_id, channel_id):
    """Check if playlist was previously processed"""
    try:
        result = execute_query("""
            SELECT p.playlist_id, p.playlist_title as title, p.playlist_description,
                   p.thumbnail_image, p.transcript_path, p.duration_seconds,
                   e.unique_exam_number, eq.updated_at as questions_updated_at
            FROM creator_base.playlists p
            LEFT JOIN exam.listed_exams e ON p.playlist_id = e.playlist_id AND p.channel_id = e.channel_id
            LEFT JOIN exam.exam_questions eq ON e.unique_exam_number = eq.unique_exam_number
            WHERE p.playlist_id = %s AND p.channel_id = %s
        """, (playlist_id, channel_id), fetch_one=True)

        return result
    except Exception as e:
        secure_log(f"Error checking existing playlist: {e}", 'error')
        return None


# ============================================================================
# PROCESSING STATUS HELPERS
# ============================================================================

def is_processing(content_id, channel_id, content_type='video'):
    """Check if content is currently being processed"""
    try:
        table = 'video_processing_status' if content_type == 'video' else 'playlist_processing_status'
        result = execute_query(f"""
            SELECT status FROM creator_base.{table}
            WHERE content_id = %s AND channel_id = %s
        """, (content_id, channel_id), fetch_one=True)
        
        if result:
            return result['status'] == 'processing'
        return False
    except Exception as e:
        secure_log(f"Error checking processing status: {e}", 'error')
        return False


def get_checkpoint_data(content_id, channel_id, content_type='video'):
    """
    Retrieve checkpoint data for recovery.

    Returns:
        dict or None: Checkpoint data containing processed chunks, or None if not found
    """
    try:
        table = 'video_processing_status' if content_type == 'video' else 'playlist_processing_status'
        result = execute_query(f"""
            SELECT checkpoint_data, last_successful_chunk, processed_chunks, total_chunks
            FROM creator_base.{table}
            WHERE content_id = %s AND channel_id = %s
        """, (content_id, channel_id), fetch_one=True)

        if result and result.get('checkpoint_data'):
            import json
            return {
                'checkpoint_data': json.loads(result['checkpoint_data']) if isinstance(result['checkpoint_data'], str) else result['checkpoint_data'],
                'last_successful_chunk': result.get('last_successful_chunk'),
                'processed_chunks': result.get('processed_chunks', 0),
                'total_chunks': result.get('total_chunks')
            }
        return None

    except Exception as e:
        secure_log(f"Error getting checkpoint data: {e}", 'error')
        return None


def set_processing_status(content_id, channel_id, status, content_type='video', **kwargs):
    """
    Set processing status for content with optional progress tracking.

    Args:
        content_id: Video/Playlist ID
        channel_id: Channel ID
        status: Status string (processing/completed/failed)
        content_type: 'video' or 'playlist'
        **kwargs: Optional fields:
            - total_chunks: Total number of chunks
            - processed_chunks: Number of chunks processed
            - progress_percentage: Progress (0-100)
            - current_stage: Current stage description
            - checkpoint_data: JSON data for recovery
            - last_successful_chunk: Last successful chunk index
            - transcript_path: Path to transcript file
            - chunk_count: Total chunk count
    """
    try:
        table = 'video_processing_status' if content_type == 'video' else 'playlist_processing_status'

        # Build dynamic UPDATE clause for optional fields
        update_fields = ['status = %s', 'updated_at = NOW()']
        update_values = [status]

        if 'total_chunks' in kwargs:
            update_fields.append('total_chunks = %s')
            update_values.append(kwargs['total_chunks'])

        if 'processed_chunks' in kwargs:
            update_fields.append('processed_chunks = %s')
            update_values.append(kwargs['processed_chunks'])

        if 'progress_percentage' in kwargs:
            update_fields.append('progress_percentage = %s')
            update_values.append(kwargs['progress_percentage'])

        if 'current_stage' in kwargs:
            update_fields.append('current_stage = %s')
            update_values.append(kwargs['current_stage'])

        if 'checkpoint_data' in kwargs:
            import json
            update_fields.append('checkpoint_data = %s')
            update_values.append(json.dumps(kwargs['checkpoint_data']))

        if 'last_successful_chunk' in kwargs:
            update_fields.append('last_successful_chunk = %s')
            update_values.append(kwargs['last_successful_chunk'])

        if 'transcript_path' in kwargs:
            update_fields.append('transcript_path = %s')
            update_values.append(kwargs['transcript_path'])

        # NOTE: summary_path removed - summaries no longer generated

        if 'chunk_count' in kwargs:
            update_fields.append('chunk_count = %s')
            update_values.append(kwargs['chunk_count'])

        if status == 'completed':
            update_fields.append('completed_at = NOW()')

        update_clause = ', '.join(update_fields)

        query = f"""
            INSERT INTO creator_base.{table} (content_id, channel_id, status, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE {update_clause}
        """

        execute_query(query, (content_id, channel_id, status, *update_values), commit=True)

        secure_log(f"Processing status set: {content_type} {content_id} -> {status}", 'info')

    except Exception as e:
        secure_log(f"Error setting processing status for {content_type} {content_id}: {e}", 'error')
        secure_log(f"Query was: INSERT INTO creator_base.{table} ...", 'error')


# ============================================================================
# YOUTUBE TOKEN EXPIRED ERROR
# ============================================================================

class YouTubeTokenExpiredError(Exception):
    """Exception raised when YouTube OAuth token has expired"""
    pass


# ============================================================================
# ADVANCED CHUNKING SYSTEM
# ============================================================================

class TranscriptChunker:
    """
    Advanced chunking system following EXACT requirements:
    
    1. ≤30K tokens: Single chunk (no splitting)
    2. 30K-120K tokens: Split into 30K chunks
    3. >120K tokens: Random sampling (first 1K + last 1K + random middle to 120K)
    """
    
    def __init__(self):
        """Initialize chunker with tiktoken"""
        self.tokenizer = tiktoken.get_encoding("o200k_base")
        secure_log("TranscriptChunker initialized", 'info')
    
    def count_tokens(self, text: str) -> int:
        """Count tokens in text"""
        try:
            return len(self.tokenizer.encode(text))
        except:
            # Fallback estimate
            return len(text) // 4
    
    def chunk_text(self, text: str) -> List[str]:
        """
        Chunk text following EXACT requirements.
        
        Returns:
            List[str]: List of text chunks
        """
        token_count = self.count_tokens(text)
        secure_log(f"Chunking transcript: {token_count} tokens", 'info')
        
        # Case 1: ≤30K tokens - return as single chunk
        if token_count <= CHUNK_SIZE_SMALL:
            secure_log(f"Single chunk (≤30K): {token_count} tokens", 'info')
            return [text]
        
        # Case 2: 30K-120K tokens - split into 30K chunks
        elif token_count <= CHUNK_SIZE_MAX:
            secure_log(f"Multiple chunks (30K-120K): {token_count} tokens", 'info')
            return self._chunk_sequential(text, token_count)
        
        # Case 3: >120K tokens - random sampling
        else:
            secure_log(f"Random sampling (>120K): {token_count} tokens", 'info')
            return self._chunk_with_sampling(text, token_count)
    
    def _chunk_sequential(self, text: str, total_tokens: int) -> List[str]:
        """
        Split text into 30K token chunks.
        
        Example: 100K tokens → [30K, 30K, 30K, 10K]
        """
        chunks = []
        tokens = self.tokenizer.encode(text)
        
        start = 0
        while start < len(tokens):
            end = min(start + CHUNK_SIZE_SMALL, len(tokens))
            chunk_tokens = tokens[start:end]
            chunk_text = self.tokenizer.decode(chunk_tokens)
            chunks.append(chunk_text)
            start = end
        
        secure_log(f"Created {len(chunks)} sequential chunks", 'info')
        return chunks
    
    def _chunk_with_sampling(self, text: str, total_tokens: int) -> List[str]:
        """
        Random sampling for >120K transcripts.
        
        Strategy:
        1. Take first 1K tokens
        2. Take last 1K tokens  
        3. Randomly sample middle chunks (1K each) until reaching 120K total
        4. Combine sampled chunks into temp file
        5. Re-chunk combined text into 30K chunks
        
        Returns:
            List[str]: 30K chunks from sampled content
        """
        tokens = self.tokenizer.encode(text)
        
        # Step 1: First 1K tokens
        first_chunk = tokens[:SAMPLE_CHUNK_SIZE]
        
        # Step 2: Last 1K tokens
        last_chunk = tokens[-SAMPLE_CHUNK_SIZE:]
        
        # Step 3: Calculate how many middle chunks needed
        tokens_used = len(first_chunk) + len(last_chunk)
        tokens_needed = CHUNK_SIZE_MAX - tokens_used
        
        middle_chunks_count = tokens_needed // SAMPLE_CHUNK_SIZE
        
        # Get middle section (excluding first and last 1K)
        middle_section = tokens[SAMPLE_CHUNK_SIZE:-SAMPLE_CHUNK_SIZE]
        
        # Randomly sample middle chunks
        middle_chunks = []
        if len(middle_section) > 0 and middle_chunks_count > 0:
            # Divide middle section into 1K chunks
            available_chunks = []
            for i in range(0, len(middle_section), SAMPLE_CHUNK_SIZE):
                chunk = middle_section[i:i+SAMPLE_CHUNK_SIZE]
                if len(chunk) > 0:
                    available_chunks.append(chunk)
            
            # Randomly select chunks
            if len(available_chunks) > 0:
                num_to_sample = min(middle_chunks_count, len(available_chunks))
                sampled_indices = random.sample(range(len(available_chunks)), num_to_sample)
                sampled_indices.sort()  # Keep chronological order
                
                for idx in sampled_indices:
                    middle_chunks.append(available_chunks[idx])
        
        # Step 4: Combine all sampled chunks
        combined_tokens = first_chunk
        for chunk in middle_chunks:
            combined_tokens.extend(chunk)
        combined_tokens.extend(last_chunk)
        
        # Decode to text
        combined_text = self.tokenizer.decode(combined_tokens)
        
        secure_log(
            f"Sampled {len(combined_tokens)} tokens from {total_tokens} total "
            f"(first 1K + {len(middle_chunks)} middle + last 1K)",
            'info'
        )
        
        # Step 5: Re-chunk combined text into 30K chunks
        return self._chunk_sequential(combined_text, len(combined_tokens))


# ============================================================================
# MAIN YOUTUBE PROCESSOR CLASS
# ============================================================================

class YouTubeProcessor:
    """
    Complete YouTube video processor with Gemini API.
    
    Features:
    - Video & playlist processing
    - Smart chunking (30K tokens up to 120K, random sampling for >120K)
    - Gemini 3 Flash (summary + questions in single call)
    - Exact prompts preserved
    - Profile picture & thumbnail download
    - Playlist combined transcripts
    - System health monitoring
    """
    
    def __init__(self, channel_id, youtube_service, project_id=None):
        """
        Initialize processor with Gemini REST API (NO SDK, NO gRPC, NO OAuth tokens).

        Args:
            channel_id: YouTube channel ID
            youtube_service: Authenticated YouTube API service
            project_id: Unused — kept for backward compatibility only
        """
        self.channel_id = channel_id
        self.youtube_service = youtube_service

        # Gemini API key — read at init time from Cloudflare Workers Secret (env var).
        # This is a permanent key — no OAuth token refresh needed.
        self.gemini_api_key = Config.GEMINI_API_KEY
        self.gemini_model = Config.GEMINI_MODEL

        if not self.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. Add it as a Cloudflare Workers Secret "
                "or in your local .env file."
            )

        # Google AI Studio REST endpoint (global, no project/location required)
        # API key is sent via x-goog-api-key header — NEVER in the URL (access log safety).
        self.vertex_ai_endpoint = (
            f"{GEMINI_API_ENDPOINT}/{self.gemini_model}:generateContent"
        )

        # Initialize chunker
        self.chunker = TranscriptChunker()

        # Storage paths
        self.thumbnails_path = STORAGE_PATHS.get('thumbnails', 'thumbnails')
        self.transcripts_path = STORAGE_PATHS.get('transcripts', 'transcripts')
        self.summaries_path = STORAGE_PATHS.get('summaries', 'summaries')
        self.profile_pictures_path = STORAGE_PATHS.get('profile_pictures', 'profile_pictures')

        secure_log(
            "YouTubeProcessor initialized with Gemini REST API (API key auth, no OAuth)",
            'info',
            channel_id=channel_id
        )
    
    
    def _get_credentials(self):
        """
        Deprecated: Vertex AI OAuth credentials removed.
        Gemini API uses a permanent API key — no OAuth token refresh needed.
        Kept for API backward compatibility.
        """
        return None

    def _ensure_token_fresh(self):
        """
        No-op: Gemini API keys never expire — no token refresh required.
        Kept for API backward compatibility.
        """
        pass
    
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def generate_unique_exam_number(self, channel_id, playlist_id=None, video_id=None):
        """
        Generate unique exam number in format: channel_id_video_id or channel_id_playlist_id

        Format:
        - For videos: UCe6dsju6cv3lYDjo773FT4w_ZwzVnFnH66s
        - For playlists: UCe6dsju6cv3lYDjo773FT4w_PLxxxxxxxxxxxxxxxxxx
        """
        if playlist_id:
            return f"{channel_id}_{playlist_id}"
        elif video_id:
            return f"{channel_id}_{video_id}"
        else:
            # Fallback to old format if neither is provided
            prefix = "VID"
            random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            return f"{prefix}_{channel_id[:8]}_{random_suffix}"
    
    
    def generate_secure_token(self, length=16):
        """Generate secure random token"""
        return ''.join(random.choices(string.ascii_letters + string.digits, k=length))
    
    
    def extract_video_id(self, url):
        """Extract video ID from YouTube URL"""
        patterns = [
            r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
            r'(?:embed\/)([0-9A-Za-z_-]{11})',
            r'^([0-9A-Za-z_-]{11})$'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        parsed_url = urlparse(url)
        if parsed_url.netloc in ['youtu.be', 'www.youtu.be']:
            return parsed_url.path.lstrip('/')
        
        query_params = parse_qs(parsed_url.query)
        if 'v' in query_params:
            return query_params['v'][0]
        
        return None
    
    
    def extract_playlist_id(self, url):
        """Extract playlist ID from YouTube URL"""
        patterns = [
            r'list=([0-9A-Za-z_-]+)',
            r'^([0-9A-Za-z_-]{34})$'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        if 'list' in query_params:
            return query_params['list'][0]
        
        return None
    
    
    def is_playlist_url(self, url):
        """Check if URL is a playlist"""
        return 'list=' in url or '/playlist' in url
    
    
    def validate_image_file(self, file_path):
        """Validate image file"""
        try:
            if not os.path.exists(file_path):
                return False
            
            with Image.open(file_path) as img:
                img.verify()
            
            mime_type, _ = mimetypes.guess_type(file_path)
            if not mime_type or not mime_type.startswith('image/'):
                return False
            
            return True
        except Exception as e:
            secure_log(f"Image validation failed: {e}", 'warning')
            return False
    
    
    @retry_with_backoff()
    def download_thumbnail(self, url, filename, folder='videos'):
        """Download and save thumbnail from URL

        Args:
            url: URL of the thumbnail image
            filename: Name for the saved file
            folder: Subfolder for organization ('videos' or 'playlists'), defaults to 'videos'
        """
        try:
            secure_log(f"Downloading thumbnail: {url}", 'info')
            
            response = requests.get(url, timeout=30, stream=True)
            response.raise_for_status()
            
            img_data = response.content
            
            try:
                img = Image.open(io.BytesIO(img_data))
                img.verify()
                
                if img.format.lower() not in ['jpeg', 'jpg', 'png', 'webp']:
                    secure_log(f"Unsupported image format: {img.format}", 'warning')
                    return None
                
                img = Image.open(io.BytesIO(img_data))
                
                if img.mode == 'RGBA':
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[3])
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                output = io.BytesIO()
                img.save(output, format='JPEG', quality=85, optimize=True)
                output.seek(0)

                result = upload_file_to_storage(output, 'thumbnails', f"{folder}/{filename}")
                
                if result:
                    secure_log(f"Thumbnail saved: {result}", 'info')
                    return result
                else:
                    secure_log("Thumbnail upload failed", 'error')
                    return None
                    
            except Exception as img_error:
                secure_log(f"Image processing error: {img_error}", 'error')
                return None
                
        except Exception as e:
            secure_log(f"Thumbnail download failed: {e}", 'error')
            return None
    
    
    @retry_with_backoff()
    def download_profile_picture(self, channel_id, profile_url=None):
        """Download and save creator's profile picture"""
        try:
            if not profile_url:
                channel_request = self.youtube_service.channels().list(
                    part='snippet',
                    id=channel_id
                )
                channel_response = channel_request.execute()
                
                if not channel_response.get('items'):
                    secure_log(f"Channel not found: {channel_id}", 'error')
                    return None
                
                thumbnails = channel_response['items'][0]['snippet']['thumbnails']
                
                if 'high' in thumbnails:
                    profile_url = thumbnails['high']['url']
                elif 'medium' in thumbnails:
                    profile_url = thumbnails['medium']['url']
                elif 'default' in thumbnails:
                    profile_url = thumbnails['default']['url']
                else:
                    secure_log("No profile picture available", 'warning')
                    return None
            
            secure_log(f"Downloading profile picture: {profile_url}", 'info')
            
            response = requests.get(profile_url, timeout=30, stream=True)
            response.raise_for_status()
            
            img_data = response.content
            
            try:
                img = Image.open(io.BytesIO(img_data))
                img.verify()
                
                img = Image.open(io.BytesIO(img_data))
                
                if img.mode == 'RGBA':
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[3])
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                img = img.resize((400, 400), Image.Resampling.LANCZOS)
                
                output = io.BytesIO()
                img.save(output, format='JPEG', quality=90, optimize=True)
                output.seek(0)
                
                filename = f"{channel_id}_profile.jpg"
                result = save_file(output, 'profile_pictures', filename)
                
                if result:
                    secure_log(f"Profile picture saved: {result}", 'info')
                    return result
                else:
                    secure_log("Profile picture upload failed", 'error')
                    return None
                    
            except Exception as img_error:
                secure_log(f"Image processing error: {img_error}", 'error')
                return None
                
        except HttpError as e:
            if e.resp.status == 401:
                secure_log("YouTube token expired", 'error')
                raise YouTubeTokenExpiredError("YouTube OAuth token has expired")
            secure_log(f"YouTube API error: {e}", 'error')
            return None
        except Exception as e:
            secure_log(f"Profile picture download failed: {e}", 'error')
            return None
    
    
    def check_caption_availability(self, video_id: str) -> Dict[str, Any]:
        """Check if captions are available for a video"""
        try:
            captions_request = self.youtube_service.captions().list(
                part='snippet',
                videoId=video_id
            )
            captions_response = captions_request.execute()
            
            items = captions_response.get('items', [])
            
            if not items:
                return {
                    'has_captions': False,
                    'auto_generated': False,
                    'manual_captions': False,
                    'languages': [],
                    'error': None
                }
            
            auto_generated = any(
                item['snippet'].get('trackKind') == 'asr' 
                for item in items
            )
            
            manual_captions = any(
                item['snippet'].get('trackKind') == 'standard' 
                for item in items
            )
            
            languages = [
                item['snippet'].get('language', 'unknown') 
                for item in items
            ]
            
            return {
                'has_captions': True,
                'auto_generated': auto_generated,
                'manual_captions': manual_captions,
                'languages': languages,
                'error': None
            }
            
        except HttpError as e:
            if e.resp.status == 403:
                return {
                    'has_captions': False,
                    'auto_generated': False,
                    'manual_captions': False,
                    'languages': [],
                    'error': 'Captions disabled or private'
                }
            elif e.resp.status == 401:
                raise YouTubeTokenExpiredError("YouTube OAuth token has expired")
            else:
                return self._get_empty_caption_result(str(e))
        except Exception as e:
            return self._get_empty_caption_result(str(e))
    
    
    def _get_empty_caption_result(self, error=None):
        """Get empty caption result"""
        return {
            'has_captions': False,
            'auto_generated': False,
            'manual_captions': False,
            'languages': [],
            'error': error
        }
    
    
    def clean_srt_captions(self, srt_text: str) -> str:
        """Clean SRT caption text"""
        lines = srt_text.split('\n')
        cleaned_lines = []
        
        for line in lines:
            line = line.strip()
            
            # Skip sequence numbers
            if line.isdigit():
                continue
            
            # Skip timestamps
            if '-->' in line:
                continue
            
            # Skip empty lines
            if not line:
                continue
            
            cleaned_lines.append(line)
        
        return ' '.join(cleaned_lines)
    
    
    @retry_with_backoff()
    def get_video_captions(self, video_id):
        """Get video captions/transcript"""
        try:
            caption_info = self.check_caption_availability(video_id)
            
            if not caption_info['has_captions']:
                secure_log(f"No captions available for video {video_id}", 'warning')
                return None
            
            captions_request = self.youtube_service.captions().list(
                part='snippet',
                videoId=video_id
            )
            captions_response = captions_request.execute()
            
            items = captions_response.get('items', [])
            if not items:
                return None
            
            # Prefer manual captions over auto-generated
            caption_id = None
            for item in items:
                if item['snippet'].get('trackKind') == 'standard':
                    caption_id = item['id']
                    break
            
            if not caption_id:
                for item in items:
                    if item['snippet'].get('trackKind') == 'asr':
                        caption_id = item['id']
                        break
            
            if not caption_id:
                secure_log("No suitable caption track found", 'warning')
                return None
            
            download_request = self.youtube_service.captions().download(
                id=caption_id,
                tfmt='srt'
            )
            
            caption_text = download_request.execute()
            
            if isinstance(caption_text, bytes):
                caption_text = caption_text.decode('utf-8', errors='ignore')
            
            cleaned_text = self.clean_srt_captions(caption_text)
            
            secure_log(f"Captions retrieved: {len(cleaned_text)} chars", 'info')
            return cleaned_text
            
        except HttpError as e:
            if e.resp.status == 401:
                raise YouTubeTokenExpiredError("YouTube OAuth token has expired")
            secure_log(f"Caption download failed: {e}", 'error')
            return None
        except Exception as e:
            secure_log(f"Caption retrieval error: {e}", 'error')
            return None
    
    
    # ========================================================================
    # GEMINI 3 FLASH PROCESSING (SUMMARY + QUESTIONS IN SINGLE CALL)
    # ========================================================================
    
    def _create_response_schema(self, num_questions: int) -> dict:
        """
        Create JSON schema for Gemini response.

        Schema includes:
        - questions: List of MCQ questions following Bloom's taxonomy (70% BT5-BT6, 30% BT1-BT4)

        NOTE: Summary generation removed to save tokens.
        """
        schema = {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "options": {
                                "type": "object",
                                "properties": {
                                    "A": {"type": "string"},
                                    "B": {"type": "string"},
                                    "C": {"type": "string"},
                                    "D": {"type": "string"}
                                },
                                "required": ["A", "B", "C", "D"]
                            },
                            "correct_answer": {"type": "string", "enum": ["A", "B", "C", "D"]},
                            "explanation": {"type": "string"}
                        },
                        "required": ["question", "options", "correct_answer", "explanation"]
                    }
                }
            },
            "required": ["questions"]
        }

        return schema
    
    
    def _create_combined_prompt(self, transcript: str, title: str, num_questions: int) -> str:
        """
        Create prompt for question generation only (summary generation removed to save tokens).

        NEW DISTRIBUTION: 70% application-based (BT5-BT6), 30% foundational (BT1-BT4)
        """
        # Calculate NEW Bloom's taxonomy distribution (70% BT5-BT6, 30% BT1-BT4)
        bt5_bt6_count = int(num_questions * 0.70)  # 70% application-based
        bt1_bt4_count = num_questions - bt5_bt6_count  # 30% foundational

        # Distribute 70% across BT5 and BT6
        bt5_count = int(bt5_bt6_count * 0.5)
        bt6_count = bt5_bt6_count - bt5_count

        # Distribute 30% across BT1-BT4
        bt1_count = int(bt1_bt4_count * 0.30)
        bt2_count = int(bt1_bt4_count * 0.30)
        bt3_count = int(bt1_bt4_count * 0.25)
        bt4_count = bt1_bt4_count - (bt1_count + bt2_count + bt3_count)

        tech_count = int(num_questions * 0.30)
        conceptual_count = num_questions - tech_count

        prompt = f"""SYSTEM: You are an expert educational content analyzer and advanced exam designer specializing in application-based assessment.

TASK: Analyze the following educational content and generate EXACTLY {num_questions} high-quality MCQ questions.

=== CRITICAL INSTRUCTIONS ===

1. QUESTION COUNT: Generate EXACTLY {num_questions} questions. NO MORE, NO LESS.
2. NO HALLUCINATION: Base questions ONLY on content present in the transcript. Do not invent information.
3. RETURN ONLY JSON: Output must be valid JSON only. No preamble, no markdown, no explanation text.
4. FOCUS ON TOPIC CONTENT: Questions must test understanding of the ACTUAL SUBJECT MATTER, not meta-commentary about the video/content itself.

=== COGNITIVE DISTRIBUTION (Bloom's Taxonomy) ===

TOTAL {num_questions} QUESTIONS DISTRIBUTED AS:

FOUNDATIONAL (30% = {bt1_bt4_count} questions):
- BT1 (Remember) = {bt1_count} questions - Recall facts, terms, definitions
- BT2 (Understand) = {bt2_count} questions - Explain concepts, summarize ideas
- BT3 (Apply) = {bt3_count} questions - Use knowledge in new situations
- BT4 (Analyze) = {bt4_count} questions - Break down concepts, find patterns

APPLICATION-BASED (70% = {bt5_bt6_count} questions):
- BT5 (Evaluate) = {bt5_count} questions - Judge validity, critique approaches, compare solutions
- BT6 (Create) = {bt6_count} questions - Design solutions, propose implementations, synthesize ideas

=== TECHNICAL vs CONCEPTUAL ===

If technical content: ~{tech_count} technical questions (code, syntax, debugging, operations, architecture)
Remaining {conceptual_count} conceptual questions (theory, principles, best practices, trade-offs)
If not technical: all {num_questions} conceptual questions

=== SPECIAL INSTRUCTIONS FOR TECHNICAL CONTENT ===

For PROGRAMMING topics (Python, Java, JavaScript, OOP, algorithms, data structures, etc.):
- BT5/BT6 questions MUST include actual CODE SNIPPETS in the question
- Question types should include:
  * "What is the output of this code?" (with code snippet)
  * "Find the error in this code" (with buggy code)
  * "Which code correctly implements X?" (compare implementations)
  * "Debug this code to fix Y issue" (with problematic code)
- CODE FORMATTING: Use \\n for newlines and proper indentation (4 spaces for Python, 2-4 for JS)
- Example format in question text:
  "What is the output of the following Python code?\\n\\nclass Animal:\\n    def __init__(self, name):\\n        self.name = name\\n\\ndog = Animal('Rex')\\nprint(dog.name)"

For SOFTWARE/TOOLS topics (Excel, Photoshop, databases, cloud platforms, etc.):
- BT5/BT6 questions should focus on:
  * "What is the correct sequence of steps to achieve X?"
  * "Which formula/function would you use to accomplish Y?"
  * "Given this scenario, what is the most efficient approach?"
  * Practical task-based scenarios with specific tool features

For SCIENTIFIC/TECHNICAL topics (quantum mechanics, physics, chemistry, engineering, etc.):
- BT5/BT6 questions should include:
  * Problem-solving with given data/equations
  * "Calculate the result given these parameters"
  * Real-world application scenarios
  * Analysis of experimental results or data

=== QUESTION QUALITY REQUIREMENTS ===

DIFFICULTY LEVEL:
- Advanced undergraduate to graduate level
- Test DEEP understanding, not superficial recall
- Require critical thinking and real-world application

CONTENT FOCUS:
- Questions must be about the TOPIC CONTENT (e.g., "How would you optimize...", "What approach best solves...")
- Write questions as if they are from a professional exam or textbook - NOT from a video/transcript
- Questions should sound like they were written by a subject matter expert

ABSOLUTELY FORBIDDEN PHRASES (NEVER USE THESE):
× "According to the text/video/transcript/content/passage..."
× "The text states/mentions/says..."
× "As discussed/mentioned in the material/video/lecture..."
× "The speaker/instructor/author says/claims/states..."
× "Based on the passage/reading/content..."
× "The tutorial/lesson explains..."
× "From the transcript/caption..."
× "What does the text suggest/underscore/imply..."
× "The content indicates..."
× Any reference to "the text", "the video", "the transcript", "the material", "the passage"

INSTEAD, phrase questions directly about the subject matter:
✓ "What is the most effective approach to..." (not "According to the text, what is...")
✓ "Which marketing strategy would best..." (not "The text mentions which strategy...")
✓ "In object-oriented programming, what is..." (not "The tutorial explains that...")
✓ "When implementing X, which approach..." (not "Based on the content, which approach...")
✓ "A company wants to increase customer satisfaction. What should..." (scenario-based)

Focus on WHAT is being taught, not HOW it was presented

QUESTION DIVERSITY:
- Each question tests a DIFFERENT concept (no rephrasing or repeated themes)
- Include: scenario-based, what-if analysis, trade-off comparison, error diagnosis, optimization
- Mix practical application with theoretical understanding

=== ANSWER FORMAT RULES ===

OPTIONS:
- Exactly 4 options labeled A, B, C, D
- Only ONE correct answer
- Distractors must be:
  * Realistic misconceptions a learner might have
  * Plausible but incorrect for specific technical reasons
  * NOT absurd or obviously wrong
- No "all of the above" or "none of the above"

EXPLANATIONS:
- Concise (1-3 sentences)
- Explain WHY the correct answer is right
- Optionally mention why key distractors are wrong

=== OUTPUT FORMAT ===

Return ONLY this valid JSON structure (no other text):

{{
  "questions": [
    {{
      "question": "Question text here?",
      "options": {{
        "A": "First option",
        "B": "Second option",
        "C": "Third option",
        "D": "Fourth option"
      }},
      "correct_answer": "A",
      "explanation": "Why this answer is correct"
    }}
  ]
}}

=== INPUT DATA ===

TITLE: {title}

TRANSCRIPT:
{transcript}

=== TASK EXECUTION ===

Generate EXACTLY {num_questions} questions in valid JSON format.

CRITICAL REMINDERS:
- NEVER reference "the text", "the video", "the transcript", "the material" in any question
- Write questions as if from a professional certification exam or university textbook
- Focus on testing knowledge of the SUBJECT MATTER directly
- Prioritize application-based questions (70% BT5-BT6)
- No hallucination - only use concepts from the provided content
- Return only valid JSON
"""

        return prompt
    
    
    @retry_with_backoff(max_retries=3, base_delay=5.0, max_delay=30.0)
    def process_chunk_with_gemini(
        self,
        transcript_chunk: str,
        title: str,
        num_questions: int,
        chunk_index: int = 0
    ) -> List[dict]:
        """
        Process single chunk with Gemini 2.5 Flash using REST API (NO SDK, NO gRPC).

        Uses pure HTTP requests with 3600 second timeout for gevent compatibility.

        NOTE: Summary generation removed to save tokens.

        Returns:
            List[dict]: questions_list only (summary removed)
        """
        try:
            secure_log(
                f"Processing chunk {chunk_index} with Gemini REST API (questions: {num_questions})",
                'info'
            )
            
            # No-op: API keys never expire (replaces OAuth token refresh)
            self._ensure_token_fresh()

            # Create prompt
            prompt = self._create_combined_prompt(transcript_chunk, title, num_questions)

            # Create schema
            schema = self._create_response_schema(num_questions)

            # Build Gemini REST API request payload
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.4,
                    "maxOutputTokens": MAX_OUTPUT_TOKENS,
                    "responseMimeType": "application/json",
                    "responseSchema": schema
                }
            }

            # SECURITY: API key sent via header, NOT as a URL query param.
            # Query params appear in access logs and proxy caches; headers do not.
            headers = {
                "x-goog-api-key": self.gemini_api_key,
                "Content-Type": "application/json"
            }

            # ── Gemini REST call with 429 exponential-backoff retry ──────────
            MAX_GEMINI_RETRIES = 5
            BASE_BACKOFF_SECONDS = 15      # wait 15 s after first 429
            response = None

            for attempt in range(1, MAX_GEMINI_RETRIES + 1):
                try:
                    response = requests.post(
                        self.vertex_ai_endpoint,
                        headers=headers,
                        json=payload,
                        timeout=3600  # 1 hour timeout for long video processing
                    )
                except requests.exceptions.Timeout:
                    secure_log(
                        f"Gemini REST API timeout for chunk {chunk_index} "
                        f"(attempt {attempt}/{MAX_GEMINI_RETRIES})", 'error'
                    )
                    return []
                except requests.exceptions.RequestException as e:
                    secure_log(
                        f"Gemini REST API network error for chunk {chunk_index}: {e} "
                        f"(attempt {attempt}/{MAX_GEMINI_RETRIES})", 'error'
                    )
                    return []

                if response.status_code == 429:
                    # Respect server-provided Retry-After, else use exponential backoff
                    retry_after = int(response.headers.get('Retry-After', 0))
                    wait_seconds = retry_after if retry_after > 0 else BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))

                    if attempt < MAX_GEMINI_RETRIES:
                        secure_log(
                            f"Gemini 429 rate-limit hit for chunk {chunk_index}. "
                            f"Retrying in {wait_seconds}s "
                            f"(attempt {attempt}/{MAX_GEMINI_RETRIES})", 'warning'
                        )
                        import time as _time
                        _time.sleep(wait_seconds)
                        continue  # retry the loop
                    else:
                        secure_log(
                            f"Gemini 429 rate-limit persisted after {MAX_GEMINI_RETRIES} retries "
                            f"for chunk {chunk_index}. Skipping chunk.", 'error'
                        )
                        return []

                # Any non-429 HTTP error → raise immediately (no retry)
                try:
                    response.raise_for_status()
                except requests.exceptions.HTTPError as http_err:
                    secure_log(
                        f"Gemini REST API HTTP error {response.status_code} "
                        f"for chunk {chunk_index}: {http_err}", 'error'
                    )
                    return []

                break  # success — exit retry loop

            result = response.json()

            # Extract generated text from REST response
            if 'candidates' in result and len(result['candidates']) > 0:
                candidate = result['candidates'][0]
                if 'content' in candidate and 'parts' in candidate['content']:
                    generated_text = candidate['content']['parts'][0].get('text', '')
                else:
                    secure_log("No content in Gemini response", 'error')
                    return []
            else:
                secure_log("No candidates in Gemini response", 'error')
                return []

            # Parse JSON response
            try:
                parsed_result = json.loads(generated_text)
            except json.JSONDecodeError:
                # Try to repair JSON
                secure_log("Attempting JSON repair", 'warning')
                try:
                    repaired = self._repair_json_output(generated_text, f"chunk_{chunk_index}")
                    parsed_result = json.loads(repaired)
                except Exception as repair_err:
                    # Repair also failed — log and return empty so other chunks can still succeed
                    secure_log(
                        f"JSON repair failed for chunk {chunk_index}: {repair_err}. "
                        "Skipping chunk gracefully.", 'error'
                    )
                    return []

            # Extract questions (summary removed)
            questions = parsed_result.get('questions', [])

            # Validate questions
            valid_questions = [
                q for q in questions
                if self._validate_question_structure(q)
            ]

            # Ensure exact count
            if len(valid_questions) > num_questions:
                valid_questions = valid_questions[:num_questions]

            secure_log(
                f"Chunk {chunk_index} processed: {len(valid_questions)} valid questions",
                'info'
            )

            return valid_questions

        except Exception as e:
            secure_log(f"Gemini processing error for chunk {chunk_index}: {e}", 'error')
            return []
    
    
    def summarize_captions_realtime(
        self,
        captions: str,
        title: str = "",
        video_id: str = "",
        duration_seconds: int = 0
    ) -> List[dict]:
        """
        Generate questions from captions using Gemini 2.5 Flash.

        NOTE: Summary generation removed to save tokens.

        OPTIMIZED FOR VERY LONG VIDEOS with:
        - Dynamic worker scaling (up to 5 workers)
        - Real-time progress tracking in database
        - Checkpoint recovery for failed processing

        Chunking logic:
        - ≤30K tokens: Single API call
        - 30K-120K tokens: Multiple 30K chunks, async processing
        - >120K tokens: Random sampling then chunking

        Returns:
            List[dict]: all_questions only (summary removed)
        """
        try:
            secure_log(
                f"Starting Gemini processing for {video_id}",
                'info',
                video_id=video_id
            )

            # Clean captions
            cleaned_captions = self.clean_srt_captions(captions) if captions else ""

            if not cleaned_captions:
                secure_log("No captions to process", 'warning')
                return []

            # Chunk transcript
            chunks = self.chunker.chunk_text(cleaned_captions)
            num_chunks = len(chunks)

            secure_log(f"Processing {num_chunks} chunks", 'info')

            # Initialize processing variables
            all_questions = []

            # Calculate questions per chunk
            total_questions = 50  # Default
            questions_per_chunk = []

            if num_chunks == 1:
                questions_per_chunk = [total_questions]
            else:
                # Distribute questions across chunks
                base_questions = total_questions // num_chunks
                remainder = total_questions % num_chunks

                for i in range(num_chunks):
                    q_count = base_questions
                    if i < remainder:
                        q_count += 1
                    questions_per_chunk.append(q_count)

            # Update processing status with total chunks for progress tracking
            if hasattr(self, 'channel_id') and self.channel_id:
                set_processing_status(
                    video_id,
                    self.channel_id,
                    'processing',
                    'video',
                    total_chunks=num_chunks,
                    processed_chunks=0,
                    progress_percentage=0,
                    current_stage='Starting AI processing...'
                )

            # Process chunks (async for speed)
            if num_chunks == 1:
                # Update stage for single chunk
                if hasattr(self, 'channel_id') and self.channel_id:
                    set_processing_status(
                        video_id,
                        self.channel_id,
                        'processing',
                        'video',
                        current_stage='Generating questions...'
                    )

                # Single chunk - direct call
                questions = self.process_chunk_with_gemini(
                    chunks[0],
                    title,
                    questions_per_chunk[0],
                    chunk_index=0
                )
                all_questions.extend(questions)

                # Update progress to 100%
                if hasattr(self, 'channel_id') and self.channel_id:
                    set_processing_status(
                        video_id,
                        self.channel_id,
                        'processing',
                        'video',
                        processed_chunks=1,
                        progress_percentage=100,
                        current_stage='Finalizing...'
                    )
            else:
                # ── MULTI-CHUNK: sequential submission, limited concurrency ────
                #
                # Why max_workers=2 instead of 5?
                # Sending 5 simultaneous Gemini requests is the #1 cause of 429 errors.
                # With 2 workers + 6s stagger the API stays within free-tier rate limits.
                # Processing is a bit slower but it COMPLETES instead of crashing.
                max_workers = min(num_chunks, 2)
                secure_log(f"Using {max_workers} concurrent workers for {num_chunks} chunks", 'info')

                # Update stage
                if hasattr(self, 'channel_id') and self.channel_id:
                    set_processing_status(
                        video_id,
                        self.channel_id,
                        'processing',
                        'video',
                        current_stage=f'Processing {num_chunks} chunks with {max_workers} workers...'
                    )

                # CHUNK SUBMISSION: stagger each submission by 6s to spread Gemini load.
                # With 2 workers this means at most 2 in-flight at once, well within rate limits.
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = []

                    for i in range(num_chunks):
                        if i > 0:
                            import time
                            time.sleep(6.0)  # 6s stagger keeps requests well below rate limit

                        future = executor.submit(
                            self.process_chunk_with_gemini,
                            chunks[i],
                            title,
                            questions_per_chunk[i],
                            i
                        )
                        futures.append((i, future))

                    # Collect results — use a 2-hour per-future timeout so that even a chunk
                    # undergoing full 429 exponential backoff (max ~470s) can still finish.
                    # The underlying HTTP timeout (3600s) is the real hard ceiling per attempt.
                    CHUNK_TIMEOUT_SECONDS = 7200  # 2 hours
                    completed_chunks = 0

                    for chunk_idx, future in futures:
                        try:
                            questions = future.result(timeout=CHUNK_TIMEOUT_SECONDS)
                            all_questions.extend(questions)

                            completed_chunks += 1
                            progress = round((completed_chunks / num_chunks) * 100, 2)

                            # Update progress in database for frontend tracking
                            if hasattr(self, 'channel_id') and self.channel_id:
                                set_processing_status(
                                    video_id,
                                    self.channel_id,
                                    'processing',
                                    'video',
                                    processed_chunks=completed_chunks,
                                    progress_percentage=progress,
                                    current_stage=f'Processed chunk {completed_chunks}/{num_chunks}'
                                )

                            secure_log(
                                f"Chunk {chunk_idx+1}/{num_chunks} completed ({progress}%)",
                                'info',
                                video_id=video_id
                            )

                        except Exception as e:
                            # Log the failure but KEEP going — partial results are better than nothing.
                            secure_log(
                                f"Chunk {chunk_idx} failed (will skip): {e}", 'warning'
                            )

            secure_log(
                f"Processing complete: {len(all_questions)} questions generated",
                'info'
            )

            return all_questions

        except Exception as e:
            # Something crashed OUTSIDE the chunk loop (e.g. chunking, DB calls).
            # Still return whatever questions were collected before the crash — partial
            # results are far better than a complete failure for the user.
            secure_log(
                f"Caption processing outer error: {e}. "
                f"Returning {len(all_questions)} partial questions.",
                'error', video_id=video_id
            )
            return all_questions if all_questions else []
    
    
    def _validate_question_structure(self, question: dict) -> bool:
        """Validate question structure (EXACT from original)"""
        if not isinstance(question, dict):
            return False
        
        required_fields = ['question', 'options', 'correct_answer', 'explanation']
        if not all(field in question for field in required_fields):
            return False
        
        options = question.get('options')
        if not isinstance(options, dict) or set(options.keys()) != {'A', 'B', 'C', 'D'}:
            return False
        
        if question.get('correct_answer') not in options:
            return False
        
        if not (isinstance(question.get('question'), str) and 
                5 < len(question['question']) < 1000 and
                isinstance(question.get('explanation'), str) and 
                5 < len(question['explanation']) < 2000):
            return False
        
        return True
    
    
    def _repair_json_output(self, json_string: str, content_type: str = "questions") -> str:
        """
        Attempts to repair common structural errors in a JSON string.

        Enhanced to extract maximum questions from partial/truncated JSON.
        Uses multi-stage repair strategy to ensure exactly 100 questions when possible.
        """
        secure_log(f"Attempting to repair JSON output for {content_type}.", 'warning')
        try:
            # Stage 1: Try standard json_repair library
            try:
                repaired_json = json_repair.repair_json(json_string)
                parsed = json.loads(repaired_json)

                # If we got valid JSON with questions, check count
                if 'questions' in parsed and isinstance(parsed['questions'], list):
                    question_count = len(parsed['questions'])
                    secure_log(f"JSON repair successful: {question_count} questions extracted.", 'info')
                    return repaired_json
            except Exception as stage1_err:
                secure_log(f"Stage 1 repair failed: {stage1_err}", 'warning')

            # Stage 2: Manual repair for truncated JSON (common with large outputs)
            secure_log("Attempting Stage 2: Manual repair for truncated JSON", 'info')

            # Find the start of questions array
            questions_start = json_string.find('"questions"')
            if questions_start == -1:
                secure_log("No 'questions' key found in response", 'error')
                return json_string

            # Extract everything from questions onwards
            questions_section = json_string[questions_start:]

            # Find the opening bracket of the questions array
            array_start = questions_section.find('[')
            if array_start == -1:
                secure_log("No questions array found", 'error')
                return json_string

            # Extract the array content
            array_content = questions_section[array_start:]

            # Try to find complete question objects, even if array is truncated
            questions = []
            depth = 0
            current_obj = ""
            in_string = False
            escape_next = False

            for char in array_content:
                if escape_next:
                    current_obj += char
                    escape_next = False
                    continue

                if char == '\\':
                    escape_next = True
                    current_obj += char
                    continue

                if char == '"' and not escape_next:
                    in_string = not in_string

                current_obj += char

                if not in_string:
                    if char == '{':
                        depth += 1
                    elif char == '}':
                        depth -= 1
                        if depth == 0 and current_obj.strip().startswith('{'):
                            # Complete question object found
                            try:
                                question_obj = json.loads(current_obj.strip().rstrip(','))
                                if self._validate_question_structure(question_obj):
                                    questions.append(question_obj)
                            except:
                                pass  # Skip malformed question
                            current_obj = ""

            # Build repaired JSON with extracted questions
            repaired_structure = {
                "questions": questions
            }

            repaired_json_str = json.dumps(repaired_structure, ensure_ascii=False)
            secure_log(f"Stage 2 repair successful: {len(questions)} questions extracted from partial JSON", 'info')
            return repaired_json_str

        except Exception as e:
            secure_log(f"All JSON repair stages failed for {content_type}: {str(e)}", 'error')
            # Return minimal valid structure to prevent crash
            return '{"questions": []}'
    
    
    # NOTE: save_summary_to_file() removed - summary generation disabled to save tokens


    # ========================================================================
    # VIDEO PROCESSING
    # ========================================================================
    
    def _format_duration(self, seconds):
        """Format duration in seconds to HH:MM:SS"""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    
    @retry_with_backoff()
    def get_video_details(self, video_id):
        """Get video details from YouTube API"""
        try:
            request = self.youtube_service.videos().list(
                part='snippet,contentDetails,statistics',
                id=video_id
            )
            response = request.execute()
            
            if not response.get('items'):
                secure_log(f"Video not found: {video_id}", 'error')
                return None
            
            item = response['items'][0]
            snippet = item.get('snippet', {})
            content_details = item.get('contentDetails', {})
            statistics = item.get('statistics', {})
            
            # Parse duration
            duration_iso = content_details.get('duration', 'PT0S')
            duration = isodate.parse_duration(duration_iso)
            duration_seconds = int(duration.total_seconds())
            
            # Get thumbnail URL
            thumbnails = snippet.get('thumbnails', {})
            thumbnail_url = None
            for quality in ['maxres', 'high', 'medium', 'default']:
                if quality in thumbnails:
                    thumbnail_url = thumbnails[quality]['url']
                    break
            
            video_data = {
                'video_id': video_id,
                'title': snippet.get('title', 'Untitled'),
                'description': snippet.get('description', ''),
                'thumbnail_url': thumbnail_url,
                'duration_seconds': duration_seconds,
                'duration_formatted': self._format_duration(duration_seconds),
                'view_count': int(statistics.get('viewCount', 0)),
                'like_count': int(statistics.get('likeCount', 0)),
                'published_at': snippet.get('publishedAt'),
                'channel_id': self.channel_id,
            }
            
            return video_data
            
        except HttpError as e:
            if e.resp.status == 401:
                raise YouTubeTokenExpiredError("YouTube OAuth token has expired")
            secure_log(f"YouTube API error: {e}", 'error')
            return None
        except Exception as e:
            secure_log(f"Error getting video details: {e}", 'error')
            return None
    
    
    def process_video_with_realtime_summary(
        self,
        video_data,
        playlist_id=None,
        playlist_position=None
    ):
        """Process video with Gemini summarization and question generation"""
        video_id = video_data['video_id']
        
        try:
            secure_log(f"Processing video: {video_id}", 'info', video_id=video_id)

            # Initialize processing status with stage info
            set_processing_status(
                video_id,
                self.channel_id,
                'processing',
                'video',
                current_stage='Downloading thumbnail...',
                progress_percentage=5
            )

            # Download thumbnail
            thumbnail_path = None
            if video_data.get('thumbnail_url'):
                thumbnail_filename = f"{video_id}.jpg"
                thumbnail_path = self.download_thumbnail(
                    video_data['thumbnail_url'],
                    thumbnail_filename,
                    folder='videos'
                )

            # Update stage: Getting captions
            set_processing_status(
                video_id,
                self.channel_id,
                'processing',
                'video',
                current_stage='Downloading transcript...',
                progress_percentage=15
            )

            # Get captions
            captions = self.get_video_captions(video_id)

            transcript_path = None
            questions = []

            if captions:
                # Update stage: Saving transcript
                set_processing_status(
                    video_id,
                    self.channel_id,
                    'processing',
                    'video',
                    current_stage='Saving transcript...',
                    progress_percentage=25
                )

                # Save transcript
                transcript_filename = f"{video_id}.txt"
                transcript_bytes = captions.encode('utf-8')
                transcript_path = upload_file_to_storage(
                    transcript_bytes,
                    'transcripts',
                    f"videos/{transcript_filename}"
                )

                # Update stage: AI Processing (will be updated further in summarize_captions_realtime)
                set_processing_status(
                    video_id,
                    self.channel_id,
                    'processing',
                    'video',
                    current_stage='Processing with AI...',
                    progress_percentage=30
                )

                # Process with Gemini (questions only - summary removed to save tokens)
                questions = self.summarize_captions_realtime(
                    captions,
                    title=video_data['title'],
                    video_id=video_id,
                    duration_seconds=video_data['duration_seconds']
                )

            # Update video data (preserve all fields including description, summary_path removed)
            video_data.update({
                'thumbnail_image': thumbnail_path,
                'transcript_path': transcript_path,
                'playlist_id': playlist_id,
                'position_in_playlist': playlist_position,
                'questions': questions,  # Store for later
                # Note: 'description' already exists in video_data from get_video_details
            })

            # Update processing status with file paths (summary_path removed)
            set_processing_status(
                video_id,
                self.channel_id,
                'completed',
                'video',
                transcript_path=transcript_path,
                chunk_count=1  # Will be updated by summarize_captions_realtime if multi-chunk
            )
            
            return video_data
            
        except YouTubeTokenExpiredError:
            set_processing_status(video_id, self.channel_id, 'failed', 'video')
            raise
        except Exception as e:
            secure_log(f"Video processing error: {e}", 'error', video_id=video_id)
            set_processing_status(video_id, self.channel_id, 'failed', 'video')
            raise
    
    
    def process_video(self, url, force_reprocess=False):
        """Process single video"""
        try:
            video_id = self.extract_video_id(url)
            if not video_id:
                return {
                    'success': False,
                    'message': 'Invalid video URL'
                }
            
            if is_processing(video_id, self.channel_id, 'video'):
                return {
                    'success': False,
                    'message': 'Video is already being processed'
                }
            
            existing = get_existing_video_data(video_id, self.channel_id)

            if existing and not force_reprocess:
                secure_log("Video previously processed - checking 15-day regeneration rule", 'info', video_id=video_id, channel_id=self.channel_id)

                # Check if questions exist for this video
                exam_number = existing.get('unique_exam_number')
                questions_updated_at = existing.get('questions_updated_at')

                # Check if questions actually exist in the database
                has_questions = exam_number and questions_updated_at

                if has_questions:
                    # Questions exist - check 15-day regeneration rule
                    can_regenerate, days_remaining, last_updated = can_regenerate_questions(exam_number)

                    if not can_regenerate:
                        # Block reprocessing - within 15-day window
                        secure_log(
                            f"Reprocessing blocked: {days_remaining} days remaining until regeneration allowed",
                            'warning',
                            video_id=video_id,
                            channel_id=self.channel_id
                        )
                        return {
                            'success': False,
                            'message': f'Video already processed. Questions can be regenerated after {days_remaining} days.',
                            'error_code': 'REGENERATION_BLOCKED',
                            'days_remaining': days_remaining,
                            'last_updated': last_updated.isoformat() if last_updated else None
                        }

                    # 15 days passed - allow regeneration from saved transcript
                    secure_log(
                        f"15-day period passed - regenerating questions from saved transcript",
                        'info',
                        video_id=video_id,
                        channel_id=self.channel_id
                    )

                    transcript_path = existing.get('transcript_path')
                    if transcript_path:
                        # Regenerate questions from existing transcript
                        result = self.regenerate_questions_from_existing(
                            content_type='video',
                            content_id=video_id,
                            title=existing.get('title', 'Untitled'),
                            transcript_path=transcript_path,
                            exam_number=exam_number
                        )

                        if result.get('success'):
                            return {
                                'success': True,
                                'message': result.get('message', 'Questions regenerated successfully'),
                                'data': existing,
                                'regenerated': True,
                                'question_count': result.get('question_count', 0)
                            }
                        else:
                            return {
                                'success': False,
                                'message': f"Question regeneration failed: {result.get('message')}",
                                'error_code': 'REGENERATION_FAILED'
                            }
                    else:
                        return {
                            'success': False,
                            'message': 'No saved transcript found for regeneration',
                            'error_code': 'NO_TRANSCRIPT'
                        }

                # No questions exist yet - ALLOW REPROCESSING to generate questions
                secure_log("No exam questions found - allowing reprocessing to generate questions", 'info', video_id=video_id, channel_id=self.channel_id)
                # Fall through to process the video and generate questions
            
            video_data = self.get_video_details(video_id)
            if not video_data:
                return {
                    'success': False,
                    'message': 'Failed to get video details'
                }
            
            processed_data = self.process_video_with_realtime_summary(video_data)
            
            # Extract questions for separate storage
            questions = processed_data.pop('questions', [])

            # Insert video
            self.insert_video_data([processed_data])

            # ALWAYS create exam entry in listed_exams (even without questions)
            exam_number = self.save_to_listed_exams(processed_data, 'video')

            # Save questions if they were generated
            if exam_number and questions:
                self.save_exam_questions_to_db(exam_number, questions)
            
            return {
                'success': True,
                'message': 'Video processed successfully',
                'data': processed_data
            }
            
        except YouTubeTokenExpiredError:
            secure_log("YouTube token expired during video processing", 'warning', video_id=video_id, channel_id=self.channel_id)
            return {
                'success': False,
                'message': 'YouTube token expired. Please reconnect.',
                'error_code': 'TOKEN_EXPIRED'
            }
        except Exception as e:
            secure_log(f"Video processing failed: {e}", 'error', video_id=video_id, channel_id=self.channel_id)
            return {
                'success': False,
                'message': str(e)
            }


    # ========================================================================
    # PLAYLIST PROCESSING (WITH COMBINED TRANSCRIPT)
    # ========================================================================
    
    @retry_with_backoff()
    def get_playlist_details(self, playlist_id):
        """Get playlist details from YouTube API"""
        try:
            playlist_request = self.youtube_service.playlists().list(
                part='snippet,contentDetails',
                id=playlist_id
            )
            playlist_response = playlist_request.execute()
            
            if not playlist_response.get('items'):
                secure_log(f"Playlist not found: {playlist_id}", 'error')
                return None
            
            playlist_item = playlist_response['items'][0]
            snippet = playlist_item.get('snippet', {})
            
            thumbnails = snippet.get('thumbnails', {})
            thumbnail_url = None
            for quality in ['maxres', 'high', 'medium', 'default']:
                if quality in thumbnails:
                    thumbnail_url = thumbnails[quality]['url']
                    break
            
            # Get videos in playlist
            videos = []
            next_page_token = None
            
            while True:
                items_request = self.youtube_service.playlistItems().list(
                    part='snippet,contentDetails',
                    playlistId=playlist_id,
                    maxResults=50,
                    pageToken=next_page_token
                )
                items_response = items_request.execute()
                
                for item in items_response.get('items', []):
                    video_id = item['contentDetails']['videoId']
                    position = item['snippet']['position']
                    videos.append({'video_id': video_id, 'position': position})
                
                next_page_token = items_response.get('nextPageToken')
                if not next_page_token:
                    break
            
            playlist_data = {
                'playlist_id': playlist_id,
                'title': snippet.get('title', 'Untitled Playlist'),
                'description': snippet.get('description', ''),
                'thumbnail_url': thumbnail_url,
                'video_count': len(videos),
                'videos': videos,
                'channel_id': self.channel_id,
            }
            
            return playlist_data
            
        except HttpError as e:
            if e.resp.status == 401:
                raise YouTubeTokenExpiredError("YouTube OAuth token has expired")
            secure_log(f"Playlist API error: {e}", 'error')
            return None
        except Exception as e:
            secure_log(f"Error getting playlist details: {e}", 'error')
            return None
    
    
    def _format_playlist_data(self, playlist_data_raw, videos_processed):
        """
        Format playlist data for database insertion.
        
        Calculates aggregated statistics from processed videos.
        
        Args:
            playlist_data_raw: Raw playlist data from YouTube API
            videos_processed: List of processed video data dicts
            
        Returns:
            dict: Formatted playlist data ready for database
        """
        try:
            playlist_id = playlist_data_raw.get('playlist_id')
            
            # Calculate totals
            total_duration = sum(video.get('duration_seconds', 0) for video in videos_processed)
            total_views = sum(video.get('view_count', 0) for video in videos_processed)

            formatted_data = {
                'playlist_id': playlist_id,
                'title': playlist_data_raw.get('title', ''),
                'playlist_description': playlist_data_raw.get('description', ''),
                'channel_id': self.channel_id,
                'thumbnail_image': playlist_data_raw.get('thumbnail_path', ''),
                'transcript_path': playlist_data_raw.get('transcript_path', ''),
                'video_count': len(videos_processed),
                'duration_seconds': total_duration,
                'total_views': total_views,
                'average_duration': total_duration // len(videos_processed) if videos_processed else 0,
                'processing_status': 'completed',
                'created_at': datetime.now()
            }
            
            return formatted_data
            
        except Exception as e:
            secure_log(f"Error formatting playlist data: {e}", 'error')
            return None
    
    
    def process_playlist(self, url, force_reprocess=False):
        """
        Process playlist with COMBINED TRANSCRIPT.
        
        Creates:
        1. Individual video transcripts (saved separately)
        2. Combined playlist transcript (video-wise concatenation)
        3. Playlist summary and questions from combined transcript
        """
        try:
            playlist_id = self.extract_playlist_id(url)
            if not playlist_id:
                return {
                    'success': False,
                    'message': 'Invalid playlist URL'
                }
            
            if is_processing(playlist_id, self.channel_id, 'playlist'):
                return {
                    'success': False,
                    'message': 'Playlist is already being processed'
                }

            # Check for existing playlist data and apply 15-day regeneration rule
            existing = get_existing_playlist_data(playlist_id, self.channel_id)

            if existing and not force_reprocess:
                secure_log("Playlist previously processed - checking 15-day regeneration rule", 'info', playlist_id=playlist_id, channel_id=self.channel_id)

                # Check if questions exist for this playlist
                exam_number = existing.get('unique_exam_number')
                questions_updated_at = existing.get('questions_updated_at')

                # Check if questions actually exist in the database
                has_questions = exam_number and questions_updated_at

                if has_questions:
                    # Questions exist - check 15-day regeneration rule
                    can_regenerate, days_remaining, last_updated = can_regenerate_questions(exam_number)

                    if not can_regenerate:
                        # Block reprocessing - within 15-day window
                        secure_log(
                            f"Playlist reprocessing blocked: {days_remaining} days remaining until regeneration allowed",
                            'warning',
                            playlist_id=playlist_id,
                            channel_id=self.channel_id
                        )
                        return {
                            'success': False,
                            'message': f'Playlist already processed. Questions can be regenerated after {days_remaining} days.',
                            'error_code': 'REGENERATION_BLOCKED',
                            'days_remaining': days_remaining,
                            'last_updated': last_updated.isoformat() if last_updated else None
                        }

                    # 15 days passed - allow regeneration from saved transcript
                    secure_log(
                        f"15-day period passed - regenerating playlist questions from saved transcript",
                        'info',
                        playlist_id=playlist_id,
                        channel_id=self.channel_id
                    )

                    transcript_path = existing.get('transcript_path')
                    if transcript_path:
                        # Regenerate questions from existing combined transcript
                        result = self.regenerate_questions_from_existing(
                            content_type='playlist',
                            content_id=playlist_id,
                            title=existing.get('title', 'Untitled Playlist'),
                            transcript_path=transcript_path,
                            exam_number=exam_number
                        )

                        if result.get('success'):
                            return {
                                'success': True,
                                'message': result.get('message', 'Playlist questions regenerated successfully'),
                                'data': existing,
                                'regenerated': True,
                                'question_count': result.get('question_count', 0)
                            }
                        else:
                            return {
                                'success': False,
                                'message': f"Question regeneration failed: {result.get('message')}",
                                'error_code': 'REGENERATION_FAILED'
                            }
                    else:
                        return {
                            'success': False,
                            'message': 'No saved combined transcript found for regeneration',
                            'error_code': 'NO_TRANSCRIPT'
                        }

                # No questions exist yet - ALLOW REPROCESSING to generate questions
                secure_log("No exam questions found for playlist - allowing reprocessing to generate questions", 'info', playlist_id=playlist_id, channel_id=self.channel_id)
                # Fall through to process the playlist and generate questions

            set_processing_status(playlist_id, self.channel_id, 'processing', 'playlist')

            playlist_data = self.get_playlist_details(playlist_id)
            if not playlist_data:
                set_processing_status(playlist_id, self.channel_id, 'failed', 'playlist')
                return {
                    'success': False,
                    'message': 'Failed to get playlist details'
                }

            # Playlist thumbnail will be set to the first video's thumbnail
            playlist_thumbnail_path = None

            # Process videos and collect transcripts
            processed_videos = []
            combined_transcript_parts = []
            total_duration = 0

            for video_info in playlist_data['videos']:
                video_id = video_info['video_id']
                position = video_info['position']

                video_details = self.get_video_details(video_id)
                if video_details:
                    # Get video caption
                    video_caption = self.get_video_captions(video_id)

                    if video_caption:
                        # Save individual transcript
                        transcript_filename = f"{video_id}.txt"
                        transcript_bytes = video_caption.encode('utf-8')
                        transcript_path = upload_file_to_storage(
                            transcript_bytes,
                            'transcripts',
                            f"videos/{transcript_filename}"
                        )

                        # Add to combined transcript
                        combined_transcript_parts.append(
                            f"=== VIDEO {position + 1}: {video_details['title']} ===\n\n{video_caption}\n\n"
                        )

                        video_details['transcript_path'] = transcript_path

                    # Download video thumbnail
                    if video_details.get('thumbnail_url'):
                        video_thumb_path = self.download_thumbnail(
                            video_details['thumbnail_url'],
                            f"{video_id}.jpg",
                            folder='videos'
                        )
                        video_details['thumbnail_image'] = video_thumb_path

                        # Use first video's thumbnail as playlist thumbnail
                        if playlist_thumbnail_path is None:
                            playlist_thumbnail_path = video_thumb_path

                    video_details['playlist_id'] = playlist_id
                    video_details['position_in_playlist'] = position

                    processed_videos.append(video_details)
                    total_duration += video_details.get('duration_seconds', 0)
            
            # Save combined transcript
            combined_transcript = "".join(combined_transcript_parts)
            combined_transcript_filename = f"{playlist_id}_combined.txt"
            combined_transcript_bytes = combined_transcript.encode('utf-8')
            combined_transcript_path = upload_file_to_storage(
                combined_transcript_bytes,
                'transcripts',
                f"playlists/{combined_transcript_filename}"
            )
            
            # Process combined transcript with Gemini
            playlist_questions = []

            if combined_transcript:
                playlist_questions = self.summarize_captions_realtime(
                    combined_transcript,
                    title=playlist_data['title'],
                    video_id=playlist_id,
                    duration_seconds=total_duration
                )

            # Insert videos
            if processed_videos:
                self.insert_video_data(processed_videos)

            # Insert playlist (summary_path removed)
            final_playlist_data = {
                'playlist_id': playlist_id,
                'title': playlist_data['title'],
                'playlist_description': playlist_data['description'],
                'description': playlist_data['description'],  # For listed_exams table
                'thumbnail_image': playlist_thumbnail_path,
                'transcript_path': combined_transcript_path,  # Combined transcript
                'video_count': len(processed_videos),
                'duration_seconds': total_duration,
                'channel_id': self.channel_id,
            }

            self.insert_playlist_data(final_playlist_data)

            # ALWAYS create exam entry in listed_exams (even without questions)
            exam_number = self.save_to_listed_exams(final_playlist_data, 'playlist')

            # Save questions if they were generated
            if exam_number and playlist_questions:
                self.save_exam_questions_to_db(exam_number, playlist_questions)
            
            set_processing_status(playlist_id, self.channel_id, 'completed', 'playlist')
            
            return {
                'success': True,
                'message': 'Playlist processed successfully',
                'data': {
                    'playlist': final_playlist_data,
                    'videos': processed_videos
                }
            }
            
        except YouTubeTokenExpiredError:
            set_processing_status(playlist_id, self.channel_id, 'failed', 'playlist')
            return {
                'success': False,
                'message': 'YouTube token expired. Please reconnect.',
                'error_code': 'TOKEN_EXPIRED'
            }
        except Exception as e:
            set_processing_status(playlist_id, self.channel_id, 'failed', 'playlist')
            secure_log(f"Playlist processing failed: {e}", 'error')
            return {
                'success': False,
                'message': str(e)
            }
    
    
    def process_url(self, url, force_reprocess=False):
        """Process URL (auto-detect video or playlist)"""
        if self.is_playlist_url(url):
            return self.process_playlist(url, force_reprocess)
        else:
            return self.process_video(url, force_reprocess)
    
    
    # ========================================================================
    # DATABASE OPERATIONS
    # ========================================================================
    
    def insert_video_data(self, video_data_list: List[Dict[str, Any]]) -> bool:
        """Insert multiple videos into database"""
        try:
            if not video_data_list:
                return True
            
            values = []
            for video in video_data_list:
                values.append((
                    video['video_id'],
                    self.channel_id,
                    video.get('title'),
                    video.get('description'),
                    video.get('thumbnail_image'),
                    video.get('transcript_path'),
                    video.get('duration_seconds', 0),
                    video.get('playlist_id'),
                    video.get('playlist_index'),  # Correct column name from schema
                ))

            execute_many("""
                INSERT INTO creator_base.videos
                (video_id, channel_id, title, video_description, thumbnail_image,
                 transcript_path, duration_seconds,
                 playlist_id, playlist_index)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    channel_id = VALUES(channel_id),
                    title = VALUES(title),
                    video_description = VALUES(video_description),
                    thumbnail_image = VALUES(thumbnail_image),
                    transcript_path = VALUES(transcript_path),
                    duration_seconds = VALUES(duration_seconds),
                    playlist_id = VALUES(playlist_id),
                    playlist_index = VALUES(playlist_index),
                    updated_at = NOW()
            """, values)
            
            secure_log(f"Inserted {len(values)} videos", 'info')
            return True
            
        except Exception as e:
            secure_log(f"Error inserting videos: {e}", 'error')
            return False
    
    
    def insert_playlist_data(self, playlist_data):
        """Insert playlist into database"""
        try:
            execute_query("""
                INSERT INTO creator_base.playlists
                (playlist_id, channel_id, playlist_title, playlist_description,
                 thumbnail_image, transcript_path, video_count, duration_seconds)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    playlist_title = VALUES(playlist_title),
                    playlist_description = VALUES(playlist_description),
                    thumbnail_image = VALUES(thumbnail_image),
                    transcript_path = VALUES(transcript_path),
                    video_count = VALUES(video_count),
                    duration_seconds = VALUES(duration_seconds),
                    updated_at = NOW()
            """, (
                playlist_data['playlist_id'],
                self.channel_id,
                playlist_data['title'],
                playlist_data.get('playlist_description'),
                playlist_data.get('thumbnail_image'),
                playlist_data.get('transcript_path'),
                playlist_data.get('video_count', 0),
                playlist_data.get('duration_seconds', 0),
            ), commit=True)
            
            secure_log(f"Inserted playlist {playlist_data['playlist_id']}", 'info')
            return True
            
        except Exception as e:
            secure_log(f"Error inserting playlist: {e}", 'error')
            return False
    
    
    def get_creator_info(self):
        """Get creator information"""
        try:
            result = execute_query("""
                SELECT creator_name, email, profile_photo_jpg
                FROM creator_base.creators
                WHERE channel_id = %s
            """, (self.channel_id,), fetch_one=True)
            
            return result
        except Exception as e:
            secure_log(f"Error getting creator info: {e}", 'error')
            return None
    
    
    def save_to_listed_exams(self, content_data, content_type='video'):
        """Save content to listed exams with all required fields"""
        try:
            from config import Config

            exam_number = self.generate_unique_exam_number(
                self.channel_id,
                playlist_id=content_data.get('playlist_id') if content_type == 'playlist' else None,
                video_id=content_data.get('video_id') if content_type == 'video' else None
            )

            # Get channel info (name and subscriber count) from creators table
            creator_info = execute_query("""
                SELECT channel_name, subscriber_count FROM creator_base.creators
                WHERE channel_id = %s
            """, (self.channel_id,), fetch_one=True)

            channel_name = creator_info['channel_name'] if creator_info else 'Unknown Creator'
            subscriber_count = creator_info['subscriber_count'] if creator_info else 0

            # Get default exam price from config
            exam_price = Config.DEFAULT_EXAM_PRICE

            execute_query("""
                INSERT INTO exam.listed_exams
                (unique_exam_number, channel_id, channel_name, number_of_subscribers,
                 exam_title, exam_description, exam_price,
                 video_id, playlist_id, thumbnail_image, transcript_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                 channel_name = VALUES(channel_name),
                 number_of_subscribers = VALUES(number_of_subscribers),
                 exam_title = VALUES(exam_title),
                 exam_description = VALUES(exam_description),
                 thumbnail_image = VALUES(thumbnail_image),
                 transcript_path = VALUES(transcript_path),
                 updated_at = NOW()
            """, (
                exam_number,
                self.channel_id,
                channel_name,
                subscriber_count,
                content_data.get('title', 'Untitled'),
                content_data.get('description', ''),
                exam_price,
                content_data.get('video_id'),
                content_data.get('playlist_id'),
                content_data.get('thumbnail_image'),
                content_data.get('transcript_path'),
            ), commit=True)

            return exam_number

        except Exception as e:
            secure_log(f"Error saving to listed exams: {e}", 'error')
            return None
    
    
    def save_exam_questions_to_db(self, unique_exam_number, questions):
        """
        TiDB Compatible: Saves questions directly via INSERT...ON DUPLICATE KEY UPDATE.
        Replaces the SaveExamQuestions stored procedure.

        Questions are stored as a single JSON blob in the questions_json column,
        NOT as individual rows with separate columns.
        """
        secure_log(f"Entering save_exam_questions_to_db for exam: {unique_exam_number}", 'info')
        if not unique_exam_number:
            return False

        try:
            # Validate question structure
            valid_questions = [q for q in (questions or []) if self._validate_question_structure(q)]
            questions_json = json.dumps(valid_questions, ensure_ascii=False) if valid_questions else "[]"

            # TiDB Compatible: Direct INSERT replaces SaveExamQuestions stored procedure
            execute_query("""
                INSERT INTO exam.exam_questions
                (unique_exam_number, questions_json)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE
                questions_json = %s,
                updated_at = NOW()
            """, (unique_exam_number, questions_json, questions_json), commit=True)

            secure_log(f"Saved {len(valid_questions)} questions for exam {unique_exam_number}", 'info')
            return True

        except Exception as error:
            secure_log(f"Database error saving questions: {str(error)}", 'error')
            return False
    
    
    def regenerate_questions_from_existing(
        self,
        content_type,
        content_id,
        title,
        transcript_path,
        exam_number=None
    ):
        """
        Regenerate questions from an existing transcript (15-day regeneration rule).

        This is called when content was previously processed and transcript exists.
        Uses existing transcript to generate new questions without calling YouTube API.

        NOTE: Summary generation removed. Questions now generated directly from transcript.

        Args:
            content_type: 'video' or 'playlist'
            content_id: video_id or playlist_id
            title: Content title for question generation
            transcript_path: Path to existing transcript file
            exam_number: Existing exam number (if any)

        Returns:
            dict: {
                'success': bool,
                'message': str,
                'question_count': int,
                'exam_number': str,
                'regenerated': True
            }
        """
        secure_log(
            f"Regenerating questions from existing {content_type} transcript",
            'info',
            video_id=content_id if content_type == 'video' else None,
            playlist_id=content_id if content_type == 'playlist' else None
        )

        try:
            # Load transcript content from GCS
            from youcert import download_file_content

            transcript_bytes = download_file_content(transcript_path)

            # Convert bytes to string if needed
            if isinstance(transcript_bytes, bytes):
                transcript_content = transcript_bytes.decode('utf-8')
            else:
                transcript_content = transcript_bytes

            if not transcript_content or len(transcript_content.strip()) < 100:
                secure_log(f"Transcript content too short or empty for regeneration", 'warning')
                return {
                    'success': False,
                    'message': 'Transcript content is too short for question generation'
                }

            # Generate or get exam number
            if not exam_number:
                if content_type == 'video':
                    exam_number = self.generate_unique_exam_number(
                        self.channel_id,
                        video_id=content_id
                    )
                else:
                    exam_number = self.generate_unique_exam_number(
                        self.channel_id,
                        playlist_id=content_id
                    )

            # Generate questions from transcript using existing summarize_captions_realtime
            # (which now only generates questions, not summary)
            questions = self.summarize_captions_realtime(
                transcript_content,
                title=title,
                video_id=content_id,
                duration_seconds=0  # Not needed for regeneration
            )
            
            if not questions:
                return {
                    'success': False,
                    'message': 'Failed to generate questions from transcript'
                }

            # Save questions to database
            questions_saved = self.save_exam_questions_to_db(exam_number, questions)

            # Queue chunk generation for compatibility (using transcript instead of summary)
            try:
                from youcert.logic.task_manager import queue_chunk_generation

                secure_log(
                    f"Queuing background chunk generation for regenerated {content_type}",
                    'info'
                )
                queue_chunk_generation(
                    content_id=content_id,
                    content_type=content_type,
                    channel_id=self.channel_id,
                    text_path=transcript_path
                )
            except Exception as task_err:
                secure_log(
                    f"Failed to queue chunking during regeneration (non-critical): {task_err}",
                    'warning'
                )

            return {
                'success': True,
                'message': f'Questions regenerated successfully! {len(questions)} questions generated.',
                'questions_generated': questions_saved,
                'question_count': len(questions),
                'exam_number': exam_number,
                'regenerated': True
            }
            
        except Exception as e:
            secure_log(f"Error regenerating questions: {e}", 'error')
            return {
                'success': False,
                'message': f'Failed to regenerate questions: {str(e)}'
            }
    
    
    def _generate_questions_from_summary(
        self,
        summary_text: str,
        title: str,
        num_questions: int = 50
    ) -> List[dict]:
        """
        Generate questions from pre-existing summary using REST API (for regeneration).
        
        Args:
            summary_text: Existing summary text
            title: Content title
            num_questions: Number of questions to generate
            
        Returns:
            List[dict]: Generated questions
        """
        try:
            secure_log(f"Generating {num_questions} questions from summary via REST API", 'info')
            
            # No-op: API keys never expire (replaces OAuth token refresh)
            self._ensure_token_fresh()

            # Calculate Bloom's taxonomy distribution
            bt1_count = int(num_questions * 0.25)
            bt2_count = int(num_questions * 0.25)
            bt3_count = int(num_questions * 0.20)
            bt4_count = int(num_questions * 0.15)
            bt5_count = int(num_questions * 0.10)
            bt6_count = num_questions - (bt1_count + bt2_count + bt3_count + bt4_count + bt5_count)

            tech_count = int(num_questions * 0.30)
            conceptual_count = num_questions - tech_count

            # Create prompt for question generation only
            prompt = f"""SYSTEM: You are an expert exam designer.

TASK: Generate EXACTLY {num_questions} MCQs based on the summary below.

CRITICAL INSTRUCTION: Generate EXACTLY {num_questions} questions. Do NOT generate {num_questions + 1}.

COGNITIVE DISTRIBUTION (Bloom's Taxonomy):
BT1 (Remember) = {bt1_count} questions
BT2 (Understand) = {bt2_count} questions
BT3 (Apply) = {bt3_count} questions
BT4 (Analyze) = {bt4_count} questions
BT5 (Evaluate) = {bt5_count} questions
BT6 (Create) = {bt6_count} questions

TECHNICAL vs CONCEPTUAL:
If technical content: ~{tech_count} technical questions
Remaining {conceptual_count} conceptual questions
If not technical: all {num_questions} conceptual questions

QUESTION QUALITY REQUIREMENTS:
- Stanford university level difficulty
- Each question tests a DIFFERENT concept
- Include reasoning-based variations
- No question numbering, no meta wording
- No phrases like "according to the summary"

ANSWER FORMAT RULES:
- Exactly 4 options labeled A, B, C, D
- Only ONE correct answer
- Realistic distractors
- Concise explanation

OUTPUT FORMAT (JSON array):
[
  {{
    "question": "Question text?",
    "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
    "correct_answer": "A",
    "explanation": "Why this is correct"
  }}
]

TITLE: {title}

SUMMARY:
{summary_text}

Generate exactly {num_questions} questions in JSON format."""

            # Create schema for questions only
            schema = {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "options": {
                            "type": "object",
                            "properties": {
                                "A": {"type": "string"},
                                "B": {"type": "string"},
                                "C": {"type": "string"},
                                "D": {"type": "string"}
                            },
                            "required": ["A", "B", "C", "D"]
                        },
                        "correct_answer": {"type": "string", "enum": ["A", "B", "C", "D"]},
                        "explanation": {"type": "string"}
                    },
                    "required": ["question", "options", "correct_answer", "explanation"]
                }
            }

            # Build Gemini REST API request
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.4,
                    "maxOutputTokens": MAX_OUTPUT_TOKENS,
                    "responseMimeType": "application/json",
                    "responseSchema": schema
                }
            }

            # SECURITY: API key sent via header, NOT as a URL query param.
            headers = {
                "x-goog-api-key": self.gemini_api_key,
                "Content-Type": "application/json"
            }

            # ── Gemini REST call with 429 exponential-backoff retry ──────────
            MAX_GEMINI_RETRIES = 5
            BASE_BACKOFF_SECONDS = 15
            response = None

            for attempt in range(1, MAX_GEMINI_RETRIES + 1):
                try:
                    response = requests.post(
                        self.vertex_ai_endpoint,
                        headers=headers,
                        json=payload,
                        timeout=3600
                    )
                except requests.exceptions.Timeout:
                    secure_log(f"Gemini timeout on summary-questions (attempt {attempt}/{MAX_GEMINI_RETRIES})", 'error')
                    return []
                except requests.exceptions.RequestException as e:
                    secure_log(f"Gemini network error on summary-questions: {e}", 'error')
                    return []

                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 0))
                    wait_seconds = retry_after if retry_after > 0 else BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                    if attempt < MAX_GEMINI_RETRIES:
                        secure_log(
                            f"Gemini 429 on summary-questions. "
                            f"Retrying in {wait_seconds}s (attempt {attempt}/{MAX_GEMINI_RETRIES})", 'warning'
                        )
                        import time as _time
                        _time.sleep(wait_seconds)
                        continue
                    else:
                        secure_log(f"Gemini 429 persisted after {MAX_GEMINI_RETRIES} retries on summary-questions.", 'error')
                        return []

                try:
                    response.raise_for_status()
                except requests.exceptions.HTTPError as http_err:
                    secure_log(f"Gemini HTTP error {response.status_code} on summary-questions: {http_err}", 'error')
                    return []

                break  # success

            result = response.json()

            # Extract generated text
            if 'candidates' in result and len(result['candidates']) > 0:
                candidate = result['candidates'][0]
                if 'content' in candidate and 'parts' in candidate['content']:
                    generated_text = candidate['content']['parts'][0].get('text', '')
                else:
                    return []
            else:
                return []

            # Parse JSON
            try:
                questions = json.loads(generated_text)
            except json.JSONDecodeError:
                # Try to repair JSON
                repaired = self._repair_json_output(generated_text, "regeneration_questions")
                questions = json.loads(repaired)

            # Validate questions
            valid_questions = [
                q for q in questions
                if self._validate_question_structure(q)
            ]

            # Ensure exact count
            if len(valid_questions) > num_questions:
                valid_questions = valid_questions[:num_questions]

            secure_log(f"Generated {len(valid_questions)} valid questions from summary", 'info')

            return valid_questions

        except Exception as e:
            secure_log(f"Error generating questions from summary: {e}", 'error')
            return []
    
    
    # ========================================================================
    # ANALYTICS & MONITORING (All functions preserved)
    # ========================================================================
    
    def get_listed_exams(self, limit=10):
        """Get listed exams for creator"""
        try:
            results = execute_query("""
                SELECT unique_exam_number, exam_title, exam_price,
                       video_id, playlist_id, is_active, created_at, thumbnail_image,
                       exam_description, summary_path
                FROM exam.listed_exams
                WHERE channel_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (self.channel_id, limit), fetch_all=True)
            
            exams = []
            for result in results or []:
                thumbnail_rel_path = result.get('thumbnail_image')
                thumbnail_url = get_file_url(thumbnail_rel_path)
                
                exam = {
                    'unique_exam_number': result['unique_exam_number'],
                    'exam_title': result.get('exam_title', 'Untitled Exam'),
                    'exam_price': float(result['exam_price']) if result.get('exam_price') else 0.00,
                    'video_id': result.get('video_id'),
                    'playlist_id': result.get('playlist_id'),
                    'is_active': bool(result.get('is_active', False)),
                    'created_at': result.get('created_at'),
                    'thumbnail_image': thumbnail_rel_path,
                    'thumbnail_url': thumbnail_url,
                    'exam_description': result.get('exam_description', ''),
                    'content_type': 'Playlist' if result.get('playlist_id') else 'Video',
                    'has_content': bool(result.get('video_id') or result.get('playlist_id')),
                    'has_thumbnail': bool(thumbnail_rel_path)
                }
                exams.append(exam)
            
            return exams
        except Exception as e:
            secure_log(f"Error getting listed exams: {e}", 'error')
            return []
    
    
    def get_processing_statistics(self):
        """Get processing statistics (summary stats removed)"""
        default_stats = {
            'videos': {'total_count': 0, 'total_duration': 0, 'with_transcripts': 0},
            'playlists': {'total_count': 0, 'total_duration': 0},
            'exams': {'total_count': 0, 'active_count': 0}
        }

        try:
            video_stats = execute_query("""
                SELECT COUNT(*) as video_count,
                       COALESCE(SUM(duration_seconds), 0) as total_duration,
                       COUNT(CASE WHEN transcript_path IS NOT NULL AND transcript_path != '' THEN 1 END) as videos_with_transcripts
                FROM creator_base.videos
                WHERE channel_id = %s
            """, (self.channel_id,), fetch_one=True) or {}

            playlist_stats = execute_query("""
                SELECT COUNT(*) as playlist_count,
                       COALESCE(SUM(duration_seconds), 0) as total_duration
                FROM creator_base.playlists
                WHERE channel_id = %s
            """, (self.channel_id,), fetch_one=True) or {}

            exam_stats = execute_query("""
                SELECT COUNT(*) as total_exams,
                       SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active_exams
                FROM exam.listed_exams
                WHERE channel_id = %s
            """, (self.channel_id,), fetch_one=True) or {}

            return {
                'videos': {
                    'total_count': video_stats.get('video_count', 0),
                    'total_duration': video_stats.get('total_duration', 0),
                    'with_transcripts': video_stats.get('videos_with_transcripts', 0)
                },
                'playlists': {
                    'total_count': playlist_stats.get('playlist_count', 0),
                    'total_duration': playlist_stats.get('total_duration', 0)
                },
                'exams': {
                    'total_count': exam_stats.get('total_exams', 0),
                    'active_count': exam_stats.get('active_exams', 0)
                }
            }
        except Exception as e:
            secure_log(f"Error getting statistics: {e}", 'error')
            return default_stats
    
    
    def cleanup_temp_files(self):
        """Clean up old temporary files"""
        try:
            secure_log("Temp file cleanup initiated", 'info')
            # GCS cleanup configured via bucket lifecycle rules
        except Exception as e:
            secure_log(f"Cleanup error: {e}", 'warning')
    
    
    @retry_with_backoff()
    def validate_youtube_api_quota(self):
        """Validate YouTube API quota"""
        try:
            test_request = self.youtube_service.channels().list(
                part='id',
                id=self.channel_id
            )
            test_response = test_request.execute()
            
            return test_response is not None
            
        except HttpError as e:
            if e.resp.status == 403 and ('quota' in str(e).lower() or 'exceeded' in str(e).lower()):
                secure_log("YouTube API quota exceeded", 'error')
                return False
            raise
        except Exception as e:
            secure_log(f"Quota check failed: {e}", 'error')
            return False
    
    
    def get_system_health_status(self):
        """Get system health status"""
        health_status = {
            'timestamp': datetime.now().isoformat(),
            'youtube_api': 'unknown',
            'gemini_ai': 'ok',
            'database': 'unknown',
            'storage': 'ok',
        }
        
        try:
            health_status['youtube_api'] = 'ok' if self.validate_youtube_api_quota() else 'error'
            
            try:
                execute_query("SELECT 1")
                health_status['database'] = 'ok'
            except Exception:
                health_status['database'] = 'error'
            
            return health_status
            
        except Exception as e:
            secure_log(f"Health check error: {e}", 'error')
            return {**health_status, 'error': str(e)}


# ============================================================================
# MODULE EXPORTS
# ============================================================================

__all__ = [
    'YouTubeProcessor',
    'YouTubeTokenExpiredError',
    'TranscriptChunker',
]

