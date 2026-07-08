import hashlib
# CREATOR_ROUTES.PY - UPGRADED v14.0 DATABASE OTP - ALIGNED WITH CENTRALIZED __init__.py
# =======================================================================================
# Features:
# - Uses centralized save_file/get_file_url/download_file_content from __init__.py
# - Uses centralized STORAGE_PATHS configuration
# - Uses get_google_client_config() for OAuth (no client_secret.json needed)
# - Centralized logging via secure_log
# - Centralized database operations via get_db_connection/execute_query
# - Cloudflare Containers / R2 / Queues compatible
# =======================================================================================

from flask import Blueprint, render_template, session, url_for, redirect, request, flash, current_app, jsonify, g, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

# CENTRALIZED IMPORTS from __init__.py
from youcert import (
    limiter, cache,
    get_session_fingerprint, validate_session_security,
    secure_log, get_db_connection, execute_query, execute_many,
    save_file, get_file_url, download_file_content,
    get_google_client_config, delete_file,
    # Encryption Utilities
    encrypt_token, decrypt_token,
    # Database Token Management (v15.0 - Replaces file-based OTP storage)
    save_otp_to_database,
    verify_otp_from_database,
    save_password_reset_token_db,
    get_password_reset_token_db,
    validate_password_reset_token_db,
    delete_password_reset_token_db,
    cleanup_expired_tokens_db,
    # Session Management
    clear_creator_session
)

from youcert.logic import CreatorEarningsCalculator
from youcert.logic import queue_video_processing
from youcert.logic import YouTubeProcessor, YouTubeTokenExpiredError
from youcert.logic.email_service import email_service, send_otp_email, verify_otp_email, send_password_reset_email

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from config import Config

# Additional imports
import random, time, os, json, mimetypes, io, re
from datetime import datetime
from functools import wraps
from PIL import Image


creator_bp = Blueprint("creator", __name__)


# ============================================================================
# ENVIRONMENT DETECTION
# ============================================================================

def is_cloud_environment():
    """Detect if running in Cloudflare Containers (production)"""
    from config import Config
    return Config.IS_CLOUDFLARE or not current_app.debug


def is_debug_mode():
    """Check if running in debug/development mode"""
    return current_app.debug


# ============================================================================
# YOUTUBE OAUTH CONFIGURATION
# ============================================================================

YOUTUBE_SCOPES = [
    'https://www.googleapis.com/auth/youtube.readonly',
    'https://www.googleapis.com/auth/youtube.force-ssl',
    'openid',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/userinfo.email'
]

# NOTE: OAuth client config is now centralized via get_google_client_config() from __init__.py
# No client_secret.json file needed - config comes from environment variables


# ============================================================================
# FILE UPLOAD CONFIGURATIONS
# ============================================================================

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MAX_FILE_SIZE = 8 * 1024 * 1024  # 8MB limit
VALID_IMAGE_MIMES = {'image/jpeg', 'image/png', 'image/gif'}
MAX_IMAGE_DIMENSION = 4096  # Maximum 4096x4096 pixels (prevents memory exhaustion)

ALLOWED_DOC_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}
MAX_DOC_SIZE = 5 * 1024 * 1024  # 5MB limit

# NOTE: Storage paths are now centralized in __init__.py via STORAGE_PATHS
# Available keys: 'signatures', 'profiles', 'transcripts', 'summaries', 
#                 'documents', 'thumbnails', 'bank_documents', 'uploads'



# ============================================================================
# HELPER FUNCTIONS - INPUT VALIDATION
# ============================================================================

def validate_youtube_id(video_id):
    """Validate YouTube video ID format: 11 alphanumeric characters"""
    if not video_id:
        return False
    pattern = r'^[A-Za-z0-9_-]{11}$'
    return bool(re.match(pattern, str(video_id)))


def validate_channel_id(channel_id):
    """Validate YouTube channel ID format: UC + 21-24 alphanumeric"""
    if not channel_id:
        return False
    pattern = r'^UC[a-zA-Z0-9_-]{21}[AQwQ]?$'
    return bool(re.match(pattern, str(channel_id)))


def validate_playlist_id(playlist_id):
    """Validate YouTube playlist ID format"""
    if not playlist_id:
        return False
    pattern = r'^(PL|RD|UU|LL|OL)[A-Za-z0-9_-]{16,}$'
    return bool(re.match(pattern, str(playlist_id)))


def sanitize_error_message(error):
    """Convert technical errors to user-friendly messages"""
    error_str = str(error).lower()
    if 'database' in error_str or 'mysql' in error_str:
        return "Database operation failed. Please try again."
    elif 'permission' in error_str:
        return "You don't have permission for this action."
    elif 'timeout' in error_str:
        return "Connection timeout. Please check your internet and try again."
    elif 'not found' in error_str:
        return "The requested resource was not found."
    else:
        return "An unexpected error occurred. Please try again."


# ============================================================================
# HELPER FUNCTIONS - FILE OPERATIONS (CLOUD/LOCAL AWARE)
# ============================================================================

def allowed_file(filename):
    """Check if image file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def allowed_document_file(filename):
    """Check if document file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_DOC_EXTENSIONS


# ============================================================================
# FILE OPERATION HELPERS (Using centralized functions from __init__.py)
# ============================================================================

# NOTE: save_file, get_file_url, download_file_content are imported from __init__.py
# These functions automatically handle local vs cloud storage

def delete_file(file_path):
    """
    Delete file from appropriate storage.
    
    Args:
        file_path (str): Path to the file
        
    Returns:
        bool: True if deleted, False otherwise
    """
    try:
        if current_app.debug:
            # Local development
            # Try multiple possible paths
            possible_paths = [
                os.path.abspath(file_path),
                os.path.join('youcert', file_path) if not file_path.startswith('youcert') else file_path,
            ]
            for abs_path in possible_paths:
                if os.path.exists(abs_path):
                    os.remove(abs_path)
                    secure_log(f"File deleted: {abs_path}", 'info')
                    return True
        else:
            # Production - delete from R2
            try:
                from youcert import get_r2_client
                
                bucket_name = Config.R2_BUCKET_NAME
                if bucket_name:
                    r2_client = get_r2_client()
                    if not r2_client:
                        secure_log("R2 client not available", 'warning')
                        return False
                    r2_client.delete_object(Bucket=bucket_name, Key=file_path)
                    secure_log(f"File deleted from R2: {file_path}", 'info')
                    return True
            except Exception as e:
                secure_log(f"R2 delete error: {str(e)}", 'warning')
                
        return False
        
    except Exception as e:
        secure_log(f"Error deleting file: {str(e)}", 'error')
        return False


def get_relative_path(abs_path):
    """Convert absolute path to relative path for DB storage"""
    try:
        return os.path.relpath(abs_path, os.getcwd())
    except ValueError:
        return abs_path


def _clean_static_path(path):
    """
    Helper to sanitize database paths.
    Converts 'static\\thumbnails\\img.jpg' -> 'thumbnails/img.jpg'
    """
    if not path:
        return None
    
    # 1. Normalize Windows backslashes to forward slashes
    clean = path.replace('\\', '/')
    
    # 2. Remove 'static/' prefixes if present
    for prefix in ['static/', '/static/', 'youcert/static/']:
        if clean.startswith(prefix):
            clean = clean[len(prefix):]
            
    # 3. Strip leading slash
    return clean.lstrip('/')


def is_valid_image(file):
    """Enhanced file validation with MIME type, size, and magic bytes checks"""
    if not file or not file.filename:
        return False
    
    # Check file size
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    
    if size > MAX_FILE_SIZE:
        secure_log(f"Image validation failed: File size {size} exceeds limit", 'warning')
        return False
    
    # Check MIME type from filename
    mime_type = mimetypes.guess_type(file.filename)[0]
    if mime_type not in VALID_IMAGE_MIMES:
        secure_log(f"Image validation failed: Invalid MIME type {mime_type}", 'warning')
        return False
    
    # Check magic bytes and image integrity using PIL
    try:
        file.seek(0)
        img = Image.open(file)
        img.verify()

        if img.format.lower() not in ['jpeg', 'png', 'gif']:
            secure_log(f"Image validation failed: Mismatch format {img.format}", 'warning')
            return False

        file.seek(0)

        # Re-open to ensure it's not corrupted and check dimensions
        img = Image.open(file)
        img.load()

        # Check image dimensions (prevent memory exhaustion attacks)
        width, height = img.size
        if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
            secure_log(f"Image validation failed: Dimensions {width}x{height} exceed limit {MAX_IMAGE_DIMENSION}", 'warning')
            return False

        file.seek(0)

        return allowed_file(file.filename)
    except Exception as e:
        secure_log(f"Image validation failed with PIL: {str(e)}", 'warning')
        return False


def save_encrypted_bank_document(file, channel_id, doc_type):
    """
    Save bank document with encryption using centralized save_file.
    
    Args:
        file: File object to save
        channel_id (str): Channel ID for directory structure
        doc_type (str): Document type identifier
        
    Returns:
        tuple: (file_path, original_extension) or (None, None) on failure
    """
    if not file or not file.filename:
        return None, None
    
    if not allowed_document_file(file.filename):
        secure_log(f"Invalid file extension: {file.filename}", 'warning')
        return None, None
    
    # Get original extension
    original_ext = file.filename.rsplit('.', 1)[1].lower()
    
    # Check file size
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    
    if size > MAX_DOC_SIZE:
        secure_log(f"File too large: {size} bytes", 'warning')
        return None, None
    
    # Create secure filename with channel subdirectory
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{channel_id}/{doc_type}_{timestamp}.enc"
    filename = secure_filename(filename.replace('/', '_'))  # Make safe for all platforms
    filename = f"{channel_id}/{filename}"  # Re-add subdirectory structure
    
    try:
        # Use centralized save_file with encryption
        saved_path = save_file(file, 'bank_documents', filename, encrypt=True)
        
        if saved_path:
            secure_log(f"Encrypted document saved: {doc_type}", 'info', channel_id=channel_id)
            return saved_path, original_ext
        else:
            secure_log(f"Failed to save encrypted document: {doc_type}", 'error', channel_id=channel_id)
            return None, None
            
    except Exception as e:
        secure_log(f"Error saving encrypted document: {str(e)}", 'error', channel_id=channel_id)
        return None, None


# ============================================================================
# HELPER FUNCTIONS - SESSION & PASSWORD RESET
# ============================================================================

def secure_login_user(channel_id, creator_name, email):
    """Secure login with session regeneration and fingerprinting"""
    clear_creator_session()  # Prevent session fixation

    session['channel_id'] = channel_id
    session['creator_name'] = creator_name
    session['email'] = email
    session.permanent = True

    session['fingerprint'] = get_session_fingerprint()
    session['last_activity'] = datetime.now().isoformat()

    from flask_wtf.csrf import generate_csrf
    generate_csrf()


# ============================================================================
# HELPER FUNCTIONS - OAUTH
# ============================================================================

def validate_oauth_scopes(credentials):
    """Validate that OAuth token has required scopes"""
    if not credentials or not hasattr(credentials, 'scopes'):
        return False

    required_scopes = set(YOUTUBE_SCOPES)
    granted_scopes = set(credentials.scopes) if credentials.scopes else set()

    missing_scopes = required_scopes - granted_scopes
    if missing_scopes:
        secure_log(f"Missing OAuth scopes: {missing_scopes}", 'warning')
        return False
    return True


def check_certificate_expiry(credentials):
    """Check if certificate is about to expire (within 5 minutes)"""
    if not credentials or not hasattr(credentials, 'expiry'):
        return False

    if not credentials.expiry:
        return False

    now = datetime.now(credentials.expiry.tzinfo) if credentials.expiry.tzinfo else datetime.now()
    time_until_expiry = credentials.expiry - now

    return time_until_expiry.total_seconds() < 300


# ============================================================================
# DECORATORS
# ============================================================================

def per_creator_rate_limit(max_calls=50, time_window=3600):
    """Per-creator rate limiting for YouTube API calls"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            channel_id = session.get('channel_id')
            if not channel_id:
                return func(*args, **kwargs)

            cache_key = f"creator_{channel_id}_api_calls"
            call_count = cache.get(cache_key) or 0

            if call_count >= max_calls:
                secure_log(f"API rate limit exceeded for creator {channel_id}", 'warning')
                flash(f"You've reached the API limit ({max_calls} calls per hour). Please try again later.", 'error')
                return jsonify({'success': False, 'message': 'Rate limit exceeded'}), 429

            cache.set(cache_key, call_count + 1, timeout=time_window)
            return func(*args, **kwargs)
        return wrapper
    return decorator


class CircuitBreakerOpen(Exception):
    pass


def circuit_breaker(max_failures=5, reset_timeout=60):
    """Circuit breaker for external API resilience"""
    def decorator(func):
        state = {'failures': 0, 'last_failure_time': None, 'open': False}

        @wraps(func)
        def wrapper(*args, **kwargs):
            if state['last_failure_time']:
                if time.time() - state['last_failure_time'] > reset_timeout:
                    state['failures'] = 0
                    state['open'] = False

            if state['open']:
                raise CircuitBreakerOpen(f"Circuit breaker open. Retry in {reset_timeout}s")

            try:
                result = func(*args, **kwargs)
                state['failures'] = 0
                return result
            except Exception as e:
                state['failures'] += 1
                state['last_failure_time'] = time.time()
                if state['failures'] >= max_failures:
                    state['open'] = True
                raise

        return wrapper
    return decorator


def retry_with_backoff(max_retries=3, base_delay=1, max_delay=10):
    """
    Decorator to retry functions with exponential backoff.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            last_exception = None
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    error_str = str(e).lower()
                    last_exception = e

                    permanent_errors = [
                        'invalid_grant', 'invalid_client', 'unauthorized_client',
                        'access_denied', 'invalid_scope', 'unsupported_grant_type'
                    ]

                    if any(err in error_str for err in permanent_errors):
                        secure_log(f"Permanent error: {str(e)[:100]}", 'error')
                        raise

                    retries += 1
                    if retries >= max_retries:
                        secure_log(f"Max retries reached for {func.__name__}", 'error')
                        raise

                    delay = min(base_delay * (2 ** (retries - 1)), max_delay)
                    jitter = random.uniform(0, delay * 0.1)
                    sleep_time = delay + jitter

                    secure_log(f"Transient error. Retry {retries}/{max_retries} after {sleep_time:.2f}s", 'warning')
                    time.sleep(sleep_time)

            if last_exception:
                raise last_exception
        return wrapper
    return decorator


# ============================================================================
# CORE APPLICATION LOGIC - TOKEN VALIDATION
# ============================================================================

def validate_and_refresh_tokens(channel_id):
    """
    Production-grade token validation with comprehensive error handling.
    Uses centralized database operations and encryption.
    """
    try:
        creator_creds = execute_query("""
            SELECT oauth_token, refresh_token, client_id, client_secret, 
                   token_uri, token_expiry
            FROM creator_base.creators
            WHERE channel_id = %s
        """, (channel_id,), fetch_one=True)

        if not creator_creds:
            return {'valid': False, 'refreshed': False, 'error': 'no_credentials', 'error_detail': 'No credentials found'}

        if not creator_creds['oauth_token']:
            return {'valid': False, 'refreshed': False, 'error': 'no_token', 'error_detail': 'No OAuth token stored'}

        # DECRYPTION: Use centralized decrypt_token
        oauth_token = decrypt_token(creator_creds['oauth_token'])
        refresh_token = decrypt_token(creator_creds['refresh_token']) if creator_creds['refresh_token'] else None
        client_id = decrypt_token(creator_creds['client_id']) if creator_creds['client_id'] else None
        client_secret = decrypt_token(creator_creds['client_secret']) if creator_creds['client_secret'] else None
        token_uri = decrypt_token(creator_creds['token_uri']) if creator_creds['token_uri'] else 'https://oauth2.googleapis.com/token'

        # Critical Check
        if not oauth_token:
            secure_log(f"Token decryption failed (returned None)", 'error', channel_id=channel_id)
            return {'valid': False, 'refreshed': False, 'error': 'decryption_failed', 'error_detail': 'Critical: Token decryption failed'}

        if not refresh_token:
            return {'valid': False, 'refreshed': False, 'error': 'no_refresh_token', 'error_detail': 'No refresh token available'}

        credentials = Credentials(
            token=oauth_token,
            refresh_token=refresh_token,
            token_uri=token_uri,
            client_id=client_id,
            client_secret=client_secret,
            scopes=YOUTUBE_SCOPES
        )

        if credentials.valid:
            return {'valid': True, 'refreshed': False, 'error': None, 'error_detail': None}

        # Token expired - attempt refresh
        if credentials.expired and credentials.refresh_token:
            # Use DATABASE ADVISORY LOCK (works across all Cloud Run instances)
            lock_key = f"oauth_refresh_{channel_id}"

            # Try to acquire database lock (wait up to 5 seconds)
            try:
                lock_result = execute_query(
                    "SELECT GET_LOCK(%s, 5) as acquired",
                    (lock_key,),
                    fetch_one=True
                )

                if not lock_result or lock_result.get('acquired') != 1:
                    # Another process is refreshing the token
                    secure_log(f"Lock not acquired - another process is refreshing token", 'info', channel_id=channel_id)
                    return {'valid': False, 'refreshed': False, 'error': 'refresh_in_progress', 'error_detail': 'Refresh in progress'}

                secure_log(f"Advisory lock acquired for token refresh", 'info', channel_id=channel_id)

                try:
                    # Check if token was refreshed while we waited for lock
                    latest_creds = execute_query(
                        "SELECT token_expiry FROM creator_base.creators WHERE channel_id = %s",
                        (channel_id,),
                        fetch_one=True
                    )

                    if latest_creds and latest_creds['token_expiry']:
                        try:
                            expiry_ts = latest_creds['token_expiry']
                            if isinstance(expiry_ts, str):
                                expiry_ts = datetime.strptime(expiry_ts, '%Y-%m-%d %H:%M:%S')
                            if expiry_ts > datetime.now():
                                secure_log(f"Token already refreshed by another process", 'info', channel_id=channel_id)
                                return {'valid': True, 'refreshed': True, 'error': None, 'error_detail': None}
                        except:
                            pass

                    # Actually refresh the token
                    @retry_with_backoff(max_retries=3)
                    def perform_refresh():
                        request_obj = Request()
                        credentials.refresh(request_obj)
                        return credentials

                    try:
                        refreshed_creds = perform_refresh()

                        # ENCRYPTION: Encrypt new token before saving
                        encrypted_token = encrypt_token(refreshed_creds.token)

                        execute_query("""
                            UPDATE creator_base.creators
                            SET oauth_token = %s, token_expiry = %s, updated_at = NOW()
                            WHERE channel_id = %s
                        """, (encrypted_token, refreshed_creds.expiry, channel_id), commit=True)

                        secure_log(f"Token refreshed successfully", 'info', channel_id=channel_id)
                        return {'valid': True, 'refreshed': True, 'error': None, 'error_detail': None}

                    except Exception as refresh_error:
                        secure_log(f"Token refresh failed: {str(refresh_error)}", 'error', channel_id=channel_id)
                        return {'valid': False, 'refreshed': False, 'error': 'refresh_failed', 'error_detail': str(refresh_error)}

                finally:
                    # ALWAYS release the advisory lock
                    execute_query("SELECT RELEASE_LOCK(%s)", (lock_key,))
                    secure_log(f"Advisory lock released", 'info', channel_id=channel_id)

            except Exception as lock_error:
                secure_log(f"Advisory lock error: {str(lock_error)}", 'error', channel_id=channel_id)
                return {'valid': False, 'refreshed': False, 'error': 'lock_error', 'error_detail': str(lock_error)}

        return {'valid': False, 'refreshed': False, 'error': 'invalid_token', 'error_detail': 'Token invalid'}

    except Exception as e:
        secure_log(f"Validation error: {str(e)}", 'error', channel_id=channel_id)
        return {'valid': False, 'refreshed': False, 'error': 'validation_error', 'error_detail': str(e)}


def check_youtube_authentication(channel_id):
    """Quick check if YouTube authentication is valid for a channel."""
    result = validate_and_refresh_tokens(channel_id)
    return result['valid']


# ============================================================================
# ROUTE DECORATORS
# ============================================================================

def login_required(f):
    """
    Decorator to require login.
    Uses centralized database operations.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        channel_id_in_session = session.get('channel_id')
        if not channel_id_in_session:
            flash('Please log in first.', 'warning')
            return redirect(url_for('creator.creator_login'))

        # CRITICAL FIX: Validate session security and clear session on failure
        try:
            if not validate_session_security():
                # Explicitly clear the session to stop the redirect loop
                clear_creator_session()
                flash('Session invalid or expired due to inactivity. Please log in again.', 'warning')
                return redirect(url_for('creator.creator_login'))
        except Exception as se:
            secure_log(f"Error during session validation: {str(se)}", 'error', channel_id=channel_id_in_session)
            clear_creator_session()
            flash('Session validation error. Please log in again.', 'warning')
            return redirect(url_for('creator.creator_login'))

        # Check database for active status using centralized operation
        try:
            creator = execute_query("""
                SELECT channel_id, creator_name, email, is_active
                FROM creator_base.creators
                WHERE channel_id = %s
            """, (channel_id_in_session,), fetch_one=True)

            if not creator or not creator['is_active']:
                clear_creator_session()
                flash('Session expired or your account has been deactivated.', 'error')
                return redirect(url_for('creator.creator_login'))

            # Store creator info in g for access within the request context
            g.channel_id = creator['channel_id']
            g.creator_name = creator['creator_name']
            g.creator_email = creator['email']

        except Exception as e:
            secure_log(f"Error during creator session validation: {str(e)}", 'error', channel_id=channel_id_in_session)
            clear_creator_session()
            flash('An unexpected error occurred. Please try logging in again.', 'error')
            return redirect(url_for('creator.creator_login'))

        return f(*args, **kwargs)
    return decorated_function


def get_youtube_service(channel_id=None, oauth_token=None):
    """
    Create YouTube service with automatic token validation and refresh.
    Uses centralized database operations.
    """
    try:
        if not channel_id:
            channel_id = session.get('channel_id')
        
        if not channel_id:
            return None

        creator_creds = execute_query("""
            SELECT oauth_token, refresh_token, client_id, client_secret,
                   token_uri, token_expiry
            FROM creator_base.creators
            WHERE channel_id = %s
        """, (channel_id,), fetch_one=True)

        if not creator_creds or not creator_creds['oauth_token']:
            flash("YouTube authentication required.", "warning")
            return None

        # DECRYPTION
        oauth_token = decrypt_token(creator_creds['oauth_token'])
        refresh_token = decrypt_token(creator_creds['refresh_token']) if creator_creds['refresh_token'] else None
        
        # Check for decryption failure
        if not oauth_token:
            secure_log(f"Decryption failed for YouTube service", 'error', channel_id=channel_id)
            flash("Authentication error. Please reconnect your channel.", "error")
            return None

        if not refresh_token:
            flash("YouTube authentication incomplete.", "warning")
            return None

        credentials = Credentials(
            token=oauth_token,
            refresh_token=refresh_token,
            token_uri=decrypt_token(creator_creds['token_uri']) if creator_creds['token_uri'] else 'https://oauth2.googleapis.com/token',
            client_id=decrypt_token(creator_creds['client_id']) if creator_creds['client_id'] else None,
            client_secret=decrypt_token(creator_creds['client_secret']) if creator_creds['client_secret'] else None,
            scopes=YOUTUBE_SCOPES
        )

        if credentials.expired and credentials.refresh_token:
            try:
                request_obj = Request()
                credentials.refresh(request_obj)
                
                # ENCRYPTION
                encrypted_token = encrypt_token(credentials.token)
                
                if encrypted_token:
                    execute_query("""
                        UPDATE creator_base.creators
                        SET oauth_token = %s, token_expiry = %s, updated_at = NOW()
                        WHERE channel_id = %s
                    """, (encrypted_token, credentials.expiry, channel_id), commit=True)
            except Exception as e:
                secure_log(f"Service refresh failed: {str(e)}", 'error', channel_id=channel_id)
                return None

        return build('youtube', 'v3', credentials=credentials)

    except Exception as e:
        secure_log(f"Error creating YouTube service: {str(e)}", 'error', channel_id=channel_id)
        return None


def requires_youtube_auth(f):
    """
    Enhanced decorator that ensures valid YouTube authentication.
    Works for both regular requests and AJAX/API calls.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'channel_id' not in session:
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    'success': False,
                    'message': 'Please log in first.',
                    'redirect': url_for('creator.creator_login')
                }), 401
            else:
                flash("Please log in first.", "warning")
                return redirect(url_for('creator.creator_login'))
        
        youtube_service = get_youtube_service()
        
        if not youtube_service:
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    'success': False,
                    'message': 'YouTube authentication expired or revoked. Please reconnect your channel.',
                    'redirect': url_for('creator.reconnect_youtube')
                }), 401
            else:
                return redirect(url_for('creator.reconnect_youtube'))
        
        return f(youtube_service=youtube_service, *args, **kwargs)
    
    return decorated_function


# ============================================================================
# CACHING
# ============================================================================




# ============================================================================
# CREATOR SIGNUP ROUTES
# ============================================================================

@creator_bp.route("/creator/signup/", methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def creator_signup():
    # CRITICAL FIX: Validate session before redirecting to prevent loop
    if 'channel_id' in session:
        if validate_session_security():
            return redirect(url_for('creator.creator_index'))
        else:
            clear_creator_session()
    
    if request.method == 'POST':
        creator_name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if not creator_name or not email or not password:
            flash("All signup fields are required.", "error")
            return render_template("creator_signup.html", name=creator_name, email=email)
        
        if len(password) < 8:
            flash("Password must be at least 8 characters long.", "error")
            return render_template("creator_signup.html", name=creator_name, email=email)
        
        try:
            # Check if email exists using centralized operation
            existing = execute_query(
                "SELECT email FROM creator_base.creators WHERE email = %s",
                (email,), fetch_one=True
            )
            
            if existing:
                flash("An account with this email already exists.", "error")
                return render_template("creator_signup.html", name=creator_name, email=email)
            
            hashed_password = generate_password_hash(password, method='pbkdf2:sha256:260000')
            
            session['temp_signup'] = {
                'creator_name': creator_name,
                'email': email,
                'password_hash': hashed_password
            }
            
            otp_code = send_otp_email(email, user_type='creator', to_name=creator_name, purpose='registration')
            
            if not otp_code:
                flash("Failed to send verification code. Please try again.", "error")
                return render_template("creator_signup.html", name=creator_name, email=email)
            
            flash("Verification code sent! Please verify your email.", "success")
            return redirect(url_for('creator.verify_otp'))
        
        except Exception as e:
            secure_log(f"Error during creator signup: {str(e)}", 'error')
            flash("Unexpected error. Please try again.", "error")
            return render_template("creator_signup.html", name=creator_name, email=email)
    
    return render_template("creator_signup.html")


@creator_bp.route("/creator/verify_otp/", methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def verify_otp():
    if 'temp_signup' not in session:
        flash("Please complete signup process.", "error")
        return redirect(url_for('creator.creator_signup'))
    
    email = session['temp_signup']['email']
    creator_name = session['temp_signup']['creator_name']
    
    if request.method == 'POST':
        entered_otp = request.form.get('otp')
        
        if not entered_otp:
            flash("Please enter the verification code.", "error")
            return render_template("creator_verify_otp.html", email=email)
        
        result = verify_otp_email(email, entered_otp, user_type='creator', purpose='registration')
        
        if result['verified']:
            # Delete verified OTP from database
            from youcert import delete_otp_from_database
            delete_otp_from_database('creator', email, purpose='registration')
            
            flash("Email verified! Please connect your YouTube channel.", "success")
            return redirect(url_for('creator.youtube_oauth'))
        else:
            flash(result['message'], "error")
            return render_template("creator_verify_otp.html", email=email)
    
    return render_template("creator_verify_otp.html", email=email)


@creator_bp.route("/creator/resend_otp/")
@limiter.limit("10 per hour")
def resend_otp():
    if 'temp_signup' not in session:
        flash("Please complete signup process.", "error")
        return redirect(url_for('creator.creator_signup'))
    
    email = session['temp_signup']['email']
    creator_name = session['temp_signup']['creator_name']
    
    email_service.delete_otp('creator', email, purpose='registration')
    otp_code = send_otp_email(email, user_type='creator', to_name=creator_name, purpose='registration')
    
    if not otp_code:
        flash("Failed to send new code. Please try again.", "error")
    else:
        flash("A new verification code has been sent to your email.", "info")
    
    return redirect(url_for('creator.verify_otp'))


# ============================================================================
# YOUTUBE OAUTH ROUTES
# ============================================================================

@creator_bp.route("/creator/youtube_oauth/")
@limiter.limit("5 per minute")
def youtube_oauth():
    if 'temp_signup' not in session:
        flash("Please complete signup process.", "error")
        return redirect(url_for('creator.creator_signup'))
        
    try:
        flow = InstalledAppFlow.from_client_config(get_google_client_config(), YOUTUBE_SCOPES)
        flow.redirect_uri = url_for('creator.oauth_callback', _external=True)
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        
        session['oauth_state'] = state
        session['oauth_state_time'] = time.time()
        return redirect(authorization_url)
        
    except Exception as e:
        secure_log(f"OAuth error: {str(e)}", 'error')
        flash("YouTube connection failed. Please try again.", "error")
        return redirect(url_for('creator.creator_signup'))


@creator_bp.route('/creator/reconnect_youtube')
@limiter.limit("5 per minute")
def reconnect_youtube():
    """Route for re-authenticating YouTube when tokens expire or are revoked."""
    if 'channel_id' not in session:
        flash("Please log in first.", "error")
        return redirect(url_for('creator.creator_login'))
    
    try:
        flow = InstalledAppFlow.from_client_config(get_google_client_config(), YOUTUBE_SCOPES)
        flow.redirect_uri = url_for('creator.oauth_callback', _external=True)
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        
        session['oauth_state'] = state
        session['oauth_state_time'] = time.time()
        session['reconnecting'] = True
        
        secure_log(f"Initiating YouTube reconnection")
        
        return redirect(authorization_url)
        
    except Exception as e:
        secure_log(f"OAuth reconnection error: {str(e)}", 'error')
        flash("Failed to initiate YouTube reconnection. Please try again.", "error")
        return redirect(url_for('creator.creator_index'))


@creator_bp.route("/creator/oauth_callback/")
@limiter.limit("10 per minute")
def oauth_callback():
    """OAuth callback with enhanced security and comprehensive error handling."""

    error = request.args.get('error')
    if error:
        flash(f"YouTube authorization failed: {error}", "error")
        return redirect(url_for('creator.creator_login'))

    state = request.args.get('state')
    stored_state = session.get('oauth_state')
    
    if not state or not stored_state or state != stored_state:
        session.pop('oauth_state', None)
        flash("Security validation failed. Please try again.", "error")
        return redirect(url_for('creator.creator_login'))
    
    is_reconnecting = session.pop('reconnecting', False)
    code = request.args.get('code')
    
    try:
        flow = InstalledAppFlow.from_client_config(get_google_client_config(), YOUTUBE_SCOPES)
        flow.redirect_uri = url_for('creator.oauth_callback', _external=True)
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
        youtube_service = build('youtube', 'v3', credentials=credentials)
        channel_response = youtube_service.channels().list(mine=True, part='snippet,statistics').execute()
        
        if not channel_response.get('items'):
            flash("No YouTube channel found.", "error")
            return redirect(url_for('creator.creator_signup'))
        
        channel = channel_response['items'][0]
        client_config = get_google_client_config()
        client_id = client_config['web']['client_id']
        client_secret = client_config['web']['client_secret']

        # ENCRYPTION: Safely encrypt all tokens
        encrypted_token = encrypt_token(credentials.token)
        encrypted_refresh_token = encrypt_token(credentials.refresh_token) if credentials.refresh_token else None
        encrypted_client_id = encrypt_token(client_id)
        encrypted_client_secret = encrypt_token(client_secret)
        encrypted_token_uri = encrypt_token(credentials.token_uri)

        # CHECK ENCRYPTION SUCCESS
        if not encrypted_token or not encrypted_client_id:
             secure_log("Encryption failed during oauth callback", 'error')
             flash("System error securing credentials.", "error")
             return redirect(url_for('creator.creator_signup'))

        if is_reconnecting:
            execute_query("""
                UPDATE creator_base.creators
                SET oauth_token = %s, refresh_token = %s, client_id = %s,
                    client_secret = %s, token_uri = %s, token_expiry = %s,
                    updated_at = NOW(), oauth_connected = TRUE
                WHERE channel_id = %s
            """, (encrypted_token, encrypted_refresh_token, encrypted_client_id,
                  encrypted_client_secret, encrypted_token_uri, credentials.expiry,
                  session['channel_id']), commit=True)
            
            flash("YouTube channel reconnected successfully!", "success")
            return redirect(url_for('creator.creator_index'))
        
        else:
            # New Signup Flow - FIXED: Use NEW processor signature (no openai_api_key)
            from youcert.logic import YouTubeProcessor
            
            profile_pic = None
            
            # Try to download profile picture with new processor
            try:
                project_id = current_app.config.get('GOOGLE_PROJECT_ID')  # Unused but kept for compat
                processor = YouTubeProcessor(
                    channel_id=channel['id'],
                    youtube_service=youtube_service,
                )
                profile_pic = processor.download_profile_picture(channel['id'])
                secure_log(f"Profile picture downloaded via processor: {profile_pic}", 'info')
                
            except Exception as processor_error:
                # If processor fails, download directly
                secure_log(f"Processor download failed, using direct download: {processor_error}", 'warning')
                
                try:
                    thumbnails = channel['snippet'].get('thumbnails', {})
                    profile_url = None
                    
                    for quality in ['high', 'medium', 'default']:
                        if quality in thumbnails:
                            profile_url = thumbnails[quality]['url']
                            break
                    
                    if profile_url:
                        import requests
                        from PIL import Image
                        import io
                        
                        response = requests.get(profile_url, timeout=30)
                        response.raise_for_status()
                        
                        img_data = response.content
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
                        
                        filename = f"{channel['id']}_profile.jpg"
                        profile_pic = save_file(output, 'profile_pictures', filename)
                        
                        secure_log(f"Profile picture downloaded directly: {profile_pic}", 'info')
                        
                except Exception as e:
                    secure_log(f"Direct profile download also failed (non-critical): {e}", 'warning')
                    profile_pic = None

            session['channel_data'] = {
                'channel_id': channel['id'],
                'channel_name': channel['snippet']['title'],
                'subscriber_count': int(channel['statistics'].get('subscriberCount', 0)),
                'youtube_channel_link': f"https://www.youtube.com/channel/{channel['id']}",
                'oauth_token': credentials.token,
                'refresh_token': credentials.refresh_token,
                'client_id': client_id,
                'client_secret': client_secret,
                'token_uri': credentials.token_uri,
                'token_expiry': credentials.expiry,
                'profile_picture_path': profile_pic
            }
            
            flash("YouTube channel connected! Please upload your signature.", "success")
            return redirect(url_for('creator.upload_signature'))
    
    except Exception as e:
        secure_log(f"OAuth callback error: {str(e)}", 'error')
        flash("YouTube connection failed.", "error")
        return redirect(url_for('creator.creator_signup'))


# ============================================================================
# SIGNATURE UPLOAD
# ============================================================================

@creator_bp.route("/creator/upload_signature/", methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def upload_signature():
    if 'temp_signup' not in session or 'channel_data' not in session:
        flash("Please complete the signup process.", "error")
        return redirect(url_for('creator.creator_signup'))
        
    if request.method == 'POST':
        if 'signature' not in request.files:
            flash("Please select a signature file.", "error")
            return render_template("upload_signature.html")
            
        file = request.files['signature']
        if file.filename == '' or not is_valid_image(file):
            flash("Please upload a valid image file.", "error")
            return render_template("upload_signature.html")
            
        try:
            filename = secure_filename(file.filename)
            channel_id = session['channel_data']['channel_id']
            signature_filename = f"signature_{channel_id}.{filename.rsplit('.', 1)[1].lower()}"
            
            file.seek(0)
            saved_signature_path = save_file(file, 'signatures', signature_filename)
            
            # Log what we saved
            secure_log(f"Signature saved to: {saved_signature_path}", 'info')
            
            signup_data = session['temp_signup']
            channel_data = session['channel_data']
            
            # Get profile picture path from session (already saved during OAuth)
            profile_picture_path = channel_data.get('profile_picture_path')
            
            # Log what we're about to save
            secure_log(
                f"Saving to database - Signature: {saved_signature_path}, Profile: {profile_picture_path}",
                'info'
            )
            
            # ENCRYPTION: Safely encrypt data from session
            enc_oauth = encrypt_token(channel_data['oauth_token'])
            enc_refresh = encrypt_token(channel_data['refresh_token']) if channel_data['refresh_token'] else None
            enc_client_id = encrypt_token(channel_data['client_id'])
            enc_secret = encrypt_token(channel_data['client_secret'])
            enc_uri = encrypt_token(channel_data['token_uri'])
            
            if not enc_oauth:
                 flash("System error securing tokens.", "error")
                 return render_template("upload_signature.html")

            execute_query("""
                INSERT INTO creator_base.creators (channel_id, channel_name, subscriber_count,
                                                 youtube_channel_link, email, password_hash, creator_name,
                                                 signature_jpg_file, profile_photo_jpg, oauth_token, refresh_token,
                                                 client_id, client_secret, token_uri, token_expiry, oauth_connected)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                channel_data['channel_id'], 
                channel_data['channel_name'],
                channel_data['subscriber_count'], 
                channel_data['youtube_channel_link'],
                signup_data['email'], 
                signup_data['password_hash'],
                signup_data['creator_name'], 
                saved_signature_path,  # Signature path
                profile_picture_path,   # Profile picture path
                enc_oauth, 
                enc_refresh, 
                enc_client_id, 
                enc_secret, 
                enc_uri,
                channel_data.get('token_expiry'), 
                True
            ), commit=True)
            
            secure_log(
                f"Creator inserted successfully - Channel ID: {channel_data['channel_id']}",
                'info'
            )
                
            secure_login_user(channel_data['channel_id'], signup_data['creator_name'], signup_data['email'])
            flash("Registration completed successfully!", "success")
            return redirect(url_for('creator.creator_index'))
            
        except Exception as e:
            secure_log(f"Signup completion error: {str(e)}", 'error')
            flash("Registration failed.", "error")
            
    return render_template("upload_signature.html")


# ============================================================================
# CREATOR LOGIN
# ============================================================================

@creator_bp.route('/creator/login/', methods=['GET', 'POST'])
@limiter.limit("8 per minute")
def creator_login():
    """Creator login with comprehensive OAuth token validation"""
    # CRITICAL FIX: Validate session before redirecting to prevent loop
    if 'channel_id' in session:
        if validate_session_security():
            return redirect(url_for('creator.creator_index'))
        else:
            clear_creator_session()

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        if not email or not password:
            flash("Email and password are required.", "error")
            return render_template("creator_login.html", email=email)

        try:
            # Use centralized database operation
            creator = execute_query("""
                SELECT channel_id, creator_name, password_hash, is_active
                FROM creator_base.creators WHERE email = %s
            """, (email,), fetch_one=True)

            if creator and check_password_hash(creator['password_hash'], password):
                
                if not creator['is_active']:
                    secure_log(f"Failed login attempt for deactivated creator: {email}", 'warning')
                    flash("Your account has been deactivated. Please contact support.", "error")
                    return render_template("creator_login.html", email=email)

                channel_id = creator['channel_id']
                
                secure_login_user(channel_id, creator['creator_name'], email)
                secure_log(f"Successful login for {email}", channel_id=channel_id)

                # Validate and refresh YouTube tokens
                token_status = validate_and_refresh_tokens(channel_id)

                if token_status['valid']:
                    if token_status['refreshed']:
                        flash("Login successful! Your YouTube access has been automatically refreshed.", "success")
                    else:
                        flash("Login successful!", "success")
                    return redirect(url_for('creator.creator_index'))
                
                else:
                    error_type = token_status.get('error')
                    
                    if error_type == 'rate_limit':
                        flash("Too many authentication attempts. Please wait a few minutes and try again.", "error")
                        return render_template("creator_login.html", email=email)
                    
                    elif error_type == 'timeout':
                        flash("Connection timeout during authentication. Please try again.", "warning")
                        return render_template("creator_login.html", email=email)
                    
                    elif error_type == 'server_error':
                        flash("Google authentication service is temporarily unavailable. Please try again in a moment.", "warning")
                        return render_template("creator_login.html", email=email)
                    
                    elif error_type == 'token_revoked':
                        flash("You have revoked access to this application. Please reconnect your YouTube channel.", "warning")
                        return redirect(url_for('creator.reconnect_youtube'))
                    
                    elif error_type == 'refresh_token_expired':
                        flash("Your YouTube session has expired due to inactivity. Please reconnect your channel.", "warning")
                        return redirect(url_for('creator.reconnect_youtube'))
                    
                    elif error_type in ['no_token', 'no_refresh_token', 'invalid_grant', 'refresh_failed', 'invalid_token', 'decryption_failed']:
                        flash("Your YouTube authentication needs to be renewed. Please reconnect your channel.", "warning")
                        return redirect(url_for('creator.reconnect_youtube'))
                    
                    else:
                        secure_log(f"Unknown token error: {error_type}", 'warning', channel_id=channel_id)
                        flash("Login successful! However, YouTube connection may need attention.", "warning")
                        return redirect(url_for('creator.creator_index'))
            
            else:
                secure_log(f"Failed login attempt for {email}", 'warning')
                flash("Invalid email or password.", "error")
                return render_template("creator_login.html", email=email)

        except Exception as e:
            secure_log(f"Error during creator login: {str(e)}", 'error')
            flash("Login failed due to a system error. Please try again.", "error")
            return render_template("creator_login.html", email=email)

    return render_template("creator_login.html")


# ============================================================================
# PASSWORD RESET
# ============================================================================

@creator_bp.route('/creator/forgot_password/', methods=['GET', 'POST'])
@limiter.limit("3 per minute")
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        if not email:
            flash("Please enter your registered email.", "error")
            return render_template("creator_forgot_password.html")
        
        try:
            user = execute_query(
                "SELECT creator_name FROM creator_base.creators WHERE email = %s",
                (email,), fetch_one=True
            )
            
            if user:
                # Generate random token
                import secrets
                reset_token = secrets.token_urlsafe(32)

                # Hash the token for database storage
                import hashlib
                token_hash = hashlib.sha256(reset_token.encode()).hexdigest()

                # Save hashed token to database
                ip_address = request.remote_addr
                save_password_reset_token_db('creator', email, token_hash, expiry_seconds=3600, ip_address=ip_address)

                # Send email with plain token
                reset_link = url_for('creator.reset_password', token=reset_token, _external=True)
                send_password_reset_email(email, reset_link, user['creator_name'])
            
            flash("If the email exists, a password reset link has been sent.", "info")
            return redirect(url_for('creator.creator_login'))
        
        except Exception as e:
            secure_log(f"Error in forgot_password: {str(e)}", 'error')
            flash("Could not process request. Please try again.", "error")
            return render_template("creator_forgot_password.html")
    
    return render_template("creator_forgot_password.html")


@creator_bp.route('/creator/reset_password/<token>/', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def reset_password(token):
    # Hash the token to look it up in database
    import hashlib
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    # Get token data from database
    token_data = get_password_reset_token_db(token_hash)

    if not token_data or token_data.get('user_type') != 'creator':
        flash("Invalid or expired reset link.", "error")
        return redirect(url_for('creator.forgot_password'))

    email = token_data.get('email')
    
    if request.method == 'POST':
        new_password = request.form.get('password')
        confirm = request.form.get('confirm')
        
        if not new_password or not confirm:
            flash("Please enter and confirm your new password.", "error")
            return render_template("creator_reset_password.html", token=token)
        
        if len(new_password) < 8:
            flash("Password must be at least 8 characters long.", "error")
            return render_template("creator_reset_password.html", token=token)
        
        if new_password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("creator_reset_password.html", token=token)
        
        try:
            hashed = generate_password_hash(new_password, method='pbkdf2:sha256:260000')
            execute_query(
                "UPDATE creator_base.creators SET password_hash = %s WHERE email = %s",
                (hashed, email), commit=True
            )
            
            # CRITICAL: Mark the password reset token as used
            delete_password_reset_token_db(token_hash)
            
            secure_log(f"Password reset completed for {email}")
            flash("Password has been reset. Please log in with your new password.", "success")
            return redirect(url_for('creator.creator_login'))
        
        except Exception as e:
            secure_log(f"Error resetting password: {str(e)}", 'error')
            flash("Failed to reset password. Please try again.", "error")
            return render_template("creator_reset_password.html", token=token)
    
    return render_template("creator_reset_password.html", token=token)


@creator_bp.route('/creator/logout/', methods=['GET', 'POST'])
@limiter.limit("8 per minute")
def creator_logout():
    channel_id = session.get('channel_id')
    if channel_id:
        secure_log(f"User logout", channel_id=channel_id)
        clear_creator_session()
        flash("You've been logged out successfully!", "info")
    else:
        flash("You were not logged in.", "info")
    return redirect(url_for('creator.creator_login'))


# ============================================================================
# SETTINGS AND PROFILE MANAGEMENT
# ============================================================================

@creator_bp.route('/creator/settings/update_password/', methods=['POST'])
@login_required
@limiter.limit("5 per minute")
def update_password():
    """Handle password update from settings page"""
    data = request.get_json() or {}
    current_pw = data.get('current_password', '').strip()
    new_pw = data.get('new_password', '').strip()
    
    if not current_pw or not new_pw:
        return jsonify(success=False, message='Both current and new passwords are required')
        
    if len(new_pw) < 8:
        return jsonify(success=False, message='New password must be at least 8 characters')
        
    try:
        row = execute_query(
            "SELECT password_hash FROM creator_base.creators WHERE channel_id = %s",
            (session.get('channel_id'),), fetch_one=True
        )
        
        if not row or not check_password_hash(row['password_hash'], current_pw):
            return jsonify(success=False, message='Current password is incorrect')

        new_hash = generate_password_hash(new_pw, method='pbkdf2:sha256:260000')
        execute_query("""
            UPDATE creator_base.creators
            SET password_hash = %s, updated_at = NOW()
            WHERE channel_id = %s
        """, (new_hash, session.get('channel_id')), commit=True)
        
        secure_log(f"Password updated successfully")
        return jsonify(success=True, message='Password updated successfully')
        
    except Exception as e:
        secure_log(f"Error updating password: {str(e)}", 'error')
        return jsonify(success=False, message='Error updating password')


@creator_bp.route('/creator/refresh_profile_picture/', methods=['POST'])
@login_required
@requires_youtube_auth
@limiter.limit("5 per minute")
def refresh_profile_picture_ajax(youtube_service):
    """Refresh profile picture from YouTube via AJAX"""
    try:   
        processor = YouTubeProcessor(
                channel_id=session['channel_id'],
                youtube_service=youtube_service,
            )
        
        profile_picture_path = processor.download_profile_picture(session['channel_id'])
        
        if profile_picture_path:
            relative_path = get_relative_path(profile_picture_path)
            execute_query("""
                UPDATE creator_base.creators
                SET profile_photo_jpg = %s, updated_at = NOW()
                WHERE channel_id = %s
            """, (relative_path, session['channel_id']), commit=True)
                
            profile_url = get_file_url(relative_path)
            if profile_url:
                profile_url += f'?t={int(time.time())}'
            
            return jsonify({
                'success': True,
                'message': 'Profile picture updated successfully!',
                'path': profile_url
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to download profile picture from YouTube.'})

    # --- ADD THIS BLOCK ---
    except YouTubeTokenExpiredError:
        secure_log(f"Token expired during profile refresh", 'warning', channel_id=session.get('channel_id'))
        return jsonify({
            'success': False,
            'message': 'YouTube connection expired. Please reconnect.',
            'redirect': url_for('creator.reconnect_youtube'),
            'needs_reconnect': True
        }), 401
    # ----------------------
            
    except Exception as e:
        secure_log(f"Error refreshing profile picture: {str(e)}", 'error')
        return jsonify({'success': False, 'message': 'Failed to refresh profile picture. Please try again.'})


@creator_bp.route('/creator/home/')
@limiter.limit("15 per minute")
@login_required
def creator_index():
    """
    Renders the creator dashboard with minimal data.

    UPDATED FOR CACHING: Renders page with placeholders, data loaded via AJAX with client-side caching
    """
    try:
        # Get profile image only (lightweight query) and normalize path
        profile_image_path = None
        try:
            creator_info = execute_query("""
                SELECT profile_photo_jpg
                FROM creator_base.creators
                WHERE channel_id = %s
            """, (session['channel_id'],), fetch_one=True)

            if creator_info and creator_info['profile_photo_jpg']:
                clean_path = _clean_static_path(creator_info['profile_photo_jpg'])
                profile_image_path = get_file_url(clean_path) or (f"/static/{clean_path}" if clean_path else None)
        except Exception as e:
            secure_log(f"Error fetching profile photo for dashboard: {str(e)}", 'error')

        # Check YouTube connection
        youtube_service = get_youtube_service()
        youtube_connected = youtube_service is not None

        # Render with placeholders - data will be loaded via AJAX
        return render_template('creator_index.html',
                             total_income=0.00,  # Placeholder
                             monthly_income=0.00,  # Placeholder
                             exams=[],  # Placeholder - loaded via AJAX
                             creator_name=session.get('creator_name', 'Creator'),
                             profile_image_path=profile_image_path,
                             total_sales=0,  # Placeholder
                             monthly_sales=0,  # Placeholder
                             month_details={},  # Placeholder
                             chart_data=[],  # Placeholder
                             current_year=2026,
                             youtube_connected=youtube_connected
                             )
                             
    except Exception as e:
        secure_log(f"Error fetching dashboard data: {str(e)}", 'error')
        flash("There was an issue loading your dashboard. Please try again.", "error")
        return render_template('creator_index.html',
                             total_income=0.00,
                             monthly_income=0.00,
                             exams=[],
                             creator_name=session.get('creator_name', 'Creator'),
                             profile_image_path=None,
                             total_sales=0,
                             monthly_sales=0,
                             month_details={},
                             chart_data=[],
                             current_year=2025,
                             youtube_connected=False
                             )



@creator_bp.route('/creator/settings/', methods=['GET'])
@limiter.limit("10 per minute")
@login_required
def creator_settings():
    """Load settings page with creator data"""
    try:
        creator_data = execute_query("""
            SELECT channel_id, email, creator_name, channel_name,
                   subscriber_count, youtube_channel_link,
                   profile_photo_jpg, signature_jpg_file
            FROM creator_base.creators
            WHERE channel_id = %s
        """, (session.get('channel_id'),), fetch_one=True)
        
        if not creator_data:
            flash('Creator profile not found.', 'error')
            return redirect(url_for('creator.creator_index'))
        
        # Convert to mutable dict
        creator_data = dict(creator_data)
            
        # Format subscriber count
        subs = creator_data.get('subscriber_count') or 0
        if subs >= 1_000_000:
            creator_data['subs_display'] = f"{subs/1_000_000:.1f}M"
        elif subs >= 1_000:
            creator_data['subs_display'] = f"{subs/1_000:.1f}K"
        else:
            creator_data['subs_display'] = str(subs)
            
        # Build URLs for images (clean path first)
        profile_clean = _clean_static_path(creator_data.get('profile_photo_jpg'))
        signature_clean = _clean_static_path(creator_data.get('signature_jpg_file'))
        creator_data['profile_photo_url'] = get_file_url(profile_clean) if profile_clean else None
        creator_data['signature_url'] = get_file_url(signature_clean) if signature_clean else None
        
    except Exception as e:
        secure_log(f"Error fetching creator settings: {str(e)}", 'error')
        flash('Failed to load settings.', 'error')
        creator_data = {}
        
    return render_template('creator_settings.html', creator=creator_data)


@creator_bp.route('/creator/settings/update_signature/', methods=['POST'])
@login_required
@limiter.limit("5 per minute")
def update_signature():
    """API endpoint for a creator to upload a new signature."""
    if 'signature' not in request.files:
        return jsonify({'success': False, 'message': 'No signature file provided.'}), 400
        
    file = request.files['signature']
    channel_id = session.get('channel_id')

    if not file or not file.filename:
        return jsonify({'success': False, 'message': 'Invalid file.'}), 400

    if not is_valid_image(file):
        return jsonify({'success': False, 'message': 'Invalid image. Please use PNG, JPG, or GIF, under 8MB.'}), 400

    try:
        # Find and delete the old signature file
        creator = execute_query(
            "SELECT signature_jpg_file FROM creator_base.creators WHERE channel_id = %s",
            (channel_id,), fetch_one=True
        )
        
        if creator and creator['signature_jpg_file']:
            delete_file(creator['signature_jpg_file'])

        # Create a secure filename
        original_filename = secure_filename(file.filename)
        ext = original_filename.rsplit('.', 1)[1].lower()
        new_filename = f"signature_{channel_id}.{ext}"
        
        # Save the new file using cloud-aware function
        file.seek(0)
        saved_path = save_file(file, 'signatures', new_filename)
        
        if not saved_path:
            return jsonify({'success': False, 'message': 'Failed to save file.'}), 500

        # Update the database
        execute_query("""
            UPDATE creator_base.creators
            SET signature_jpg_file = %s, updated_at = NOW()
            WHERE channel_id = %s
        """, (saved_path, channel_id), commit=True)

        # Generate the new URL
        new_signature_url = get_file_url(saved_path)
        if new_signature_url:
            new_signature_url += f'?t={int(time.time())}'

        return jsonify({
            'success': True,
            'message': 'Signature updated successfully!',
            'signature_url': new_signature_url
        })

    except Exception as e:
        secure_log(f"Error updating signature: {str(e)}", 'error')
        return jsonify({'success': False, 'message': 'An unexpected error occurred. Please try again.'}), 500


@creator_bp.route('/creator/profile_update/', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def profile_update_ajax():
    """Handles profile updates via AJAX"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Invalid request format.'})
            
        creator_name = data.get('creator_name', '').strip()
        
        if not creator_name:
            return jsonify({'success': False, 'message': 'Creator name cannot be empty.'})
            
        if len(creator_name) > 100:
            return jsonify({'success': False, 'message': 'Creator name must be less than 100 characters.'})
            
        execute_query("""
            UPDATE creator_base.creators
            SET creator_name = %s, updated_at = NOW()
            WHERE channel_id = %s
        """, (creator_name, session['channel_id']), commit=True)
        
        session['creator_name'] = creator_name
        secure_log(f"Profile updated successfully")
        return jsonify({'success': True, 'message': 'Profile updated successfully!'})
        
    except Exception as e:
        secure_log(f"Error updating creator profile: {str(e)}", 'error')
        return jsonify({'success': False, 'message': 'Failed to update profile. Please try again.'})


# ============================================================================
# EXAM MANAGEMENT
# ============================================================================

@creator_bp.route('/creator/listed_exams/')
@limiter.limit("20 per minute")
@login_required
def listed_exam():
    """Display creator's listed exams with comprehensive data"""
    try:
        results = execute_query("""
            SELECT unique_exam_number, exam_title, exam_price,
                   video_id, playlist_id, is_active, created_at, thumbnail_image,
                   exam_description, channel_name
            FROM exam.listed_exams
            WHERE channel_id = %s
            ORDER BY created_at DESC
            LIMIT 50
        """, (session['channel_id'],), fetch_all=True)
        
        exams = []

        for result in (results or []):
            # Convert to dict (same pattern as exam_details route)
            exam = dict(result)

            # Handle thumbnail (exact same way as exam_details route)
            exam['thumbnail_url'] = None
            if exam.get('thumbnail_image'):
                exam['thumbnail_url'] = get_file_url(exam['thumbnail_image'])

            # Process other fields
            exam['exam_title'] = exam.get('exam_title') or 'Untitled Exam'
            exam['exam_price'] = float(exam['exam_price']) if exam.get('exam_price') else 0.00
            exam['is_active'] = bool(exam.get('is_active'))
            exam['exam_description'] = exam.get('exam_description') or ''
            exam['channel_name'] = exam.get('channel_name') or ''
            exam['content_type'] = 'Playlist' if exam.get('playlist_id') else 'Video'
            exam['status_display'] = 'Active' if exam['is_active'] else 'Inactive'

            exams.append(exam)
            
        return render_template('creator_listed_exam_list.html',
                             exams=exams,
                             total_exams=len(exams))
                             
    except Exception as e:
        secure_log(f"Error fetching listed exams: {str(e)}", 'error')
        flash("Failed to load exams. Please try again.", "error")
        return render_template('creator_listed_exam_list.html', exams=[], total_exams=0)


@creator_bp.route('/creator/list_new_exam/', methods=['GET', 'POST'])
@login_required
@limiter.limit("20 per minute")
def list_new_exam():
    """
    List new exam page with Cloud Tasks integration and Vertex AI REST API.
    
    UPDATED FOR v8: Now uses Vertex AI REST API instead of OpenAI
    
    Behavior:
    - LOCAL DEVELOPMENT: Processes synchronously (immediate response)
    - CLOUD RUN: Queues task to Cloud Tasks (returns 202 Accepted)
    
    All existing validation is preserved.
    """
    channel_id = session.get('channel_id')
    
    if request.method == 'POST':
        url = request.form.get('youtube_url', '').strip()
        
        # ====================================================================
        # INPUT VALIDATION (Unchanged)
        # ====================================================================
        
        if not url:
            return jsonify({
                "success": False, 
                "message": "Please provide a YouTube URL."
            }), 400
            
        if 'youtube.com' not in url and 'youtu.be' not in url:
            return jsonify({
                "success": False, 
                "message": "Please provide a valid YouTube URL."
            }), 400
        
        # Check for Gemini API key
        gemini_key = Config.GEMINI_API_KEY
        if not gemini_key:
            return jsonify({
                "success": False, 
                "message": "Gemini AI is not configured. Please contact support."
            }), 500
        
        # ====================================================================
        # YOUTUBE API CONNECTIVITY TEST (Unchanged)
        # ====================================================================
        
        secure_log(f"Testing YouTube API connectivity...", 'info', channel_id=channel_id)
        
        try:
            youtube_service = get_youtube_service(channel_id=channel_id)
            
            if not youtube_service:
                secure_log(f"Failed to create YouTube service", 'error', channel_id=channel_id)
                return jsonify({
                    "success": False,
                    "message": "Failed to connect to YouTube. Please reconnect your channel.",
                    "redirect": url_for('creator.reconnect_youtube'),
                    "needs_reconnect": True
                }), 401
            
            # Test the service with a simple API call
            secure_log(f"Making test API call to verify token...", 'info', channel_id=channel_id)
            
            test_request = youtube_service.channels().list(
                part='id',
                mine=True,
                maxResults=1
            )
            test_response = test_request.execute()
            
            if not test_response:
                secure_log(f"Test API call returned no response", 'error', channel_id=channel_id)
                return jsonify({
                    "success": False,
                    "message": "YouTube connection test failed. Please reconnect your channel.",
                    "redirect": url_for('creator.reconnect_youtube'),
                    "needs_reconnect": True
                }), 401
            
            secure_log(f"YouTube API test successful", 'info', channel_id=channel_id)
            
        except Exception as e:
            error_str = str(e).lower()
            secure_log(f"YouTube API test failed: {str(e)}", 'error', channel_id=channel_id)
            
            if 'invalid_grant' in error_str or 'token' in error_str or 'expired' in error_str or 'revoked' in error_str:
                return jsonify({
                    "success": False,
                    "message": "Your YouTube session has expired or been revoked. Please reconnect your channel.",
                    "redirect": url_for('creator.reconnect_youtube'),
                    "needs_reconnect": True
                }), 401
            
            elif 'quota' in error_str or 'rate' in error_str:
                return jsonify({
                    "success": False,
                    "message": "YouTube API quota exceeded. Please try again later."
                }), 429
            
            else:
                return jsonify({
                    "success": False,
                    "message": "Failed to connect to YouTube. Please try again or reconnect your channel.",
                    "redirect": url_for('creator.reconnect_youtube'),
                    "needs_reconnect": True
                }), 500
        
        # ====================================================================
        # CLOUDFLARE QUEUES INTEGRATION (Gemini API)
        # ====================================================================
        
        secure_log(f"Preparing video processing task for {url} (Gemini API)", 'info', channel_id=channel_id)
        
        try:
            # Get credentials from the authenticated YouTube service
            credentials = youtube_service._http.credentials
            
            # Package credentials for background task
            creds_data = {
                'token': credentials.token,
                'refresh_token': credentials.refresh_token,
                'token_uri': credentials.token_uri or 'https://oauth2.googleapis.com/token',
                'client_id': credentials.client_id,
                'client_secret': credentials.client_secret,
            }
            
            # Encrypt credentials using centralized encrypt_token
            encrypted_creds = encrypt_token(json.dumps(creds_data))
            
            if not encrypted_creds:
                secure_log("Failed to encrypt credentials for task", 'error', channel_id=channel_id)
                return jsonify({
                    "success": False,
                    "message": "Failed to prepare processing task. Please try again."
                }), 500
            
            # Import queue function
            from youcert.logic import queue_video_processing
            
            # Queue the video processing task
            # UPDATED: No longer passing openai_api_key (using Vertex AI now)
            result = queue_video_processing(
                video_id='',  # Will be extracted from URL by processor
                channel_id=channel_id,
                url=url,
                credentials_json=encrypted_creds,
                openai_api_key=''  # No longer used, kept for compatibility
            )
            
            # Handle result based on execution mode
            if result.get('success'):
                execution_mode = result.get('execution_mode', 'unknown')
                
                if execution_mode == 'local_sync':
                    # LOCAL DEVELOPMENT: Processing completed synchronously
                    secure_log(f"Processing completed (local mode, Vertex AI REST)", 'info', channel_id=channel_id)
                    
                    # Get the actual processing result
                    processing_result = result.get('result', {})
                    
                    if processing_result.get('success'):
                        return jsonify({
                            "success": True, 
                            "message": "Exam created successfully! You can view it in your Listed Exams page.",
                            "data": processing_result.get('data', {}),
                            "execution_mode": "local_sync",
                            "ai_backend": "gemini_api"
                        }), 200
                    else:
                        return jsonify({
                            "success": False,
                            "message": processing_result.get('message', 'Processing failed. Please try again.')
                        }), 400
                
                else:
                    # CLOUD RUN: Task queued to Cloud Tasks
                    secure_log(
                        f"Task queued to Cloud Tasks (Vertex AI REST API)", 
                        'info', 
                        channel_id=channel_id,
                        context={'task_name': result.get('task_name')}
                    )
                    
                    return jsonify({
                        "success": True,
                        "message": "Video processing has started! This may take a few minutes. You'll see the exam in your Listed Exams page once complete.",
                        "task_name": result.get('task_name'),
                        "status": "processing",
                        "execution_mode": "cloudflare_queues",
                        "ai_backend": "gemini_api"
                    }), 202  # HTTP 202 Accepted
            
            else:
                # Task queuing failed
                secure_log(
                    f"Failed to queue task: {result.get('message')}", 
                    'error',
                    channel_id=channel_id
                )
                
                return jsonify({
                    "success": False,
                    "message": "Failed to start processing. Please try again."
                }), 500
                
        except Exception as e:
            secure_log(f"Error in list_new_exam: {str(e)}", 'error', channel_id=channel_id)
            return jsonify({
                "success": False,
                "message": "An unexpected error occurred. Please try again."
            }), 500
    
    # GET request - show the form
    return render_template('creator_list_new_exam.html')



@creator_bp.route('/creator/exam/<exam_number>/')
@limiter.limit("20 per minute")
@login_required
def exam_details(exam_number):
    """Display comprehensive exam details"""
    try:
        exam = execute_query("""
            SELECT unique_exam_number, exam_title, exam_description, channel_name,
                   is_active, created_at, thumbnail_image, exam_price, video_id, playlist_id,
                   summary_path, number_of_subscribers, updated_at
            FROM exam.listed_exams
            WHERE unique_exam_number = %s AND channel_id = %s
        """, (exam_number, session['channel_id']), fetch_one=True)

        if not exam:
            flash("Exam not found or you do not have permission to view it.", "error")
            return redirect(url_for('creator.listed_exam'))

        # Convert to mutable dict
        exam_data = dict(exam)

        # Handle Thumbnail Paths (use get_file_url directly - same as user_routes)
        exam_data['thumbnail_url'] = None
        if exam_data.get('thumbnail_image'):
            exam_data['thumbnail_url'] = get_file_url(exam_data['thumbnail_image'])
        else:
            exam_data['thumbnail_image'] = None
            exam_data['thumbnail_url'] = None

        # Process other fields
        exam_data['is_active'] = bool(exam['is_active'])
        exam_data['exam_price'] = float(exam['exam_price']) if exam['exam_price'] else 0.00

        # Handle summary path (using similar logic if needed, or get_file_url)
        if exam_data.get('summary_path'):
            exam_data['summary_url'] = get_file_url(exam_data['summary_path'])

        # Fetch question count from exam_questions table
        import json
        questions_data = execute_query("""
            SELECT questions_json
            FROM exam.exam_questions
            WHERE unique_exam_number = %s
        """, (exam_number,), fetch_one=True)

        if questions_data and questions_data.get('questions_json'):
            try:
                questions = json.loads(questions_data['questions_json'])
                exam_data['total_questions'] = len(questions)
            except json.JSONDecodeError:
                exam_data['total_questions'] = 0
        else:
            exam_data['total_questions'] = 0

        # Set passing score (default 80%)
        exam_data['passing_score'] = 80

        # Construct YouTube video link
        if exam_data.get('video_id'):
            exam_data['youtube_video_link'] = f"https://www.youtube.com/watch?v={exam_data['video_id']}"
        elif exam_data.get('playlist_id'):
            exam_data['youtube_video_link'] = f"https://www.youtube.com/playlist?list={exam_data['playlist_id']}"
        else:
            exam_data['youtube_video_link'] = "#"

        return render_template('creator_exam_details.html', exam=exam_data)

    except Exception as e:
        secure_log(f"Error fetching exam details: {str(e)}", 'error')
        flash("Failed to load exam details. Please try again.", "error")
        return redirect(url_for('creator.listed_exam'))


@creator_bp.route('/creator/exam/<exam_number>/update_price/', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def update_exam_price(exam_number):
    """Updates the price of a specific exam."""
    data = request.get_json()
    new_price = data.get('price')
    
    if new_price is None:
        return jsonify({'success': False, 'message': 'New price not provided.'}), 400
        
    try:
        new_price = float(new_price)
        if new_price < 0:
            return jsonify({'success': False, 'message': 'Price cannot be negative.'}), 400
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid price format.'}), 400
        
    try:
        # Use centralized execute_query for consistency with rest of codebase
        rows_affected = execute_query("""
            UPDATE exam.listed_exams
            SET exam_price = %s, updated_at = NOW()
            WHERE unique_exam_number = %s AND channel_id = %s
        """, (new_price, exam_number, session['channel_id']), commit=True)

        if rows_affected == 0:
            return jsonify({'success': False, 'message': 'Exam not found or you do not have permission.'}), 404

        secure_log(f"Exam price updated successfully")
        return jsonify({'success': True, 'message': 'Exam price updated successfully.'})
        
    except Exception as e:
        secure_log(f"Error updating exam price: {str(e)}", 'error')
        return jsonify({'success': False, 'message': 'Failed to update price.'}), 500


@creator_bp.route('/creator/exam/<exam_number>/toggle_status/', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def toggle_exam_status(exam_number):
    """Toggle exam status with better feedback"""
    try:
        exam = execute_query("""
            SELECT is_active FROM exam.listed_exams
            WHERE unique_exam_number = %s AND channel_id = %s
        """, (exam_number, session['channel_id']), fetch_one=True)
        
        if not exam:
            return jsonify({'success': False, 'message': 'Exam not found or access denied.'})
            
        new_status = not exam['is_active']
        
        execute_query("""
            UPDATE exam.listed_exams
            SET is_active = %s, updated_at = NOW()
            WHERE unique_exam_number = %s AND channel_id = %s
        """, (new_status, exam_number, session['channel_id']), commit=True)
        
        status_text = "activated" if new_status else "deactivated"
        secure_log(f"Exam {status_text} successfully")
        return jsonify({
            'success': True,
            'message': f'Exam {status_text} successfully!',
            'new_status': new_status,
            'status_display': 'Active' if new_status else 'Inactive'
        })
        
    except Exception as e:
        secure_log(f"Error toggling exam status: {str(e)}", 'error')
        return jsonify({'success': False, 'message': 'Failed to update exam status. Please try again.'})


@creator_bp.route('/creator/exam/<exam_number>/questions/', methods=['GET'])
@login_required
@limiter.limit("20 per minute")
def get_exam_questions(exam_number):
    """Fetch AI-generated questions and answers for creator's exam"""
    try:
        # Verify creator owns this exam
        exam = execute_query("""
            SELECT unique_exam_number, exam_title
            FROM exam.listed_exams
            WHERE unique_exam_number = %s AND channel_id = %s
        """, (exam_number, session['channel_id']), fetch_one=True)

        if not exam:
            return jsonify({
                'success': False,
                'message': 'Exam not found or you do not have permission to view it.'
            }), 404

        # Fetch questions JSON
        questions_data = execute_query("""
            SELECT questions_json
            FROM exam.exam_questions
            WHERE unique_exam_number = %s
        """, (exam_number,), fetch_one=True)

        if not questions_data or not questions_data.get('questions_json'):
            return jsonify({
                'success': False,
                'message': 'No questions found for this exam.'
            }), 404

        # Parse questions JSON
        import json
        questions = json.loads(questions_data['questions_json'])

        return jsonify({
            'success': True,
            'exam_title': exam['exam_title'],
            'total_questions': len(questions),
            'questions': questions  # Includes questions, options, correct_answer, and explanation
        })

    except json.JSONDecodeError as e:
        secure_log(f"Error parsing questions JSON: {str(e)}", 'error')
        return jsonify({
            'success': False,
            'message': 'Error parsing question data.'
        }), 500
    except Exception as e:
        secure_log(f"Error fetching exam questions: {str(e)}", 'error')
        return jsonify({
            'success': False,
            'message': 'Failed to fetch questions. Please try again.'
        }), 500


# ============================================================================
# API ENDPOINTS
# ============================================================================

@creator_bp.route('/creator/api/dashboard_stats/')
@login_required
@limiter.limit("20 per minute")
def dashboard_stats_api():
    """
    API endpoint for dashboard statistics.
    NEW: Uses client-side cookies (30-minute expiry) instead of server cache.
    """
    try:
        channel_id = session['channel_id']

        # Check if earnings data exists in client-side cookie
        earnings_cookie = request.cookies.get(f'creator_earnings_{channel_id}')

        if earnings_cookie:
            # Parse and return cached earnings from cookie
            try:
                import base64
                earnings_data = json.loads(base64.b64decode(earnings_cookie).decode('utf-8'))
                secure_log(f"Using client-side cookie for earnings (channel: {channel_id})", 'info')

                return jsonify({
                    'success': True,
                    'data': earnings_data,
                    'from_cache': True
                })
            except Exception as decode_error:
                # Cookie corrupted, fetch fresh data
                secure_log(f"Cookie decode error: {decode_error}", 'warning')

        # Fetch fresh earnings data from database
        earnings_calculator = CreatorEarningsCalculator(channel_id)
        earnings_summary = earnings_calculator.get_earnings_summary()

        earnings_data = {
            'total_income': earnings_summary.get('total_cumulative_income', 0.00),
            'monthly_income': earnings_summary.get('monthly_income', 0.00),
            'total_sales': earnings_summary.get('total_sales', 0),
            'monthly_sales': earnings_summary.get('monthly_sales', 0)
        }

        # Create response and set client-side cookie (30 minutes expiry)
        response = jsonify({
            'success': True,
            'data': earnings_data,
            'from_cache': False
        })

        # Encode earnings data and set as cookie (30-minute expiry)
        import base64
        from datetime import datetime, timedelta

        earnings_json = json.dumps(earnings_data)
        earnings_b64 = base64.b64encode(earnings_json.encode('utf-8')).decode('utf-8')

        response.set_cookie(
            f'creator_earnings_{channel_id}',
            earnings_b64,
            max_age=1800,  # 30 minutes in seconds
            httponly=True,  # Prevent JavaScript access
            samesite='Lax',
            secure=False  # Set to True in production with HTTPS
        )

        secure_log(f"Fresh earnings fetched and cookie set (channel: {channel_id})", 'info')

        return response

    except Exception as e:
        secure_log(f"Error fetching dashboard stats: {str(e)}", 'error')
        return jsonify({'success': False, 'message': 'Failed to fetch statistics'})


@creator_bp.route('/creator/api/dashboard_exams/')
@login_required
@limiter.limit("20 per minute")
def dashboard_exams_api():
    """API endpoint for dashboard exam list (top 5 recent exams)"""
    try:
        channel_id = session.get('channel_id')
        secure_log(f"Fetching dashboard exams for channel_id: {channel_id}", 'info')

        exams = execute_query("""
            SELECT
                unique_exam_number,
                exam_title,
                exam_price,
                is_active,
                created_at
            FROM exam.listed_exams
            WHERE channel_id = %s
            ORDER BY created_at DESC
            LIMIT 5
        """, (channel_id,), fetch_all=True)

        secure_log(f"Dashboard exams query returned {len(exams) if exams else 0} exams", 'info')

        return jsonify({
            'success': True,
            'data': exams or []
        })

    except Exception as e:
        secure_log(f"Error fetching dashboard exams: {str(e)}", 'error')
        return jsonify({'success': False, 'message': 'Failed to fetch exams'})


@creator_bp.route('/creator/api/exam_count/')
@login_required
@limiter.limit("15 per minute")
def exam_count_api():
    """API endpoint for exam count"""
    try:
        result = execute_query("""
            SELECT
                COUNT(*) as total_exams,
                SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active_exams
            FROM exam.listed_exams
            WHERE channel_id = %s
        """, (session['channel_id'],), fetch_one=True)

        return jsonify({
            'success': True,
            'data': {
                'total_exams': result['total_exams'] if result else 0,
                'active_exams': result['active_exams'] if result else 0
            }
        })

    except Exception as e:
        secure_log(f"Error fetching exam count: {str(e)}", 'error')
        return jsonify({'success': False, 'message': 'Failed to fetch exam count'})


@creator_bp.route('/creator/api/processing_progress/<video_id>')
@login_required
@limiter.limit("30 per minute")
def get_processing_progress(video_id):
    """
    API endpoint to get real-time processing progress for a video.

    Returns progress percentage, current stage, and chunk processing status.
    Used for live updates in the UI.
    """
    try:
        channel_id = session.get('channel_id')

        result = execute_query("""
            SELECT
                status,
                total_chunks,
                processed_chunks,
                progress_percentage,
                current_stage,
                error_message,
                started_at,
                updated_at,
                TIMESTAMPDIFF(SECOND, started_at, NOW()) as elapsed_seconds
            FROM creator_base.video_processing_status
            WHERE content_id = %s AND channel_id = %s
        """, (video_id, channel_id), fetch_one=True)

        if not result:
            return jsonify({
                'success': False,
                'message': 'Processing status not found'
            }), 404

        # Calculate estimated time remaining (if processing)
        eta_seconds = None
        if result['status'] == 'processing' and result['processed_chunks'] and result['total_chunks']:
            elapsed = result['elapsed_seconds']
            chunks_done = result['processed_chunks']
            chunks_total = result['total_chunks']

            if chunks_done > 0:
                avg_time_per_chunk = elapsed / chunks_done
                chunks_remaining = chunks_total - chunks_done
                eta_seconds = int(avg_time_per_chunk * chunks_remaining)

        return jsonify({
            'success': True,
            'data': {
                'video_id': video_id,
                'status': result['status'],
                'progress_percentage': float(result['progress_percentage']) if result['progress_percentage'] else 0.0,
                'current_stage': result['current_stage'] or 'Initializing...',
                'total_chunks': result['total_chunks'],
                'processed_chunks': result['processed_chunks'] or 0,
                'error_message': result['error_message'],
                'elapsed_seconds': result['elapsed_seconds'],
                'eta_seconds': eta_seconds,
                'started_at': result['started_at'].isoformat() if result['started_at'] else None,
                'updated_at': result['updated_at'].isoformat() if result['updated_at'] else None
            }
        })

    except Exception as e:
        secure_log(f"Error fetching processing progress: {str(e)}", 'error', channel_id=session.get('channel_id'))
        return jsonify({'success': False, 'message': 'Failed to fetch progress'}), 500


@creator_bp.route('/creator/api/processing_videos')
@login_required
@limiter.limit("30 per minute")
def get_processing_videos():
    """
    API endpoint to get all currently processing videos for the logged-in creator.

    Returns a list of all videos currently being processed with their progress.
    Used to show processing status on the listed exams page.
    """
    try:
        channel_id = session.get('channel_id')

        # Try with all columns, fallback if columns don't exist
        try:
            results = execute_query("""
                SELECT
                    content_id as video_id,
                    status,
                    total_chunks,
                    processed_chunks,
                    progress_percentage,
                    current_stage,
                    started_at,
                    TIMESTAMPDIFF(SECOND, started_at, NOW()) as elapsed_seconds
                FROM creator_base.video_processing_status
                WHERE channel_id = %s AND status = 'processing'
                ORDER BY started_at DESC
            """, (channel_id,))
        except Exception as column_error:
            # Fallback query with only basic columns if new columns don't exist
            secure_log(f"Column error in processing videos, using minimal fallback: {str(column_error)}", 'warning', channel_id=channel_id)
            results = execute_query("""
                SELECT
                    content_id as video_id,
                    status,
                    started_at,
                    TIMESTAMPDIFF(SECOND, started_at, NOW()) as elapsed_seconds
                FROM creator_base.video_processing_status
                WHERE channel_id = %s AND status = 'processing'
                ORDER BY started_at DESC
            """, (channel_id,))

        if not results:
            return jsonify({
                'success': True,
                'data': []
            })

        # Process each video
        videos = []
        for result in results:
            # Calculate ETA
            eta_text = 'Calculating...'
            total_chunks = result.get('total_chunks', None)
            processed_chunks = result.get('processed_chunks', 0)

            if total_chunks and processed_chunks and processed_chunks > 0:
                elapsed = result['elapsed_seconds']
                chunks_done = processed_chunks
                chunks_total = total_chunks

                avg_time_per_chunk = elapsed / chunks_done
                chunks_remaining = chunks_total - chunks_done
                eta_seconds = int(avg_time_per_chunk * chunks_remaining)

                minutes = eta_seconds // 60
                seconds = eta_seconds % 60
                if minutes > 0:
                    eta_text = f'ETA: {minutes}m {seconds}s'
                else:
                    eta_text = f'ETA: {seconds}s'

            videos.append({
                'video_id': result['video_id'],
                'status': result['status'],
                'progress_percentage': float(result['progress_percentage']) if result.get('progress_percentage') else 0.0,
                'current_stage': result.get('current_stage') or 'Initializing...',
                'total_chunks': total_chunks or 0,
                'processed_chunks': processed_chunks or 0,
                'eta_text': eta_text
            })

        return jsonify({
            'success': True,
            'data': videos
        })

    except Exception as e:
        secure_log(f"Error fetching processing videos: {str(e)}", 'error', channel_id=session.get('channel_id'))
        return jsonify({'success': False, 'message': 'Failed to fetch processing videos'}), 500


# Assuming there's a /creator/exam/<exam_number>/toggle_status/ route here that ends with the following:
# @creator_bp.route('/creator/exam/<exam_number>/toggle_status/', methods=['POST'])
# @login_required
# @limiter.limit("5 per minute")
# def toggle_exam_status(exam_number):
#     try:
#         channel_id = session.get('channel_id')
#         exam = execute_query("SELECT is_active FROM exam.listed_exams WHERE unique_exam_number = %s AND channel_id = %s",
#                              (exam_number, channel_id), fetch_one=True)
#         if not exam:
#             return jsonify(success=False, message='Exam not found or denied.'), 404
#
#         new_status = 1 if exam['is_active'] == 0 else 0
#         execute_query("UPDATE exam.listed_exams SET is_active = %s, updated_at = NOW() WHERE unique_exam_number = %s AND channel_id = %s",
#                       (new_status, exam_number, channel_id), commit=True)
#         return jsonify(success=True, message=f'Exam status updated to {"active" if new_status else "inactive"}.')
#
#     except Exception as e:
#         secure_log(f"Error toggling exam status: {str(e)}", 'error', channel_id=session.get('channel_id'))
#         return jsonify(success=False, message='An error occurred while toggling the status.'), 500


@creator_bp.route('/creator/exam/<exam_number>/sync_data/', methods=['POST'])
@login_required
@requires_youtube_auth
@limiter.limit("5 per minute")
def sync_exam_data(exam_number, youtube_service):
    """Manually attempt to recover missing thumbnails or re-queue question generation"""
    try:
        channel_id = session.get('channel_id')
        exam = execute_query("""
            SELECT e.video_id, e.playlist_id, e.thumbnail_image, e.exam_title,
                   q.questions_json 
            FROM exam.listed_exams e
            LEFT JOIN exam.exam_questions q ON e.unique_exam_number = q.unique_exam_number
            WHERE e.unique_exam_number = %s AND e.channel_id = %s
        """, (exam_number, channel_id), fetch_one=True)

        if not exam:
            return jsonify(success=False, message='Exam not found or denied.'), 404

        from youcert.logic import YouTubeProcessor
        from youcert.logic.task_manager import TaskManager
        processor = YouTubeProcessor(channel_id=channel_id, youtube_service=youtube_service)

        actions_taken = []
        is_missing_thumbnail = not exam.get('thumbnail_image')
        is_missing_questions = not exam.get('questions_json') or exam.get('questions_json') == '[]'

        if not is_missing_thumbnail and not is_missing_questions:
            return jsonify(success=True, message='Exam data is already complete.')

        # 1. Recover Thumbnail
        if is_missing_thumbnail:
            thumbnail_path = None
            if exam.get('video_id'):
                video_details = processor.get_video_details(exam['video_id'])
                if video_details and video_details.get('thumbnail_url'):
                    thumbnail_filename = f"{exam['video_id']}.jpg"
                    thumbnail_path = processor.download_thumbnail(video_details['thumbnail_url'], thumbnail_filename, folder='videos')
            elif exam.get('playlist_id'):
                playlist_details = processor.get_playlist_details(exam['playlist_id'], max_results=1)
                if playlist_details and playlist_details.get('videos'):
                    first_video = playlist_details['videos'][0]
                    if first_video.get('thumbnail_url'):
                        thumbnail_filename = f"{first_video['video_id']}.jpg"
                        thumbnail_path = processor.download_thumbnail(first_video['thumbnail_url'], thumbnail_filename, folder='videos')

            if thumbnail_path:
                execute_query("""
                    UPDATE exam.listed_exams
                    SET thumbnail_image = %s, updated_at = NOW()
                    WHERE unique_exam_number = %s AND channel_id = %s
                """, (thumbnail_path, exam_number, channel_id))
                actions_taken.append("Thumbnail recovered")
            else:
                actions_taken.append("Thumbnail recovery failed")

        # 2. Recover Questions (Re-queue generation)
        if is_missing_questions:
            # Construct url from video_id or playlist_id
            url = None
            if exam.get('video_id'):
                url = f"https://www.youtube.com/watch?v={exam['video_id']}"
            elif exam.get('playlist_id'):
                url = f"https://www.youtube.com/playlist?list={exam['playlist_id']}"
                
            if url:
                try:
                    credentials = youtube_service._http.credentials
                    import json
                    creds_data = {
                        'token': credentials.token,
                        'refresh_token': credentials.refresh_token,
                        'token_uri': credentials.token_uri or 'https://oauth2.googleapis.com/token',
                        'client_id': credentials.client_id,
                        'client_secret': credentials.client_secret,
                    }
                    encrypted_creds = encrypt_token(json.dumps(creds_data))
                    
                    if encrypted_creds:
                        from config import Config
                        TaskManager.queue_task(
                            task_type='video_processing',
                            payload={
                                'video_id': exam_number,
                                'channel_id': channel_id,
                                'url': url,
                                'credentials_json': encrypted_creds,
                                'openai_api_key': Config.GEMINI_API_KEY
                            },
                            channel_id=channel_id
                        )
                        actions_taken.append("Question generation queued")
                    else:
                        actions_taken.append("Failed to encrypt credentials")
                except Exception as cred_err:
                    actions_taken.append(f"Failed to prepare credentials: {str(cred_err)}")
            else:
                actions_taken.append("Missing URL to queue generation")

        message = "Sync complete: " + ", ".join(actions_taken)
        return jsonify(success=True, message=message)

    except Exception as e:
        secure_log(f"Error syncing data for exam {exam_number}: {e}", 'error', channel_id=session.get('channel_id'))
        return jsonify(success=False, message='An unexpected error occurred during sync.'), 500


@creator_bp.route('/creator/exam/<exam_number>/regenerate_questions/', methods=['POST'])
@login_required
def regenerate_exam_questions(exam_number):
    youtube_service = get_youtube_service()
    if not youtube_service:
        return jsonify(success=False, message='YouTube authentication required.'), 401
    try:
        channel_id = session.get('channel_id')
        exam = execute_query("""
            SELECT e.video_id, e.playlist_id, e.exam_title
            FROM exam.listed_exams e
            WHERE e.unique_exam_number = %s AND e.channel_id = %s
        """, (exam_number, channel_id), fetch_one=True)

        if not exam:
            return jsonify(success=False, message='Exam not found or denied.'), 404

        from youcert.logic.video_processor import can_regenerate_questions
        can_regenerate, days_remaining, _ = can_regenerate_questions(exam_number)

        if not can_regenerate:
            return jsonify({
                'success': False, 
                'blocked': True,
                'days_remaining': days_remaining,
                'message': f'Questions were recently updated. You can regenerate them again in {days_remaining} days.'
            })

        # Process the generation using the background queue
        url = None
        if exam.get('video_id'):
            url = f"https://www.youtube.com/watch?v={exam['video_id']}"
        elif exam.get('playlist_id'):
            url = f"https://www.youtube.com/playlist?list={exam['playlist_id']}"

        if url:
            credentials = youtube_service._http.credentials
            import json
            creds_data = {
                'token': credentials.token,
                'refresh_token': credentials.refresh_token,
                'token_uri': credentials.token_uri or 'https://oauth2.googleapis.com/token',
                'client_id': credentials.client_id,
                'client_secret': credentials.client_secret,
            }
            encrypted_creds = encrypt_token(json.dumps(creds_data))

            if encrypted_creds:
                from youcert.logic.task_manager import TaskManager
                from config import Config
                TaskManager.queue_task(
                    task_type='video_processing',
                    payload={
                        'video_id': exam_number,
                        'channel_id': channel_id,
                        'url': url,
                        'credentials_json': encrypted_creds,
                        'openai_api_key': Config.GEMINI_API_KEY
                    },
                    channel_id=channel_id
                )
                return jsonify(success=True, message='Question regeneration has started successfully. This process runs in the background.')
            else:
                return jsonify(success=False, message='Failed to encrypt credentials required for generation.'), 500
        else:
            return jsonify(success=False, message='Missing URL to regenerate questions.'), 400

    except Exception as e:
        secure_log(f"Error regenerating questions manual trigger: {e}", 'error', channel_id=session.get('channel_id'))
        return jsonify(success=False, message='An unexpected error occurred during regeneration request.'), 500


@creator_bp.route('/creator/check_youtube_status/')
@login_required
@limiter.limit("20 per minute")
def check_youtube_status():
    """API endpoint to check YouTube authentication status."""
    try:
        channel_id = session.get('channel_id')
        if not channel_id:
            return jsonify({
                'success': False,
                'message': 'Not logged in'
            }), 401
        
        token_status = validate_and_refresh_tokens(channel_id)
        
        return jsonify({
            'success': True,
            'channel_id': channel_id,
            'valid': token_status['valid'],
            'refreshed': token_status['refreshed'],
            'error': token_status['error'],
            'error_detail': token_status['error_detail']
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500


# ============================================================================
# BANK ACCOUNT MANAGEMENT
# ============================================================================

@creator_bp.route('/creator/bank_accounts/')
@login_required
@limiter.limit("10 per minute")
def view_bank_accounts():
    """View all listed bank accounts for the creator"""
    channel_id = session.get('channel_id')
    
    try:
        bank_accounts = execute_query("""
            SELECT 
                id,
                account_holder_name,
                bank_name,
                branch_name,
                account_type,
                country_code,
                currency_code,
                verification_status,
                is_active,
                is_frozen,
                created_at,
                updated_at,
                verified_at,
                rejection_reason,
                ifsc_code,
                swift_code,
                account_number
            FROM creator_base.creator_bank_info
            WHERE channel_id = %s
            ORDER BY is_active DESC, created_at DESC
        """, (channel_id,), fetch_all=True)
        
        formatted_accounts = []
        status_map = {
            0: {'label': 'Pending Verification', 'class': 'warning'},
            1: {'label': 'Verified', 'class': 'success'},
            2: {'label': 'Rejected', 'class': 'danger'},
            3: {'label': 'Under Review', 'class': 'info'}
        }
        
        for account in (bank_accounts or []):
            account = dict(account)
            
            # DECRYPTION: Masked number
            try:
                decrypted_num = decrypt_token(account['account_number'])
                if decrypted_num:
                    account['account_number_masked'] = f"XXXX-{decrypted_num[-4:]}"
                else:
                    account['account_number_masked'] = "Error"
            except Exception:
                account['account_number_masked'] = "Error"

            status_code = account['verification_status']
            account['status_display'] = status_map.get(status_code, {'label': 'Unknown', 'class': 'secondary'})
            account['can_activate'] = (status_code == 1 and not account['is_frozen'])
            account['banking_method'] = account.get('ifsc_code') or account.get('swift_code') or 'International'
            formatted_accounts.append(account)
            
        return render_template(
            'creator_bank_accounts_list.html',
            bank_accounts=formatted_accounts,
            total_accounts=len(formatted_accounts)
        )
        
    except Exception as e:
        secure_log(f"Error fetching bank accounts: {str(e)}", 'error', channel_id=channel_id)
        flash("Error loading bank accounts.", "error")
        return render_template('creator_bank_accounts_list.html', bank_accounts=[], total_accounts=0)


@creator_bp.route('/creator/bank_accounts/add/', methods=['GET', 'POST'])
@login_required
@limiter.limit("5 per minute")
def add_bank_account():
    """Add a new bank account"""
    channel_id = session.get('channel_id')
    
    if request.method == 'POST':
        try:
            account_holder_name = request.form.get('account_holder_name', '').strip()
            bank_name = request.form.get('bank_name', '').strip()
            branch_name = request.form.get('branch_name', '').strip()
            account_number = request.form.get('account_number', '').strip()
            account_type = request.form.get('account_type', 'savings')
            
            ifsc_code = request.form.get('ifsc_code', '').strip() or None
            swift_code = request.form.get('swift_code', '').strip() or None
            iban = request.form.get('iban', '').strip() or None
            routing_number = request.form.get('routing_number', '').strip() or None
            sort_code = request.form.get('sort_code', '').strip() or None
            bsb_number = request.form.get('bsb_number', '').strip() or None
            
            bank_address = request.form.get('bank_address', '').strip() or None
            account_holder_address = request.form.get('account_holder_address', '').strip()
            country_code = request.form.get('country_code', 'IND').strip()
            currency_code = request.form.get('currency_code', 'INR').strip()
            
            raw_id_type = request.form.get('id_type', '').strip().lower()
            valid_id_types = ['aadhaar', 'pan', 'passport', 'driving_license', 'voter_id', 'other']
            id_type = raw_id_type if raw_id_type in valid_id_types else 'other'
            id_number = request.form.get('id_number', '').strip()
            
            if not account_holder_name or not bank_name or not account_number or not account_holder_address:
                flash("Please fill in all required fields.", "error")
                return redirect(url_for('creator.add_bank_account'))
            
            # Encrypt sensitive data
            encrypted_account_number = encrypt_token(account_number)
            encrypted_id_number = encrypt_token(id_number)
            
            if not encrypted_account_number or not encrypted_id_number:
                secure_log("Encryption failed for bank details", 'error', channel_id=channel_id)
                flash("System error securing data.", "error")
                return redirect(url_for('creator.add_bank_account'))
            
            id_image_file = request.files.get('id_image')
            bank_document_file = request.files.get('bank_document')
            
            # Upload files (assumes save_encrypted_bank_document is defined in your helpers)
            id_image_path, _ = save_encrypted_bank_document(id_image_file, channel_id, f'id_image_{int(time.time())}')
            bank_document_path, _ = save_encrypted_bank_document(bank_document_file, channel_id, f'bank_statement_{int(time.time())}')
            
            if not id_image_path or not bank_document_path:
                flash("Failed to upload documents.", "error")
                return redirect(url_for('creator.add_bank_account'))
            
            execute_query("""
                INSERT INTO creator_base.creator_bank_info (
                    channel_id, account_holder_name, bank_name, branch_name,
                    account_number, account_type, ifsc_code, swift_code, iban,
                    routing_number, sort_code, bsb_number, bank_address,
                    account_holder_address, country_code, currency_code,
                    id_type, id_number, id_image_path, bank_document_path,
                    created_by, verification_status, is_active
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, 0)
            """, (
                channel_id, account_holder_name, bank_name, branch_name,
                encrypted_account_number, account_type, ifsc_code, swift_code, iban,
                routing_number, sort_code, bsb_number, bank_address,
                account_holder_address, country_code, currency_code,
                id_type, encrypted_id_number, id_image_path, bank_document_path,
                channel_id
            ), commit=True)
            
            flash("Bank account added successfully!", "success")
            return redirect(url_for('creator.view_bank_accounts'))
                
        except Exception as e:
            secure_log(f"Error adding bank account: {str(e)}", 'error', channel_id=channel_id)
            flash("An error occurred.", "error")
            return redirect(url_for('creator.add_bank_account'))
    
    return render_template('creator_add_bank_account.html')


@creator_bp.route('/creator/bank_accounts/<int:account_id>/')
@login_required
@limiter.limit("10 per minute")
def view_bank_account_details(account_id):
    """View full details of a specific bank account"""
    channel_id = session.get('channel_id')
    
    try:
        bank_account = execute_query("""
            SELECT * FROM creator_base.creator_bank_info
            WHERE id = %s AND channel_id = %s
        """, (account_id, channel_id), fetch_one=True)
        
        if not bank_account:
            flash("Bank account not found.", "error")
            return redirect(url_for('creator.view_bank_accounts'))
        
        bank_account = dict(bank_account)
        
        # DECRYPTION
        decrypted_acc = decrypt_token(bank_account['account_number'])
        decrypted_id = decrypt_token(bank_account['id_number'])
        
        bank_account['account_number'] = decrypted_acc if decrypted_acc else '**** (Error)'
        bank_account['id_number'] = decrypted_id if decrypted_id else '**** (Error)'
        
        status_map = {
            0: {'label': 'Pending Verification', 'class': 'warning', 'icon': 'clock'},
            1: {'label': 'Verified', 'class': 'success', 'icon': 'check-circle'},
            2: {'label': 'Rejected', 'class': 'danger', 'icon': 'x-circle'},
            3: {'label': 'Under Review', 'class': 'info', 'icon': 'info'}
        }
        
        status_code = bank_account['verification_status']
        bank_account['status_display'] = status_map.get(status_code, {'label': 'Unknown', 'class': 'secondary', 'icon': 'help-circle'})
        bank_account['can_activate'] = (status_code == 1 and not bank_account['is_frozen'])
        bank_account['can_receive_payment'] = (status_code == 1 and bank_account['is_active'] and not bank_account['is_frozen'])
        
        return render_template('creator_bank_account_details.html', account=bank_account)
        
    except Exception as e:
        secure_log(f"Error fetching bank account details: {str(e)}", 'error')
        return redirect(url_for('creator.view_bank_accounts'))


@creator_bp.route('/creator/bank_accounts/<int:account_id>/toggle_active/', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def toggle_bank_account_active(account_id):
    """
    Toggle bank account active status.
    TiDB Compatible: Replaced ToggleCreatorBankAccount stored procedure
    with Python transaction logic.
    Logic: Activates selected account & deactivates all others.
    Prevents deactivating the only active account.
    """
    channel_id = session.get('channel_id')

    try:
        with get_db_connection() as (conn, cursor):
            # 1. Get the target account
            cursor.execute("""
                SELECT id, verification_status, is_active, is_frozen
                FROM creator_base.creator_bank_info
                WHERE id = %s AND channel_id = %s
            """, (account_id, channel_id))
            account = cursor.fetchone()

            if not account:
                return jsonify({'success': False, 'message': 'Bank account not found.'}), 404

            # 2. Safety checks
            if account['is_frozen']:
                return jsonify({'success': False, 'message': 'This account is frozen. Contact support.'}), 403

            if account['verification_status'] != 1:
                return jsonify({'success': False, 'message': 'Only verified accounts can be toggled.'}), 400

            current_active = bool(account['is_active'])

            # 3. If deactivating — prevent deactivating the only active account
            if current_active:
                cursor.execute("""
                    SELECT COUNT(*) AS active_count
                    FROM creator_base.creator_bank_info
                    WHERE channel_id = %s AND is_active = 1 AND verification_status = 1
                """, (channel_id,))
                count_row = cursor.fetchone()
                if count_row and count_row['active_count'] <= 1:
                    return jsonify({
                        'success': False,
                        'message': 'Cannot deactivate your only active payment method.'
                    }), 400

                # Deactivate this account
                cursor.execute(
                    "UPDATE creator_base.creator_bank_info SET is_active = 0 WHERE id = %s",
                    (account_id,)
                )
                conn.commit()
                new_status = False
            else:
                # 4. Activating — deactivate all others, activate this one
                cursor.execute("""
                    UPDATE creator_base.creator_bank_info
                    SET is_active = 0
                    WHERE channel_id = %s AND id != %s
                """, (channel_id, account_id))

                cursor.execute(
                    "UPDATE creator_base.creator_bank_info SET is_active = 1 WHERE id = %s",
                    (account_id,)
                )
                conn.commit()
                new_status = True

        action = 'activated' if new_status else 'deactivated'
        secure_log(f"Bank account {account_id} {action}", 'info', channel_id=channel_id)

        return jsonify({
            'success': True,
            'message': f'Bank account {action} successfully.',
            'new_status': new_status,
            'status_display': 'Active' if new_status else 'Inactive'
        })

    except Exception as e:
        secure_log(f"Error toggling bank account status: {str(e)}", 'error', channel_id=channel_id)
        return jsonify({
            'success': False,
            'message': 'Failed to update account status. Please try again.'
        }), 500


@creator_bp.route('/creator/bank_accounts/<int:account_id>/delete/', methods=['POST'])
@login_required
@limiter.limit("5 per hour")
def delete_bank_account(account_id):
    """Delete (soft delete) a bank account"""
    channel_id = session.get('channel_id')
    
    try:
        account = execute_query("""
            SELECT is_active FROM creator_base.creator_bank_info
            WHERE id = %s AND channel_id = %s
        """, (account_id, channel_id), fetch_one=True)
        
        if not account:
            return jsonify({
                'success': False,
                'message': 'Bank account not found or access denied.'
            }), 404
        
        if account['is_active']:
            return jsonify({
                'success': False,
                'message': 'Cannot delete an active account. Please deactivate it first.'
            }), 400
        
        execute_query("""
            DELETE FROM creator_base.creator_bank_info
            WHERE id = %s AND channel_id = %s
        """, (account_id, channel_id), commit=True)
        
        secure_log(f"Bank account {account_id} deleted", 'info', channel_id=channel_id)
        
        return jsonify({
            'success': True,
            'message': 'Bank account removed successfully. Encrypted files remain for audit purposes.'
        })
        
    except Exception as e:
        secure_log(f"Error deleting bank account: {str(e)}", 'error', channel_id=channel_id)
        return jsonify({
            'success': False,
            'message': 'Failed to delete bank account. Please try again.'
        }), 500


@creator_bp.route('/creator/bank_accounts/<int:account_id>/documents/<doc_type>/')
@login_required
@limiter.limit("10 per minute")
def view_bank_account_document(account_id, doc_type):
    """View uploaded bank documents (ID image or bank statement)"""
    channel_id = session.get('channel_id')
    
    try:
        if doc_type == 'id_image':
            result = execute_query("""
                SELECT id_image_path, id_type, channel_id
                FROM creator_base.creator_bank_info
                WHERE id = %s
            """, (account_id,), fetch_one=True)
        elif doc_type == 'bank_statement':
            result = execute_query("""
                SELECT bank_document_path, channel_id
                FROM creator_base.creator_bank_info
                WHERE id = %s
            """, (account_id,), fetch_one=True)
        else:
            flash("Invalid document type.", "error")
            return redirect(url_for('creator.view_bank_accounts'))
        
        if not result:
            flash("Document not found.", "error")
            return redirect(url_for('creator.view_bank_accounts'))
        
        # Security check
        if result['channel_id'] != channel_id:
            secure_log(f"Unauthorized document access attempt for account {account_id}", 'warning', channel_id=channel_id)
            flash("Unauthorized access.", "error")
            return redirect(url_for('creator.view_bank_accounts'))
        
        doc_path = result.get('id_image_path' if doc_type == 'id_image' else 'bank_document_path')
        
        if not doc_path:
            flash("Document not uploaded yet.", "warning")
            return redirect(url_for('creator.view_bank_account_details', account_id=account_id))
        
        # Load and decrypt file using centralized function
        decrypted_data = download_file_content(doc_path, decrypt=True)
        
        if not decrypted_data:
            secure_log(f"Failed to load/decrypt document for account {account_id}", 'error', channel_id=channel_id)
            flash("Error accessing document. Please contact support.", "error")
            return redirect(url_for('creator.view_bank_account_details', account_id=account_id))
        
        # Detect file type from magic numbers
        header = decrypted_data[:4]
        
        if header.startswith(b'%PDF'):
            mimetype = 'application/pdf'
            ext = 'pdf'
        elif header.startswith(b'\x89PNG'):
            mimetype = 'image/png'
            ext = 'png'
        elif header.startswith(b'\xff\xd8'):
            mimetype = 'image/jpeg'
            ext = 'jpg'
        elif header[:3] == b'GIF':
            mimetype = 'image/gif'
            ext = 'gif'
        else:
            if 'id_image' in doc_type:
                mimetype = 'image/jpeg'
                ext = 'jpg'
            else:
                mimetype = 'application/pdf'
                ext = 'pdf'

        download_name = f"{doc_type}.{ext}"
        
        return send_file(
            io.BytesIO(decrypted_data),
            mimetype=mimetype,
            as_attachment=False,
            download_name=download_name
        )
            
    except Exception as e:
        secure_log(f"Error viewing bank account document: {str(e)}", 'error', channel_id=channel_id)
        flash("Error accessing document.", "error")
        return redirect(url_for('creator.view_bank_account_details', account_id=account_id))


@creator_bp.route('/creator/bank_accounts/<int:account_id>/update/', methods=['GET', 'POST'])
@login_required
@limiter.limit("8 per hour")
def update_bank_account(account_id):
    """Update existing bank account details"""
    channel_id = session.get('channel_id')
    
    if request.method == 'POST':
        try:
            # Check ownership
            account = execute_query("""
                SELECT id FROM creator_base.creator_bank_info
                WHERE id = %s AND channel_id = %s
            """, (account_id, channel_id), fetch_one=True)
            
            if not account:
                flash("Bank account not found.", "error")
                return redirect(url_for('creator.view_bank_accounts'))
            
            # Extract basic data
            account_holder_name = request.form.get('account_holder_name', '').strip()
            bank_name = request.form.get('bank_name', '').strip()
            branch_name = request.form.get('branch_name', '').strip()
            account_type = request.form.get('account_type', 'savings')
            
            ifsc_code = request.form.get('ifsc_code', '').strip() or None
            swift_code = request.form.get('swift_code', '').strip() or None
            iban = request.form.get('iban', '').strip() or None
            routing_number = request.form.get('routing_number', '').strip() or None
            sort_code = request.form.get('sort_code', '').strip() or None
            bsb_number = request.form.get('bsb_number', '').strip() or None
            
            bank_address = request.form.get('bank_address', '').strip() or None
            account_holder_address = request.form.get('account_holder_address', '').strip()
            country_code = request.form.get('country_code', 'IND').strip()
            currency_code = request.form.get('currency_code', 'INR').strip()
            
            if not account_holder_name or not bank_name:
                flash("Please fill in required fields.", "error")
                return redirect(url_for('creator.update_bank_account', account_id=account_id))
            
            execute_query("""
                UPDATE creator_base.creator_bank_info
                SET account_holder_name = %s, bank_name = %s, branch_name = %s,
                    account_type = %s, ifsc_code = %s, swift_code = %s, iban = %s,
                    routing_number = %s, sort_code = %s, bsb_number = %s,
                    bank_address = %s, account_holder_address = %s, country_code = %s,
                    currency_code = %s, verification_status = 0, is_active = 0,
                    updated_by = %s, updated_at = NOW()
                WHERE id = %s AND channel_id = %s
            """, (
                account_holder_name, bank_name, branch_name, account_type,
                ifsc_code, swift_code, iban, routing_number, sort_code, bsb_number,
                bank_address, account_holder_address, country_code, currency_code,
                channel_id, account_id, channel_id
            ), commit=True)
            
            flash("Bank account updated successfully! Re-verification required.", "success")
            return redirect(url_for('creator.view_bank_account_details', account_id=account_id))
            
        except Exception as e:
            secure_log(f"Error updating bank account: {str(e)}", 'error', channel_id=channel_id)
            flash("Failed to update bank account.", "error")
            return redirect(url_for('creator.update_bank_account', account_id=account_id))
    
    # GET request
    try:
        bank_account = execute_query("""
            SELECT * FROM creator_base.creator_bank_info
            WHERE id = %s AND channel_id = %s
        """, (account_id, channel_id), fetch_one=True)
        
        if not bank_account:
            return redirect(url_for('creator.view_bank_accounts'))
        
        bank_account = dict(bank_account)

        # DECRYPTION: Full decrypted account number for editing
        decrypted_acc_num = decrypt_token(bank_account['account_number'])
        if decrypted_acc_num:
            bank_account['account_number_decrypted'] = decrypted_acc_num
            bank_account['account_number_masked'] = '****' + decrypted_acc_num[-4:]
        else:
            bank_account['account_number_decrypted'] = ''
            bank_account['account_number_masked'] = '****'

        # Decrypt ID number for editing
        decrypted_id_num = decrypt_token(bank_account['id_number'])
        if decrypted_id_num:
            bank_account['id_number_decrypted'] = decrypted_id_num
            bank_account['id_number_masked'] = '****' + decrypted_id_num[-4:]
        else:
            bank_account['id_number_decrypted'] = ''
            bank_account['id_number_masked'] = '****'

        return render_template('creator_update_bank_account.html', account=bank_account)
        
    except Exception as e:
        secure_log(f"Error loading bank account: {str(e)}", 'error')
        return redirect(url_for('creator.view_bank_accounts'))

        
