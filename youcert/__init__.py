"""
==============================================================================
YOUCERT __init__.py - DATABASE OTP VERSION (UPGRADED v14.0)
==============================================================================

This is the central initialization file for the YOUCERT Flask application.
It provides unified interfaces that work in BOTH environments:
  - LOCAL DEVELOPMENT (Windows/Linux/Mac)
  - CLOUDFLARE CONTAINERS (Production)

UPGRADED FEATURES v14.0:
    - DATABASE-LEVEL OTP STORAGE - Multi-instance ready
    - Multi-instance ready - OTPs stored in MySQL, accessible across all instances
    - NO REDIS DEPENDENCY - Uses SimpleCache and database storage
    - Client-side Sessions - Signed cookies instead of server-side storage
    - Fixed cursor_class error - Proper database connection context manager
    - Cost Savings - $50-150/month saved (no Memorystore)
    - GEVENT MONKEY PATCHING - For high concurrency (70+ requests per instance)

CLOUDFLARE SERVICES INTEGRATED:
    Cloudflare R2            - S3-compatible file storage
    Cloudflare Queues        - Background job processing
    Cloudflare Logpush       - Structured log capture from stdout/stderr
    Workers Secrets          - Secure env vars
    Gemini API               - AI processing via REST

AUTHENTICATION & CONFIGURATION:
  - Production: Workers Secrets as environment variables
  - Local Dev: Configurable via .env file

==============================================================================
"""

# ==============================================================================
# GEVENT MONKEY PATCHING - MUST BE FIRST (before any other import)
# ==============================================================================
# gevent patches stdlib (socket, ssl, select) for greenlet-based concurrency:
# 120+ concurrent requests per container instance with a single worker process.
# thread=False: required for Flask-MySQLdb / mysqlclient compatibility.
import os
import sys

# Enable line-buffered output so Cloudflare log capture sees prints immediately
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

print("[init] Step 1: stdlib pre-imports OK", flush=True)

if os.getenv('IS_DEVELOPMENT', 'False').lower() != 'true' or os.getenv('GEVENT_SUPPORT') == 'True':
    from gevent import monkey as _gmonkey
    # Only patch if not already patched — wsgi.py patches first in production.
    # Gevent docs: patching twice causes unpredictable LoopExit errors.
    if not _gmonkey.is_module_patched('socket'):
        _gmonkey.patch_all(thread=False)
        print("[init] Step 1: gevent monkey-patching applied", flush=True)
    else:
        print("[init] Step 1: gevent already patched (by wsgi.py) — skipping", flush=True)
else:
    print("[init] Step 1: gevent skipped (local dev mode)", flush=True)

print("[init] Step 2: importing pymysql...", flush=True)
import pymysql
pymysql.install_as_MySQLdb()
print("[init] Step 2: pymysql installed as MySQLdb", flush=True)


# ==============================================================================
# STANDARD LIBRARY IMPORTS
# ==============================================================================
print("[init] Step 3: importing stdlib...", flush=True)
import io
import json
import logging
import hashlib
import re
import time
import random
from datetime import datetime, timedelta
from contextlib import contextmanager
from functools import lru_cache
from typing import Optional, Dict, Any, Tuple
print("[init] Step 3: stdlib done", flush=True)

# ==============================================================================
# FLASK AND EXTENSIONS
# ==============================================================================
print("[init] Step 4: importing flask...", flush=True)
from flask import Flask, current_app, session, request, send_from_directory, g, abort, jsonify
print("[init] Step 4a: flask core done", flush=True)
from flask_mysqldb import MySQL
print("[init] Step 4b: flask_mysqldb done", flush=True)
from flask_wtf.csrf import CSRFProtect
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
print("[init] Step 4c: flask extensions done (CORS/CSRF/Limiter/Cache)", flush=True)
from cryptography.fernet import Fernet
print("[init] Step 4d: cryptography done", flush=True)
import MySQLdb
import MySQLdb.cursors
print("[init] Step 4e: MySQLdb native driver done", flush=True)

# ==============================================================================
# LOCAL IMPORTS
# ==============================================================================
print("[init] Step 5: importing config...", flush=True)
from config import Config
# Log config status WITHOUT exposing secret values
print(f"[init] Step 5: config loaded — "
      f"IS_DEVELOPMENT={Config.IS_DEVELOPMENT}, "
      f"IS_TIDB={Config.IS_TIDB}, "
      f"SECRET_KEY={'SET' if getattr(Config, 'SECRET_KEY', None) else 'MISSING'}, "
      f"MYSQL_HOST={'SET' if getattr(Config, 'MYSQL_HOST', None) else 'MISSING'}",
      flush=True)

# ==============================================================================
# FLASK EXTENSIONS INITIALIZATION
# ==============================================================================
print("[init] Step 6: initializing extension objects...", flush=True)
mysql = MySQL()
csrf = CSRFProtect()
cache = Cache()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per minute", "5000 per hour"],
    storage_uri="memory://"
)
print("[init] Step 6: extension objects created (not yet init_app'd)", flush=True)

# ##############################################################################
#
#                    SECTION 1: ENVIRONMENT DETECTION
#
# ##############################################################################

def is_cloud_run() -> bool:
    """
    Check if running in Cloudflare Containers (production).
    Kept as is_cloud_run() for backward compatibility across route files.

    Returns:
        bool: True if running in Cloudflare production
    """
    return Config.IS_CLOUDFLARE

def is_production() -> bool:
    """
    Check if running in production mode.
    
    Production is defined as:
    - Running in Cloudflare Containers, OR
    - FLASK_ENV set to 'production'
    
    Returns:
        bool: True if production environment
    """
    return is_cloud_run() or Config.FLASK_ENV == 'production'

def is_windows() -> bool:
    """
    Check if running on Windows.

    Useful for path handling and encoding fixes.

    Returns:
        bool: True if Windows
    """
    return os.name == 'nt'

def get_base_url() -> str:
    """
    Get the base URL for the application.

    Auto-detects from Flask request if available, otherwise uses Config.BASE_URL.
    This ensures certificates and emails use the correct domain even when
    a custom domain is added without updating environment variables.

    Priority:
    1. Flask request URL (auto-detects custom domains)
    2. SERVICE_URL environment variable
    3. Config.BASE_URL fallback

    Returns:
        str: Base URL (e.g., 'https://www.youcert.com' or 'http://127.0.0.1:5000')

    Examples:
        Development: 'http://127.0.0.1:5000'
        Cloudflare default: 'https://youcert.com'
        Custom domain: 'https://www.youcert.com' (auto-detected)
    """
    try:
        # Try to get from current Flask request context
        from flask import request, has_request_context

        if has_request_context():
            # Auto-detect from request (works with custom domains!)
            scheme = request.scheme  # 'http' or 'https'
            host = request.host  # 'www.youcert.com' or 'localhost:5000'
            base_url = f"{scheme}://{host}"
            return base_url
    except (RuntimeError, ImportError):
        # No request context available (e.g., background task)
        pass

    # Fallback to Config.BASE_URL
    return Config.BASE_URL

def get_project_id() -> Optional[str]:
    """
    Get Google Cloud Project ID from Config.
    GCP metadata server calls removed — Project ID comes from Config only.
    """
    return getattr(Config, 'GOOGLE_PROJECT_ID', None)

# ##############################################################################
#
#                    SECTION 2: DATABASE-LEVEL OTP STORAGE (NEW v14.0)
#
# ##############################################################################

def save_otp_to_database(user_type: str, email: str, otp_code: str, 
                         purpose: str = 'login', expiry_seconds: int = 600,
                         ip_address: str = None) -> bool:
    """
    Save OTP to database instead of filesystem.
    
    Args:
        user_type: 'admin', 'creator', or 'user'
        email: Email address
        otp_code: The OTP code (6 digits)
        purpose: Purpose of OTP (login, registration, first_time_setup, etc)
        expiry_seconds: How long OTP is valid (default 600 = 10 minutes)
        ip_address: IP address that requested the OTP
    
    Returns:
        bool: True if successful
    """
    try:
        # Delete any existing OTP for this user/purpose
        execute_query(
            """
            DELETE FROM admin_base.otp_tokens 
            WHERE user_type = %s AND email = %s AND purpose = %s
            """,
            (user_type, email, purpose),
            commit=True
        )
        
        # Insert new OTP
        expires_at = datetime.now() + timedelta(seconds=expiry_seconds)
        
        execute_query(
            """
            INSERT INTO admin_base.otp_tokens 
            (user_type, email, otp_code, purpose, expires_at, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (user_type, email, otp_code, purpose, expires_at, ip_address),
            commit=True
        )
        
        secure_log(
            f"OTP saved to database",
            'info',
            user_type=user_type,
            email=email[:20] + '...' if len(email) > 20 else email,
            purpose=purpose,
            expiry_seconds=expiry_seconds
        )
        return True
        
    except Exception as e:
        secure_log(
            f"Failed to save OTP to database: {e}",
            'error',
            user_type=user_type,
            email=email,
            purpose=purpose
        )
        return False

def get_otp_from_database(user_type: str, email: str, purpose: str = 'login') -> Optional[str]:
    """
    Retrieve OTP from database.
    
    Args:
        user_type: 'admin', 'creator', or 'user'
        email: Email address
        purpose: Purpose of OTP
    
    Returns:
        str or None: OTP code if valid and not expired, None otherwise
    """
    try:
        result = execute_query(
            """
            SELECT otp_code, expires_at, verified 
            FROM admin_base.otp_tokens
            WHERE user_type = %s AND email = %s AND purpose = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (user_type, email, purpose),
            fetch_one=True
        )
        
        if not result:
            secure_log(
                f"OTP not found in database",
                'debug',
                user_type=user_type,
                email=email,
                purpose=purpose
            )
            return None
        
        # Check if already verified
        if result['verified']:
            secure_log(
                f"OTP already verified",
                'info',
                user_type=user_type,
                email=email,
                purpose=purpose
            )
            return None
        
        # Check expiry
        if datetime.now() > result['expires_at']:
            secure_log(
                f"OTP expired",
                'info',
                user_type=user_type,
                email=email,
                purpose=purpose
            )
            # Delete expired OTP
            execute_query(
                """
                DELETE FROM admin_base.otp_tokens
                WHERE user_type = %s AND email = %s AND purpose = %s
                """,
                (user_type, email, purpose),
                commit=True
            )
            return None
        
        secure_log(
            f"OTP retrieved from database",
            'debug',
            user_type=user_type,
            email=email,
            purpose=purpose
        )
        return result['otp_code']
        
    except Exception as e:
        secure_log(
            f"Failed to retrieve OTP from database: {e}",
            'error',
            user_type=user_type,
            email=email,
            purpose=purpose
        )
        return None

def verify_otp_from_database(user_type: str, email: str, otp_code: str, 
                             purpose: str = 'login') -> bool:
    """
    Verify OTP from database and mark as verified if correct.
    
    Args:
        user_type: 'admin', 'creator', or 'user'
        email: Email address
        otp_code: OTP code to verify
        purpose: Purpose of OTP
    
    Returns:
        bool: True if OTP is correct and not expired
    """
    try:
        stored_otp = get_otp_from_database(user_type, email, purpose)
        
        if not stored_otp:
            secure_log(
                f"OTP verification failed - not found or expired",
                'warning',
                user_type=user_type,
                email=email,
                purpose=purpose
            )
            return False
        
        if stored_otp == otp_code:
            # Mark as verified
            execute_query(
                """
                UPDATE admin_base.otp_tokens 
                SET verified = TRUE
                WHERE user_type = %s AND email = %s AND purpose = %s AND otp_code = %s
                """,
                (user_type, email, purpose, otp_code),
                commit=True
            )
            
            secure_log(
                f"OTP verified successfully",
                'info',
                user_type=user_type,
                email=email,
                purpose=purpose
            )
            return True
        
        secure_log(
            f"OTP verification failed - incorrect code",
            'warning',
            user_type=user_type,
            email=email,
            purpose=purpose
        )
        return False
        
    except Exception as e:
        secure_log(
            f"Failed to verify OTP: {e}",
            'error',
            user_type=user_type,
            email=email,
            purpose=purpose
        )
        return False

def delete_otp_from_database(user_type: str, email: str, purpose: str = 'login') -> bool:
    """
    Delete OTP from database.
    
    Args:
        user_type: 'admin', 'creator', or 'user'
        email: Email address
        purpose: Purpose of OTP
    
    Returns:
        bool: True if successful
    """
    try:
        execute_query(
            """
            DELETE FROM admin_base.otp_tokens
            WHERE user_type = %s AND email = %s AND purpose = %s
            """,
            (user_type, email, purpose),
            commit=True
        )
        
        secure_log(
            f"OTP deleted from database",
            'info',
            user_type=user_type,
            email=email,
            purpose=purpose
        )
        return True
        
    except Exception as e:
        secure_log(
            f"Failed to delete OTP from database: {e}",
            'error',
            user_type=user_type,
            email=email,
            purpose=purpose
        )
        return False

def cleanup_expired_tokens_db() -> Dict[str, int]:
    """
    Clean up expired OTPs and password reset tokens from database.
    
    Returns:
        dict: Statistics about deleted records
    """
    try:
        # Delete expired OTPs
        otp_result = execute_query(
            "DELETE FROM admin_base.otp_tokens WHERE expires_at < NOW()",
            commit=True
        )
        
        # Delete expired password reset tokens
        token_result = execute_query(
            "DELETE FROM admin_base.password_reset_tokens WHERE expires_at < NOW()",
            commit=True
        )
        
        # Delete verified OTPs older than 24 hours
        execute_query(
            """
            DELETE FROM admin_base.otp_tokens 
            WHERE verified = TRUE AND created_at < DATE_SUB(NOW(), INTERVAL 24 HOUR)
            """,
            commit=True
        )
        
        # Delete used tokens older than 24 hours
        execute_query(
            """
            DELETE FROM admin_base.password_reset_tokens 
            WHERE used = TRUE AND created_at < DATE_SUB(NOW(), INTERVAL 24 HOUR)
            """,
            commit=True
        )
        
        secure_log("Database token cleanup completed", 'info')
        
        return {
            'otps_deleted': 1 if otp_result else 0,
            'tokens_deleted': 1 if token_result else 0
        }
        
    except Exception as e:
        secure_log(f"Failed to cleanup expired tokens: {e}", 'error')
        return {'otps_deleted': 0, 'tokens_deleted': 0}

# ##############################################################################
#
#                    SECTION 3: PASSWORD RESET TOKEN MANAGEMENT (DATABASE)
#
# ##############################################################################

def save_password_reset_token_db(user_type: str, email: str, token_hash: str,
                                 expiry_seconds: int = 3600, ip_address: str = None) -> bool:
    """
    Save password reset token to database.
    
    Args:
        user_type: 'admin', 'creator', or 'user'
        email: Email address
        token_hash: Hashed reset token
        expiry_seconds: How long token is valid (default 3600 = 1 hour)
        ip_address: IP address that requested the reset
    
    Returns:
        bool: True if successful
    """
    try:
        expires_at = datetime.now() + timedelta(seconds=expiry_seconds)
        
        execute_query(
            """
            INSERT INTO admin_base.password_reset_tokens 
            (user_type, email, token_hash, expires_at, ip_address)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_type, email, token_hash, expires_at, ip_address),
            commit=True
        )
        
        secure_log(
            f"Password reset token saved to database",
            'info',
            user_type=user_type,
            email=email[:20] + '...' if len(email) > 20 else email
        )
        return True
        
    except Exception as e:
        secure_log(
            f"Failed to save password reset token: {e}",
            'error',
            user_type=user_type,
            email=email
        )
        return False

def get_password_reset_token_db(token_hash: str) -> Optional[Dict]:
    """
    Get password reset token from database.
    
    Args:
        token_hash: Hashed token
    
    Returns:
        dict or None: Token data if valid
    """
    try:
        result = execute_query(
            """
            SELECT user_type, email, expires_at, used
            FROM admin_base.password_reset_tokens
            WHERE token_hash = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (token_hash,),
            fetch_one=True
        )
        
        if not result:
            return None
        
        # Check if already used
        if result['used']:
            return None
        
        # Check expiry
        if datetime.now() > result['expires_at']:
            return None
        
        return result
        
    except Exception as e:
        secure_log(f"Failed to get password reset token: {e}", 'error')
        return None

def validate_password_reset_token_db(token_hash: str) -> bool:
    """
    Validate password reset token.
    
    Args:
        token_hash: Hashed token
    
    Returns:
        bool: True if valid
    """
    return get_password_reset_token_db(token_hash) is not None

def delete_password_reset_token_db(token_hash: str) -> bool:
    """
    Mark password reset token as used.
    
    Args:
        token_hash: Hashed token
    
    Returns:
        bool: True if successful
    """
    try:
        execute_query(
            """
            UPDATE admin_base.password_reset_tokens 
            SET used = TRUE
            WHERE token_hash = %s
            """,
            (token_hash,),
            commit=True
        )
        
        secure_log("Password reset token marked as used", 'info')
        return True
        
    except Exception as e:
        secure_log(f"Failed to mark token as used: {e}", 'error')
        return False

# ##############################################################################
#
#                    SECTION 4: CLOUDFLARE R2 STORAGE
#
# ##############################################################################

_r2_client = None  # boto3 S3-compatible client for Cloudflare R2

# ##############################################################################
#
#                    DATABASE-BASED LOCKOUT MANAGEMENT (NEW v15.0)
#
# ##############################################################################

def save_login_lockout_db(email: str, user_type: str, lockout_until: datetime, 
                           ip_address: str = None) -> bool:
    """
    Save login lockout to database.
    
    Args:
        email: User email
        user_type: 'admin', 'creator', or 'user'
        lockout_until: When lockout expires
        ip_address: IP address of the failed attempts
    
    Returns:
        bool: True if successful
    """
    try:
        # Delete any existing lockout
        execute_query(
            """
            DELETE FROM admin_base.login_lockouts
            WHERE email = %s AND user_type = %s
            """,
            (email, user_type),
            commit=True
        )
        
        # Insert new lockout
        execute_query(
            """
            INSERT INTO admin_base.login_lockouts 
            (email, user_type, locked_until, ip_address)
            VALUES (%s, %s, %s, %s)
            """,
            (email, user_type, lockout_until, ip_address),
            commit=True
        )
        
        secure_log(
            f"Login lockout saved for {user_type}",
            'warning',
            email=email[:20] + '...' if len(email) > 20 else email,
            locked_until=lockout_until.isoformat()
        )
        return True
        
    except Exception as e:
        secure_log(f"Failed to save lockout: {e}", 'error', email=email)
        return False


def get_login_lockout_db(email: str, user_type: str) -> Optional[datetime]:
    """
    Get login lockout expiry time from database.
    
    Args:
        email: User email
        user_type: 'admin', 'creator', or 'user'
    
    Returns:
        datetime or None: Lockout expiry time if locked
    """
    try:
        result = execute_query(
            """
            SELECT locked_until 
            FROM admin_base.login_lockouts
            WHERE email = %s AND user_type = %s 
            AND locked_until > NOW()
            ORDER BY locked_until DESC
            LIMIT 1
            """,
            (email, user_type),
            fetch_one=True
        )
        
        if result:
            return result['locked_until']
        return None
        
    except Exception as e:
        secure_log(f"Failed to get lockout: {e}", 'error')
        return None


def delete_login_lockout_db(email: str, user_type: str) -> bool:
    """
    Delete login lockout from database.
    
    Args:
        email: User email
        user_type: 'admin', 'creator', or 'user'
    
    Returns:
        bool: True if successful
    """
    try:
        execute_query(
            """
            DELETE FROM admin_base.login_lockouts
            WHERE email = %s AND user_type = %s
            """,
            (email, user_type),
            commit=True
        )
        
        secure_log(f"Login lockout deleted for {user_type}", 'info', email=email)
        return True
        
    except Exception as e:
        secure_log(f"Failed to delete lockout: {e}", 'error')
        return False


def increment_failed_login_db(email: str, user_type: str, max_attempts: int = 5,
                               lockout_minutes: int = 30, ip_address: str = None) -> Tuple[int, bool]:
    """
    Increment failed login counter and lock account if threshold reached.
    
    Args:
        email: User email
        user_type: 'admin', 'creator', or 'user'
        max_attempts: Maximum failed attempts before lockout (default 5)
        lockout_minutes: Lockout duration in minutes (default 30)
        ip_address: IP address of the failed attempt
    
    Returns:
        Tuple[int, bool]: (current_attempts, is_locked)
    """
    try:
        # Get current failed attempts
        result = execute_query(
            """
            SELECT attempts, last_attempt_at
            FROM admin_base.failed_login_attempts
            WHERE email = %s AND user_type = %s
            ORDER BY last_attempt_at DESC
            LIMIT 1
            """,
            (email, user_type),
            fetch_one=True
        )
        
        current_attempts = result['attempts'] + 1 if result else 1
        
        # Update or insert failed attempts
        execute_query(
            """
            INSERT INTO admin_base.failed_login_attempts 
            (email, user_type, attempts, last_attempt_at, ip_address)
            VALUES (%s, %s, %s, NOW(), %s)
            ON DUPLICATE KEY UPDATE
            attempts = %s,
            last_attempt_at = NOW(),
            ip_address = %s
            """,
            (email, user_type, current_attempts, ip_address, 
             current_attempts, ip_address),
            commit=True
        )
        
        # Check if should lock
        if current_attempts >= max_attempts:
            lockout_until = datetime.now() + timedelta(minutes=lockout_minutes)
            save_login_lockout_db(email, user_type, lockout_until, ip_address)
            
            # Clear failed attempts counter
            execute_query(
                """
                DELETE FROM admin_base.failed_login_attempts
                WHERE email = %s AND user_type = %s
                """,
                (email, user_type),
                commit=True
            )
            
            secure_log(
                f"Account locked after {max_attempts} failed attempts",
                'error',
                email=email,
                user_type=user_type
            )
            return current_attempts, True
        
        secure_log(
            f"Failed login attempt {current_attempts}/{max_attempts}",
            'warning',
            email=email,
            user_type=user_type
        )
        return current_attempts, False
        
    except Exception as e:
        secure_log(f"Failed to increment login attempts: {e}", 'error')
        return 0, False


def reset_failed_login_db(email: str, user_type: str) -> bool:
    """
    Reset failed login counter on successful login.
    
    Args:
        email: User email
        user_type: 'admin', 'creator', or 'user'
    
    Returns:
        bool: True if successful
    """
    try:
        # Delete failed attempts
        execute_query(
            """
            DELETE FROM admin_base.failed_login_attempts
            WHERE email = %s AND user_type = %s
            """,
            (email, user_type),
            commit=True
        )
        
        # Delete any lockouts
        delete_login_lockout_db(email, user_type)
        
        secure_log(f"Failed login counter reset for {user_type}", 'info', email=email)
        return True
        
    except Exception as e:
        secure_log(f"Failed to reset login counter: {e}", 'error')
        return False


def check_login_lockout_db(email: str, user_type: str) -> Tuple[bool, Optional[str]]:
    """
    Check if account is locked due to failed login attempts.
    
    Args:
        email: User email
        user_type: 'admin', 'creator', or 'user'
    
    Returns:
        Tuple[bool, Optional[str]]: (is_locked, error_message)
    """
    try:
        lockout_until = get_login_lockout_db(email, user_type)
        
        if lockout_until:
            remaining_minutes = int((lockout_until - datetime.now()).total_seconds() / 60)
            if remaining_minutes > 0:
                return True, f"Account locked. Try again in {remaining_minutes} minutes"
            else:
                # Lockout expired, clean up
                delete_login_lockout_db(email, user_type)
        
        return False, None
        
    except Exception as e:
        secure_log(f"Failed to check lockout: {e}", 'error')
        return False, None




def use_cloud_storage() -> bool:
    """Check if Cloudflare R2 cloud storage should be used."""
    return bool(getattr(Config, 'R2_ACCESS_KEY_ID', None) and getattr(Config, 'R2_ENDPOINT_URL', None))

# NOTE: No @lru_cache here — it conflicts with the global _r2_client singleton guard below
def get_r2_client():
    """Get or create boto3 R2 client (singleton, Cloudflare R2 / S3-compatible)."""
    global _r2_client
    if _r2_client is None:
        try:
            import boto3
            from botocore.config import Config as BotocoreConfig
            # Cloudflare R2 boto3 requirements (per official R2 S3 API docs):
            # - region_name MUST be 'auto' or 'us-east-1' (weur/wnam etc are NOT valid)
            # - endpoint_url must NOT have trailing slash
            # - addressing_style MUST be 'path' — 'virtual' breaks custom endpoint_url
            #   by trying to prepend bucket name as a subdomain
            endpoint = Config.R2_ENDPOINT_URL.rstrip('/') if Config.R2_ENDPOINT_URL else ''
            
            _r2_client = boto3.client(
                's3',
                endpoint_url=endpoint,
                aws_access_key_id=Config.R2_ACCESS_KEY_ID,
                aws_secret_access_key=Config.R2_SECRET_ACCESS_KEY,
                region_name='auto',
                config=BotocoreConfig(
                    signature_version='s3v4',
                    s3={'addressing_style': 'path'},
                    retries={'max_attempts': 3, 'mode': 'standard'}
                )
            )
            secure_log(f"R2 client initialized against endpoint: {endpoint}", 'info')
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            secure_log(f"Failed to initialize R2 client: {e}\n{tb}", 'error')
            print(f"CRITICAL R2 INIT FAILURE: {e}\n{tb}", flush=True)
            return None
    return _r2_client

def get_gcs_client():
    """Backward compat alias — returns R2 client."""
    return get_r2_client()

def get_gcs_bucket():
    """Backward compat stub — R2 operations use put_object/get_object directly."""
    return get_r2_client()

# ##############################################################################
#
#                    SECTION 5: CLOUDFLARE SECRETS
#
# ##############################################################################
# Cloudflare Workers Secrets are injected as plain environment variables.
# No SDK required — secrets are already available via os.environ.

def get_secret(secret_id: str, version: str = "latest") -> Optional[str]:
    """
    Stub: Cloudflare secrets are plain env vars — Secret Manager removed.
    Checks both hyphenated and underscored variants of the secret name.
    """
    return os.environ.get(secret_id) or os.environ.get(secret_id.replace('-', '_'))

def clear_secret_cache():
    """No-op: no secret cache in Cloudflare setup."""
    pass

# ##############################################################################
#
#                    SECTION 6: ENCRYPTION (Fernet — KMS Removed)
#
# ##############################################################################
# Cloud KMS removed. All encryption uses Fernet via TOKEN_ENCRYPTION_KEY env var.
# Store TOKEN_ENCRYPTION_KEY as a Cloudflare Workers Secret.

def _should_use_cloud_kms() -> bool:
    """KMS removed — always returns False. Fernet handles all encryption."""
    return False

def _get_kms_key_path() -> Optional[str]:
    """KMS removed — returns None."""
    return None

def get_kms_client():
    """KMS removed — returns None."""
    return None

# ##############################################################################
#
#                    SECTION 7: TASK QUEUE (Cloudflare Queues)
#
# ##############################################################################
# Cloud Tasks removed. Use TaskManager in youcert.logic.task_manager which
# dispatches to Cloudflare Queues via REST API in production.

def get_cloud_tasks_client():
    """Stub: Cloud Tasks removed. Use TaskManager from youcert.logic.task_manager."""
    return None

# ##############################################################################
#
#                    SECTION 8: LOGGING (Standard Python — Cloudflare Logpush)
#
# ##############################################################################
# Cloud Logging removed. Uses standard Python logging.
# Cloudflare Logpush automatically captures container stdout/stderr logs.

def get_cloud_logging_client():
    """Stub: Cloud Logging removed — Cloudflare Logpush captures container logs."""
    return None

# ##############################################################################
#
#                    SECTION 9: ENCRYPTION
#
# ##############################################################################

_cipher = None

def get_cipher():
    """Get or create Fernet cipher (singleton pattern)"""
    global _cipher
    if _cipher is None:
        if not Config.TOKEN_ENCRYPTION_KEY:
            secure_log("No encryption key configured", 'warning')
            return None
        
        try:
            key = Config.TOKEN_ENCRYPTION_KEY
            if isinstance(key, str):
                key = key.encode()
            _cipher = Fernet(key)
            secure_log("Fernet cipher initialized", 'debug')
        except Exception as e:
            secure_log(f"Failed to initialize cipher: {e}", 'error')
            return None
    
    return _cipher

def encrypt_token(token: str) -> Optional[str]:
    """
    Encrypt token using Fernet symmetric encryption.
    (Cloud KMS removed — TOKEN_ENCRYPTION_KEY is a Cloudflare Workers Secret)
    """
    if not token:
        return None

    cipher = get_cipher()
    if not cipher:
        return None

    try:
        import base64
        encrypted = cipher.encrypt(token.encode('utf-8'))
        return base64.b64encode(encrypted).decode('utf-8')
    except Exception as e:
        secure_log(f"Encryption failed: {e}", 'error')
        return None

def decrypt_token(encrypted_token: str) -> Optional[str]:
    """
    Decrypt token using Fernet symmetric encryption.
    (Cloud KMS removed — TOKEN_ENCRYPTION_KEY is a Cloudflare Workers Secret)
    """
    if not encrypted_token:
        return None

    cipher = get_cipher()
    if not cipher:
        return None

    try:
        import base64
        encrypted_bytes = base64.b64decode(encrypted_token)
        decrypted = cipher.decrypt(encrypted_bytes)
        return decrypted.decode('utf-8')
    except Exception as e:
        secure_log(f"Decryption failed: {e}", 'error')
        return None


# ##############################################################################
#
#                    SECTION 10: STORAGE PATHS
#
# ##############################################################################

# Project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ==============================================================================
# UPLOADS DIRECTORY - User-uploaded files (PROJECT_X/uploads/)
# ==============================================================================
if Config.IS_CLOUDFLARE:
    # Cloudflare Containers: Use /app/uploads
    UPLOADS_BASE = '/app/uploads'
else:
    # Local: Use PROJECT_X/uploads (parent directory of youcert/)
    UPLOADS_BASE = os.path.join(PROJECT_ROOT, 'uploads')

# ==============================================================================
# STATIC DIRECTORY - Application assets only (CSS/JS/templates)
# ==============================================================================
if Config.IS_CLOUDFLARE:
    STATIC_BASE = '/app/static'
else:
    STATIC_BASE = os.path.join(PROJECT_ROOT, 'youcert', 'static')

# Storage folders
STORAGE_FOLDERS = {
    'transcripts': 'transcripts',
    'summaries': 'summaries',
    'signatures': 'signatures',
    'profiles': 'profiles',
    'profile_photos': 'profile_photos',
    'profile_pictures': 'profile_pictures',  # Alias for compatibility
    'thumbnails': 'thumbnails',
    'certificates': 'certificates',
    'bank_documents': 'bank_documents',
    'documents': 'documents',
    'uploads': 'uploads'
}

# Storage paths (using UPLOADS_BASE for user files)
STORAGE_PATHS = {
    key: os.path.join(UPLOADS_BASE, folder)
    for key, folder in STORAGE_FOLDERS.items()
}


def init_storage_directories():
    """
    Create local storage directories with videos/playlists subfolders (development only).

    In production, files go to R2, not local filesystem.
    This is only called during app initialization for local development.
    """
    if use_cloud_storage():
        return  # Production uses R2

    try:
        os.makedirs(UPLOADS_BASE, exist_ok=True)

        for folder_key, folder_path in STORAGE_PATHS.items():
            os.makedirs(folder_path, exist_ok=True)

            # Create subdirectories for videos/playlists
            if folder_key in ['transcripts', 'summaries', 'thumbnails']:
                os.makedirs(os.path.join(folder_path, 'videos'), exist_ok=True)
                os.makedirs(os.path.join(folder_path, 'playlists'), exist_ok=True)

        secure_log(f"Storage directories created: {UPLOADS_BASE}", 'info')
    except Exception as e:
        secure_log(f"Warning: Could not create storage directories: {e}", 'warning')


def get_storage_path(storage_type: str, subfolder: str = None) -> str:
    """
    Get storage path for a storage type with optional subfolder.

    Args:
        storage_type: Type of storage (transcripts, summaries, etc.)
        subfolder: Optional subfolder ('videos' or 'playlists')

    Returns:
        str: Path to storage directory

    Example:
        get_storage_path('transcripts', 'videos') -> '/uploads/transcripts/videos'
        get_storage_path('summaries', 'playlists') -> '/uploads/summaries/playlists'
    """
    if use_cloud_storage():
        # Return R2 path (used as object key prefix for boto3 operations)
        base_path = f"{STORAGE_FOLDERS.get(storage_type, storage_type)}"
        if subfolder:
            base_path = f"{base_path}/{subfolder}"
        return base_path
    else:
        # Return local path with subfolder
        path = STORAGE_PATHS.get(storage_type)
        if path:
            if subfolder:
                path = os.path.join(path, subfolder)
            os.makedirs(path, exist_ok=True)
        return path



def encrypt_bytes(data: bytes) -> Optional[bytes]:
    """
    Encrypt raw bytes using Fernet symmetric encryption.
    KMS removed — all encryption uses TOKEN_ENCRYPTION_KEY.

    Args:
        data: Raw bytes to encrypt

    Returns:
        bytes: Encrypted bytes with 'F' prefix, or None on failure
    """
    if not data:
        return None

    try:
        cipher = get_cipher()
        if cipher:
            encrypted = b'F' + cipher.encrypt(data)  # 'F' prefix for Fernet
            secure_log(f"Fernet encryption successful ({len(data)} bytes)", 'debug')
            return encrypted

        secure_log("No encryption key available (TOKEN_ENCRYPTION_KEY not set)", 'error')
        return None

    except Exception as e:
        secure_log(f"encrypt_bytes error: {e}", 'error')
        return None


def decrypt_bytes(data: bytes) -> Optional[bytes]:
    """
    Decrypt encrypted bytes using Fernet.
    KMS removed — only 'F' prefix (Fernet) is supported.
    Legacy 'D'/'E' prefix (KMS) data will log an error.

    Args:
        data: Encrypted bytes

    Returns:
        bytes: Decrypted bytes, or None on failure
    """
    if not data:
        secure_log("decrypt_bytes: No data provided", 'debug')
        return None

    try:
        prefix = data[0:1]

        # KMS-encrypted data ('D' = Direct KMS, 'E' = Envelope KMS)
        if prefix in (b'D', b'E'):
            secure_log("KMS-encrypted data detected — KMS has been removed. Data needs re-encryption with Fernet.", 'error')
            return None

        # Fernet encryption ('F' prefix)
        elif prefix == b'F':
            cipher = get_cipher()
            if cipher:
                try:
                    decrypted = cipher.decrypt(data[1:])  # Skip 'F' prefix
                    secure_log("Fernet decryption successful", 'debug')
                    return decrypted
                except Exception as e:
                    secure_log(f"Fernet decryption failed: {e}", 'error')
                    return None

        # Legacy format (no prefix) — try Fernet directly
        else:
            secure_log(f"Legacy encrypted data detected (prefix byte: {prefix})", 'debug')
            cipher = get_cipher()
            if cipher:
                try:
                    decrypted = cipher.decrypt(data)
                    secure_log("Legacy Fernet decryption successful", 'debug')
                    return decrypted
                except Exception as fernet_error:
                    secure_log(f"Legacy Fernet decryption failed: {fernet_error}", 'error')
                    return None

        secure_log("No decryption method available", 'error')
        return None

    except Exception as e:
        secure_log(f"decrypt_bytes error: {e}", 'error')
        return None



def save_file(file_data, storage_type: str, filename: str = None, encrypt: bool = False, subfolder: str = None) -> Optional[str]:
    """
    Save file to PROJECT_X/uploads/ (local) or GCS (cloud) with optional encryption.

    Args:
        file_data: File data (bytes or file object)
        storage_type: Type of storage ('profiles', 'signatures', 'documents', 'bank_documents', etc.)
        filename: Optional filename (auto-generated if not provided)
        encrypt: If True, encrypts file content before saving (for sensitive documents)
        subfolder: Optional subfolder ('videos' or 'playlists') for organizing media files

    Returns:
        str or None: Relative file path (e.g., 'transcripts/videos/transcript.txt') or None on error
    """
    try:
        # Generate filename if not provided
        if not filename:
            if hasattr(file_data, 'filename') and file_data.filename:
                from werkzeug.utils import secure_filename
                timestamp = int(time.time() * 1000)
                original = secure_filename(file_data.filename)
                filename = f"{timestamp}_{original}"
            else:
                filename = f"{int(time.time() * 1000)}.bin"
        else:
            from werkzeug.utils import secure_filename
            filename = secure_filename(filename)
        
        # Read file content
        if hasattr(file_data, 'read'):
            file_data.seek(0)
            data = file_data.read()
        else:
            data = file_data
        
        # Encrypt if requested (for bank documents, confidential files)
        if encrypt:
            secure_log(f"Encrypting file: {filename}", 'info')
            encrypted_data = encrypt_bytes(data)
            if not encrypted_data:
                secure_log(f"Encryption failed for {filename}", 'error')
                return None
            data = encrypted_data
            secure_log(f"File encrypted successfully: {filename}", 'info')
        
        if use_cloud_storage():
            # Upload to Cloudflare R2 (S3-compatible via boto3)
            client = get_r2_client()
            if not client:
                secure_log("R2 client unavailable — check R2_ACCESS_KEY_ID and R2_ENDPOINT_URL", 'error')
                return None

            # Build object key with optional subfolder
            folder_name = STORAGE_FOLDERS.get(storage_type, storage_type)
            if subfolder:
                object_key = f"{folder_name}/{subfolder}/{filename}"
            else:
                object_key = f"{folder_name}/{filename}"

            # Determine content type
            content_type = 'application/octet-stream'
            if hasattr(file_data, 'content_type') and file_data.content_type:
                content_type = file_data.content_type

            try:
                client.put_object(
                    Bucket=Config.R2_BUCKET_NAME,
                    Key=object_key,
                    Body=data,
                    ContentType=content_type,
                )
                secure_log(f"File uploaded to R2: {object_key} (encrypted={encrypt})", 'info')
                return object_key
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                secure_log(f"R2 put_object failed: {e}\n{tb}", 'error')
                print(f"CRITICAL R2 UPLOAD FAILURE: {e}\n{tb}", flush=True)
                return None
        else:
            # Save to PROJECT_X/uploads/ locally
            storage_path = get_storage_path(storage_type, subfolder)
            if not storage_path:
                secure_log(f"Failed to get storage path for: {storage_type}", 'error')
                return None

            file_path = os.path.join(storage_path, filename)

            # Ensure directory exists
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            with open(file_path, 'wb') as f:
                f.write(data)

            # Return relative path (from uploads/)
            folder_name = STORAGE_FOLDERS.get(storage_type, storage_type)
            if subfolder:
                relative_path = f"{folder_name}/{subfolder}/{filename}"
            else:
                relative_path = f"{folder_name}/{filename}"
            secure_log(f"File saved locally: {file_path} -> {relative_path} (encrypted={encrypt})", 'info')
            return relative_path
            
    except Exception as e:
        secure_log(f"Failed to save file: {e}", 'error')
        import traceback
        secure_log(f"Traceback: {traceback.format_exc()}", 'error')
        return None

def get_r2_public_url(filepath: str) -> Optional[str]:
    """
    Get public URL for a file in Cloudflare R2.
    Requires R2_PUBLIC_URL to be set (custom domain via CF Dashboard > R2 > Settings).
    If not set, get_file_url() will fall back to a presigned URL.
    """
    try:
        if use_cloud_storage() and Config.R2_PUBLIC_URL:
            base = Config.R2_PUBLIC_URL.rstrip('/')
            key = filepath.lstrip('/')
            return f"{base}/{key}"
        return None
    except Exception as e:
        secure_log(f"Failed to generate R2 public URL: {e}", 'error')
        return None

def get_gcs_public_url(filepath: str) -> Optional[str]:
    """Backward compat alias for get_r2_public_url()."""
    return get_r2_public_url(filepath)

def get_file_url(filepath: str, storage_type: str = None) -> Optional[str]:
    """
    Get a publicly accessible URL for a file in R2 or a local path.

    In production:
        1. Returns R2 public URL if R2_PUBLIC_URL is configured (no signing, fastest)
        2. Falls back to presigned S3 URL (1 hour expiry) via boto3
    In development:
        Returns a local /uploads/ path served by Flask.
    """
    if not filepath:
        return None

    try:
        if use_cloud_storage():
            # Sanitize filepath to a relative path within the bucket
            if 'uploads/' in filepath:
                filepath = filepath.split('uploads/', 1)[-1]
            filepath = filepath.lstrip('/')

            # Try public URL first (no API call, instant)
            public_url = get_r2_public_url(filepath)
            if public_url:
                return public_url

            # Fall back to presigned URL (1 hour expiry)
            client = get_r2_client()
            if not client:
                secure_log("R2 client unavailable — cannot generate presigned URL", 'error')
                return None

            presigned_url = client.generate_presigned_url(
                'get_object',
                Params={'Bucket': Config.R2_BUCKET_NAME, 'Key': filepath},
                ExpiresIn=3600,  # 1 hour
            )
            return presigned_url

        else:
            # Local development: return /uploads/ route served by Flask
            if 'uploads' in filepath:
                filepath = filepath.split('uploads', 1)[-1]
            filepath = filepath.lstrip('/')
            return f"/uploads/{filepath}"

    except Exception as e:
        secure_log(f"Failed to get file URL for '{filepath}': {e}", 'error')
        return None

def download_file_content(filepath: str, decrypt: bool = False) -> Optional[bytes]:
    """
    Download file content from storage.

    Args:
        filepath: File path
        decrypt: If True, decrypt the file content (for .enc files)

    Returns:
        bytes or None: File content (decrypted if decrypt=True)
    """
    try:
        if use_cloud_storage():
            r2 = get_r2_client()
            if not r2:
                return None

            response = r2.get_object(Bucket=Config.R2_BUCKET_NAME, Key=filepath)
            data = response['Body'].read()
        else:
            # Read from local storage
            full_path = os.path.join(UPLOADS_BASE, filepath)
            if os.path.exists(full_path):
                with open(full_path, 'rb') as f:
                    data = f.read()
            else:
                return None

        # Decrypt if requested
        if decrypt and data:
            decrypted = decrypt_bytes(data)
            if decrypted:
                return decrypted
            else:
                secure_log(f"Failed to decrypt file: {filepath}", 'error')
                return None

        return data

    except Exception as e:
        secure_log(f"Failed to download file: {e}", 'error')
        return None

def file_exists(filepath: str) -> bool:
    """Check if file exists in storage"""
    try:
        if use_cloud_storage():
            r2 = get_r2_client()
            if not r2:
                return False
            try:
                r2.head_object(Bucket=Config.R2_BUCKET_NAME, Key=filepath)
                return True
            except r2.exceptions.ClientError:
                return False
        else:
            full_path = os.path.join(UPLOADS_BASE, filepath)
            return os.path.exists(full_path)
    except Exception as e:
        secure_log(f"Failed to check file existence: {e}", 'error')
        return False

def delete_file(filepath: str) -> bool:
    """Delete file from storage"""
    try:
        if use_cloud_storage():
            r2 = get_r2_client()
            if not r2:
                return False
            r2.delete_object(Bucket=Config.R2_BUCKET_NAME, Key=filepath)
            return True
        else:
            full_path = os.path.join(UPLOADS_BASE, filepath)
            if os.path.exists(full_path):
                os.remove(full_path)
            return True
    except Exception as e:
        secure_log(f"Failed to delete file: {e}", 'error')
        return False

def upload_to_gcs(local_path: str, gcs_path: str) -> bool:
    """Upload file to R2 from local path (backward compat alias)"""
    try:
        r2 = get_r2_client()
        if not r2:
            return False
        
        r2.upload_file(local_path, Config.R2_BUCKET_NAME, gcs_path)
        return True
    except Exception as e:
        secure_log(f"Failed to upload to R2: {e}", 'error')
        return False

def download_from_gcs(gcs_path: str, local_path: str) -> bool:
    """Download file from R2 to local path (backward compat alias)"""
    try:
        r2 = get_r2_client()
        if not r2:
            return False
        
        r2.download_file(Config.R2_BUCKET_NAME, gcs_path, local_path)
        return True
    except Exception as e:
        secure_log(f"Failed to download from R2: {e}", 'error')
        return False

# ##############################################################################
#
#                    SECTION 11: LOGGING
#
# ##############################################################################

def secure_log(message: str, level: str = 'info', user_id: str = None, context: Dict = None, **kwargs):
    """
    Secure logging with structured Python logging.
    
    Args:
        message: Log message
        level: Log level (debug, info, warning, error, critical)
        user_id: Optional user ID
        context: Optional context dictionary
        **kwargs: Additional context fields
    """
    # Combine context
    full_context = context or {}
    full_context.update(kwargs)
    
    if user_id:
        full_context['user_id'] = user_id
    
    # Standard Python logging — Cloudflare Logpush captures stdout/stderr
    py_logger = logging.getLogger('youcert')
    log_method = getattr(py_logger, level.lower(), py_logger.info)

    if full_context:
        log_method(f"{message} | Context: {json.dumps(full_context)}")
    else:
        log_method(message)


def sanitize_error_for_user(error_message: str, user_friendly_message: str = None) -> str:
    """
    Sanitize error messages for production to prevent information leakage.

    In production: Returns generic message and logs detailed error server-side
    In development: Returns detailed error message for debugging

    Args:
        error_message: The detailed error message
        user_friendly_message: Optional custom user-friendly message

    Returns:
        str: Sanitized error message safe to return to users
    """
    # Log the detailed error server-side
    secure_log(f"Error occurred: {error_message}", 'error')

    # In production, return generic message
    if is_production():
        return user_friendly_message or "An error occurred. Please try again later."

    # In development, return detailed error for debugging
    return error_message


# ##############################################################################
#
#                    SECTION 12: OAUTH
#
# ##############################################################################

@lru_cache(maxsize=1)
def get_google_client_config() -> Dict:
    """
    Get Google OAuth client configuration.
    
    Returns cached configuration to avoid repeated environment access.
    
    Returns:
        dict: OAuth client configuration
    """
    return {
        'web': {
            'client_id': Config.GOOGLE_CLIENT_ID,
            'client_secret': Config.GOOGLE_CLIENT_SECRET,
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'redirect_uris': [Config.OAUTH_REDIRECT_URI]
        }
    }

# ##############################################################################
#
#                    SECTION 13: DATABASE (FIXED cursor_class error)
#
# ##############################################################################

@contextmanager
def get_db_connection(cursor_class: str = 'dict'):
    """
    Database connection context manager with proper cleanup.

    Automatically uses the correct connection method:
    - Production: MySQL via TCP
    - Local: MySQL via TCP

    Args:
        cursor_class: 'dict' for DictCursor, 'tuple' for standard cursor

    Yields:
        tuple: (connection, cursor)

    Example:
        with get_db_connection() as (conn, cursor):
            cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            result = cursor.fetchone()

    Note:
        Flask-MySQLdb manages connections per-request automatically.
        The connection is returned to the pool when the Flask request ends.
        We only need to close the cursor explicitly.
    """
    cursor = None
    try:
        # Get connection from Flask-MySQLdb (managed per-request)
        connection = mysql.connection

        # Create cursor with appropriate type
        if cursor_class == 'dict':
            cursor = connection.cursor(MySQLdb.cursors.DictCursor)
        else:
            cursor = connection.cursor()

        yield connection, cursor

    except Exception as e:
        secure_log(f"DB Connection Error: {e}", 'error')
        raise
    finally:
        # Always close cursor to free resources
        if cursor:
            try:
                cursor.close()
            except Exception as cursor_close_error:
                secure_log(f"Error closing cursor: {cursor_close_error}", 'warning')

        # Note: Flask-MySQLdb automatically returns connection to pool
        # at end of request via teardown_appcontext. No manual close needed.

def execute_query(
    query: str,
    params: tuple = None,
    cursor_class: str = 'dict',
    fetch_one: bool = False,
    fetch_all: bool = False,
    commit: bool = False
) -> Any:
    """
    Execute a database query safely.

    This is the primary function for database operations.
    Handles connections, cursors, commits, and rollbacks automatically.

    Args:
        query: SQL query string with %s placeholders
        params: Tuple of parameters for the query
        cursor_class: 'dict' or 'tuple'
        fetch_one: Return single row
        fetch_all: Return all rows
        commit: Commit the transaction

    Returns:
        - If fetch_one: Single row dict/tuple or None
        - If fetch_all: List of rows
        - If commit: Number of affected rows
        - Otherwise: None

    Example:
        # Select single row
        user = execute_query(
            "SELECT * FROM users WHERE id = %s",
            (user_id,),
            fetch_one=True
        )

        # Select multiple rows
        users = execute_query(
            "SELECT * FROM users WHERE status = %s",
            ('active',),
            fetch_all=True
        )

        # Insert/Update
        rows_affected = execute_query(
            "UPDATE users SET status = %s WHERE id = %s",
            ('inactive', user_id),
            commit=True
        )
    """
    with get_db_connection(cursor_class) as (conn, cursor):
        try:
            cursor.execute(query, params or ())

            if commit:
                conn.commit()
                return cursor.rowcount

            if fetch_one:
                return cursor.fetchone()
            if fetch_all:
                return cursor.fetchall()

            return None
        except Exception as e:
            if commit:
                try:
                    conn.rollback()
                except Exception:
                    pass
            secure_log(f"Query Error: {e}", 'error')
            raise

def execute_many(query: str, params_list: list, commit: bool = True) -> int:
    """
    Execute bulk insert/update.

    More efficient than multiple execute_query calls.

    Args:
        query: SQL query with %s placeholders
        params_list: List of parameter tuples
        commit: Whether to commit

    Returns:
        int: Number of affected rows

    Example:
        execute_many(
            "INSERT INTO logs (user_id, action) VALUES (%s, %s)",
            [(1, 'login'), (2, 'logout'), (3, 'view')]
        )
    """
    with get_db_connection('tuple') as (conn, cursor):
        try:
            cursor.executemany(query, params_list)
            if commit:
                conn.commit()
            return cursor.rowcount
        except Exception as e:
            if commit:
                try:
                    conn.rollback()
                except Exception:
                    pass
            secure_log(f"Bulk Exec Error: {e}", 'error')
            raise

def call_stored_procedure(proc_name: str, params: tuple = None) -> list:
    """
    TiDB Cloud Compatible: Stored procedures NOT supported.

    TiDB Cloud Serverless does not support MySQL stored procedures.
    This function raises NotImplementedError to guide migration to
    execute_query() based Python logic.

    Args:
        proc_name: Name of the stored procedure (legacy reference only)
        params: Not used

    Raises:
        NotImplementedError: Always, since TiDB does not support stored procedures.
    """
    raise NotImplementedError(
        f"Stored procedures are not supported in TiDB Cloud Serverless. "
        f"Please refactor '{proc_name}' logic into Python using execute_query() or get_db_connection()."
    )

# ##############################################################################
#
#                    SECTION 14: SESSION & CACHE
#
# ##############################################################################

def get_session_fingerprint() -> str:
    """
    Generate session fingerprint from user agent and IP.
    
    Returns:
        str: Fingerprint hash
    """
    user_agent = request.headers.get('User-Agent', '')
    ip_address = request.remote_addr or ''
    fingerprint_string = f"{user_agent}:{ip_address}"
    return hashlib.sha256(fingerprint_string.encode()).hexdigest()

def validate_session_security() -> bool:
    """
    Validate session security with smart fingerprint checking.

    CONTAINER OPTIMIZED:
    - Allows up to 333 fingerprint changes (IP changes are normal behind load balancers)
    - Strict User-Agent check (exact match required)
    - Prevents infinite login loops on IP changes

    Allows fingerprint changes for:
    - Load balancer IP routing changes
    - Mobile network switches (IP changes)
    - CDN/proxy routing changes

    Blocks:
    - ANY User-Agent change (session hijacking)
    - More than 333 fingerprint changes per session (excessive)

    Returns:
        bool: True if session is valid, False if suspicious
    """
    if 'fingerprint' not in session:
        return True  # First request after login

    current_fingerprint = get_session_fingerprint()
    stored_fingerprint = session.get('fingerprint')

    if current_fingerprint != stored_fingerprint:
        # Track fingerprint change count
        change_count = session.get('fingerprint_changes', 0)

        # STRICT User-Agent check - exact match required
        current_ua = request.headers.get('User-Agent', '')
        stored_ua = session.get('original_user_agent', current_ua)

        # If User-Agent is DIFFERENT, it is definitely an attack (or browser upgrade)
        # Block this immediately
        if current_ua != stored_ua:
            secure_log(
                f"Session security violation: User-Agent changed",
                'warning',
                user_id=session.get('user_id') or session.get('channel_id') or session.get('admin_id')
            )
            return False

        # If User-Agent matches but Fingerprint (IP) changed:
        # Behind load balancers, IP changes are normal. We INCREASE the limit.
        if change_count >= 333:  # INCREASED FROM 3 TO 333 for container environments
            secure_log(
                f"Session security violation: Too many IP changes ({change_count})",
                'warning',
                user_id=session.get('user_id') or session.get('channel_id') or session.get('admin_id')
            )
            return False

        # Allow change and update fingerprint to new IP
        secure_log(
            f"Session fingerprint changed (allowed, count: {change_count + 1}): IP change detected (normal behind load balancer)",
            'debug'
        )
        session['fingerprint'] = current_fingerprint
        session['fingerprint_changes'] = change_count + 1

    return True

def clear_user_session():
    """
    Clear only user-specific session data, preserving creator/admin sessions.

    This allows multiple user types to be logged in simultaneously on the same browser.
    """
    user_keys = [
        'user_id', 'name', 'email', 'new_user',
        'oauth_state', 'oauth_state_timestamp',
        'fingerprint', 'last_activity'
    ]
    # Also clear any exam attempt keys
    exam_keys = [key for key in session.keys() if key.startswith('exam_')]

    for key in user_keys + exam_keys:
        session.pop(key, None)

def clear_creator_session():
    """
    Clear only creator-specific session data, preserving user/admin sessions.

    This allows multiple user types to be logged in simultaneously on the same browser.
    """
    creator_keys = [
        'channel_id', 'channel_name', 'email', 'creator_id',
        'oauth_state', 'reconnecting',
        'fingerprint', 'last_activity'
    ]

    for key in creator_keys:
        session.pop(key, None)

def clear_admin_session():
    """
    Clear only admin-specific session data, preserving user/creator sessions.

    This allows multiple user types to be logged in simultaneously on the same browser.
    """
    admin_keys = [
        'admin_id', 'admin_name', 'email', 'admin_designation',
        'temp_setup_name', 'temp_registration',
        'impersonating', 'original_admin_id',
        'fingerprint', 'last_activity'
    ]
    # Also clear any OTP verification keys
    otp_keys = [key for key in session.keys() if 'otp_verified' in key]

    for key in admin_keys + otp_keys:
        session.pop(key, None)

def get_user_cache_key(key: str, user_id: str = None) -> str:
    """
    Get user-specific cache key.
    
    Args:
        key: Base key
        user_id: User ID
    
    Returns:
        str: User-specific cache key
    """
    if user_id:
        return f"user_{user_id}_{key}"
    return key

def get_user_cache(key: str, user_id: str = None):
    """
    Get value from cache with user isolation.
    
    Args:
        key: Cache key
        user_id: User ID for isolation
    
    Returns:
        Cached value or None
    """
    cache_key = get_user_cache_key(key, user_id)
    return cache.get(cache_key)

def set_user_cache(key: str, value, user_id: str = None, timeout: int = 300):
    """
    Set value in cache with user isolation.
    
    Args:
        key: Cache key
        value: Value to cache
        user_id: User ID for isolation
        timeout: Cache timeout in seconds
    """
    cache_key = get_user_cache_key(key, user_id)
    cache.set(cache_key, value, timeout=timeout)

def delete_user_cache(key: str, user_id: str = None):
    """
    Delete value from cache with user isolation.
    
    Args:
        key: Cache key
        user_id: User ID for isolation
    """
    cache_key = get_user_cache_key(key, user_id)
    cache.delete(cache_key)

# ##############################################################################
#
#                    SECTION 15: APP FACTORY
#
# ##############################################################################

def _init_encryption(app):
    """Initialize encryption system (Fernet only)"""
    if Config.TOKEN_ENCRYPTION_KEY:
        get_cipher()  # Initialize Fernet
        secure_log("Using Fernet for encryption", 'info')
    else:
        secure_log("No encryption key configured!", 'warning')

def _configure_cache(app):
    """
    Configure cache (SimpleCache only - no Redis).
    
    Args:
        app: Flask application
    """
    # Always use SimpleCache (in-memory, no external dependencies)
    app.config['CACHE_TYPE'] = 'SimpleCache'
    app.config['CACHE_DEFAULT_TIMEOUT'] = 300
    
    cache.init_app(app)
    secure_log("Cache initialized: SimpleCache (in-memory)", 'info')

def create_app(config_name: str = 'production') -> Flask:
    """
    Application factory.
    
    Args:
        config_name: Configuration name (development, production)
    
    Returns:
        Flask: Configured Flask application
    """
    print("[create_app] CA0: Starting create_app...", flush=True)
    app = Flask(__name__)
    print("[create_app] CA0: Flask instance created", flush=True)

    # ==========================================================================
    # 0. CONFIGURE PROXY HEADERS (for HTTPS behind load balancer)
    # ==========================================================================
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    print("[create_app] CA1: ProxyFix applied", flush=True)

    # ==========================================================================
    # 1. LOAD CONFIGURATION
    # ==========================================================================
    print("[create_app] CA2: Loading config...", flush=True)
    from config import get_config
    config_class = get_config(config_name)
    app.config.from_object(config_class)
    print("[create_app] CA2: Config loaded", flush=True)

    # Fix MySQL configuration for Cloudflare Containers
    if Config.IS_CLOUDFLARE:
        secure_log(f"MySQL configured for TCP: host={'SET' if Config.MYSQL_HOST else 'MISSING'}, port={Config.MYSQL_PORT}", 'info')

    # Configuration Mode
    if not Config.IS_CLOUDFLARE:
        secure_log("Local Development Mode:", 'info')
    else:
        secure_log("Cloudflare Production Mode:", 'info')

    # Set dynamic OAuth redirect URI based on BASE_URL
    Config.OAUTH_REDIRECT_URI = f"{Config.BASE_URL}/oauth_callback"

    # ==========================================================================
    # 2. CONFIGURE LOGGING
    # ==========================================================================
    print("[create_app] CA3: Configuring logging...", flush=True)
    log_level = getattr(logging, Config.LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.ERROR)
    print("[create_app] CA3: Logging configured", flush=True)

    # ==========================================================================
    # 3. ENSURE STORAGE DIRECTORIES (with videos/playlists subfolders)
    # ==========================================================================
    print("[create_app] CA4: init_storage_directories...", flush=True)
    init_storage_directories()
    print("[create_app] CA4: Storage dirs done", flush=True)
    
    # ==========================================================================
    # 4. LOG ENVIRONMENT INFO
    # ==========================================================================
    print("[create_app] CA5: Logging env info...", flush=True)
    secure_log(f"Environment: {'Cloudflare Containers' if is_cloud_run() else 'Local Development'}", 'info')
    secure_log(f"Platform: {'Windows' if is_windows() else 'Linux/Mac'}", 'info')
    
    # ==========================================================================
    # 5. INITIALIZE FLASK EXTENSIONS
    # ==========================================================================
    print("[create_app] CA6: csrf.init_app...", flush=True)
    csrf.init_app(app)
    print("[create_app] CA6: csrf done", flush=True)
    # ═══════════════════════════════════════════════════════════════════════
    # TiDB Cloud SSL via MYSQL_CUSTOM_OPTIONS
    # ═══════════════════════════════════════════════════════════════════════
    # Flask-MySQLdb has NO built-in SSL support (verified from source).
    # The ONLY way to pass SSL is via MYSQL_CUSTOM_OPTIONS which gets
    # kwargs.update()'d into pymysql.connect(**kwargs).
    #
    # Since we use pymysql.install_as_MySQLdb(), the ssl param format is:
    #   pymysql.connect(ssl={'ca': '/path/to/ca-certificates.crt'})
    # ═══════════════════════════════════════════════════════════════════════
    if Config.IS_TIDB:
        ssl_cfg = Config.MYSQL_SSL or {}
        ca_path = ssl_cfg.get('ca', '') if isinstance(ssl_cfg, dict) else ''

        if ca_path:
            # Explicit CA cert found (e.g. Linux system bundle)
            app.config['MYSQL_CUSTOM_OPTIONS'] = {
                'ssl': {'ca': ca_path}
            }
            print(f"[create_app] CA7: TiDB SSL via MYSQL_CUSTOM_OPTIONS (CA={ca_path})", flush=True)
        else:
            # No explicit CA — still enable SSL (pymysql will use default verification)
            app.config['MYSQL_CUSTOM_OPTIONS'] = {
                'ssl': {'ssl': True}
            }
            print("[create_app] CA7: TiDB SSL via MYSQL_CUSTOM_OPTIONS (no explicit CA)", flush=True)

    print("[create_app] CA7: mysql.init_app...", flush=True)
    mysql.init_app(app)
    print("[create_app] CA7: mysql done", flush=True)
    
    print("[create_app] CA8: limiter.init_app...", flush=True)
    limiter.init_app(app)
    print("[create_app] CA8: limiter done", flush=True)
    
    # ==========================================================================
    # 6. CONFIGURE CACHE (SimpleCache - NO REDIS)
    # ==========================================================================
    print("[create_app] CA9: _configure_cache...", flush=True)
    _configure_cache(app)
    print("[create_app] CA9: cache done", flush=True)
    
    # ==========================================================================
    # 7. INITIALIZE EMAIL SERVICE CACHE
    # ==========================================================================
    print("[create_app] CA10: email service cache...", flush=True)
    with app.app_context():
        try:
            from youcert.logic import email_service
            email_service.set_cache(cache)
            print("[create_app] CA10: email service done", flush=True)
        except Exception as e:
            print(f"[create_app] CA10: email service skipped: {e}", flush=True)
    
    # ==========================================================================
    # 8. CONFIGURE CORS
    # ==========================================================================
    allowed_origins = [
        "http://localhost:5000",
        "http://127.0.0.1:5000",
    ]

    # Add production domains (both with and without www)
    service_url = getattr(Config, 'SERVICE_URL', None)
    if service_url:
        allowed_origins.append(service_url)
        # Also add non-www variant if using www, or www variant if not
        if service_url.startswith("https://www."):
            allowed_origins.append(service_url.replace("https://www.", "https://"))
        elif service_url.startswith("https://"):
            allowed_origins.append(service_url.replace("https://", "https://www."))
    
    CORS(app, resources={
        r"/*": {
            "origins": allowed_origins,
            "methods": ["GET", "POST", "PUT", "DELETE"],
            "allow_headers": ["Content-Type", "Authorization", "X-CSRFToken"],
            "supports_credentials": True
        }
    })
    print("[create_app] CA11: CORS done", flush=True)
    
    # ==========================================================================
    # 9. INITIALIZE ENCRYPTION (Fernet)
    # ==========================================================================
    print("[create_app] CA12: _init_encryption...", flush=True)
    _init_encryption(app)
    print("[create_app] CA12: encryption done", flush=True)
    
    # ==========================================================================
    # 10. CONFIGURE SESSION SECURITY (CLIENT-SIDE SIGNED COOKIES)
    # ==========================================================================
    app.config.update(
        SESSION_COOKIE_SECURE=is_production(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=21600,  # 6 hours
        WTF_CSRF_TIME_LIMIT=900,  # 15 minutes
    )
    print("[create_app] CA13: session security done", flush=True)
    
    # ==========================================================================
    # 11. STATIC FILE SERVING
    # ==========================================================================
    @app.route('/uploads/<path:filename>')
    def serve_uploads(filename):
        """
        Serve uploaded files from PROJECT_X/uploads/ directory.
        - Production: Redirect to R2 public URL
        - Local: Serve from uploads directory
        """
        if use_cloud_storage():
            # Get public R2 URL for the file
            gcs_url = get_gcs_public_url(filename)
            if gcs_url:
                from flask import redirect
                return redirect(gcs_url)
            # Fallback if R2 fails
            abort(404)

        # Local development - serve from PROJECT_X/uploads/
        uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
        return send_from_directory(uploads_dir, filename)

    
    # ==========================================================================
    # 12. SECURITY HEADERS
    # ==========================================================================
    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        if is_production():
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response
    
    # ==========================================================================
    # 13. SESSION VALIDATION
    # ==========================================================================
    @app.before_request
    def validate_session():
        if request.endpoint and 'static' not in request.endpoint:
            if session.get('user_id') or session.get('channel_id') or session.get('admin_id'):
                if 'fingerprint' not in session:
                    session['fingerprint'] = get_session_fingerprint()
                    session['original_user_agent'] = request.headers.get('User-Agent', '')
                    session['fingerprint_changes'] = 0
                    session['last_activity'] = datetime.now().isoformat()
    
    # ==========================================================================
    # 14. CRON JOB ENDPOINTS (For Cloud Scheduler)
    # ==========================================================================
    @app.route('/cron/cleanup-tokens', methods=['POST'])
    def cron_cleanup_tokens():
        """
        Cleanup expired OTP and password reset tokens.

        This endpoint is called by Cloud Scheduler daily.
        Only accepts requests from Cloud Scheduler (X-CloudScheduler header).
        """
        # Verify request is from Cloud Scheduler
        if is_production():
            scheduler_header = request.headers.get('X-CloudScheduler')
            if not scheduler_header:
                secure_log("Unauthorized cron access attempt", 'warning')
                return jsonify({'error': 'Unauthorized'}), 401

        try:
            stats = cleanup_expired_tokens_db()
            secure_log(
                "Cron: Token cleanup completed",
                'info',
                context=stats
            )
            return jsonify({
                'success': True,
                'message': 'Token cleanup completed',
                'stats': stats
            }), 200
        except Exception as e:
            error_msg = sanitize_error_for_user(
                str(e),
                "Token cleanup failed"
            )
            return jsonify({
                'success': False,
                'error': error_msg
            }), 500

    # ==========================================================================
    # 15. REGISTER BLUEPRINTS
    # ==========================================================================
    print("[create_app] CA14: importing blueprints...", flush=True)
    from .routes import creator_bp, user_bp, admin_bp, public_bp
    print("[create_app] CA14: blueprints imported, registering...", flush=True)

    app.register_blueprint(user_bp)
    app.register_blueprint(creator_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(public_bp)
    print("[create_app] CA14: main blueprints registered", flush=True)
    
    # Register worker blueprint for Cloudflare Queues
    try:
        from .routes import worker_bp
        app.register_blueprint(worker_bp)
        # Exempt worker routes from CSRF protection (queue consumers cannot provide CSRF tokens)
        csrf.exempt(worker_bp)
        secure_log("Worker routes registered for Cloudflare Queues (CSRF exempt)", 'info')
    except ImportError:
        secure_log("Worker routes not available (Queues disabled)", 'info')
    
    # ==========================================================================
    # 16. REGISTER TASK HANDLERS (For local task execution)
    # ==========================================================================
    try:
        from youcert.logic import task_handlers  # noqa: F401
        secure_log("Task handlers registered", 'info')
    except ImportError:
        secure_log("Task handlers not available", 'info')
    
    # ==========================================================================
    # 17. LOG FINAL STATUS
    # ==========================================================================
    print("[create_app] CA15: APP FULLY INITIALIZED!", flush=True)
    secure_log(f"App initialized successfully (Debug: {app.debug})", 'info')
    
    # Log service status
    if use_cloud_storage():
        bucket_name = getattr(Config, 'R2_BUCKET_NAME', 'unknown')
        secure_log(f"Storage: R2 ({bucket_name})", 'info')
    else:
        secure_log("Storage: Local filesystem", 'info')
    
    secure_log("Encryption: Fernet", 'info')
    
    secure_log("Cache: SimpleCache (NO REDIS)", 'info')
    secure_log("Session: Client-side signed cookies", 'info')
    secure_log(f"OTP Storage: Database (admin_base.otp_tokens) - Multi-instance ready", 'info')
    
    # ==========================================================================
    # 18. CPU-BASED AUTO-SCALE TRIGGER
    # ==========================================================================
    # Monitors container CPU in a background thread. When average CPU exceeds
    # 90% for 15 consecutive seconds, new requests are rejected with 503 so
    # Cloudflare's Load Balancer spins up a fresh container automatically.
    # Only active in production (Cloudflare Containers).
    if is_production():
        try:
            from youcert.cpu_monitor import start_monitor, is_overloaded
            start_monitor()
            print("[create_app] CA16: CPU auto-scale monitor started", flush=True)

            @app.before_request
            def cpu_overload_guard():
                """Return 503 if this container's CPU is saturated (>90% avg)."""
                # Never block health checks or Cloudflare readiness probes
                if request.path in ('/_health', '/health', '/favicon.ico'):
                    return None
                if is_overloaded():
                    from flask import Response
                    return Response(
                        "Service temporarily overloaded — retry shortly.",
                        status=503,
                        headers={
                            "Retry-After": "5",
                            "X-Container-Overloaded": "1"
                        }
                    )

        except Exception as e:
            print(f"[create_app] CA16: CPU monitor failed to start: {e}", flush=True)
    else:
        print("[create_app] CA16: CPU monitor skipped (local dev mode)", flush=True)

    return app

# ##############################################################################
#
#                    SECTION 17: MODULE EXPORTS
#
# ##############################################################################

# All functions and variables that should be importable from youcert
__all__ = [
    # Environment Detection
    'is_cloud_run',
    'is_production',
    'is_windows',
    'get_base_url',
    'get_project_id',
    
    # Flask Extensions
    'mysql',
    'csrf',
    'cache',
    'limiter',
    
    # Cloudflare Clients (backward-compat names preserved)
    'get_r2_client',
    'get_gcs_client',   # alias → get_r2_client()
    'get_gcs_bucket',   # alias → get_r2_client()
    'use_cloud_storage',
    'get_secret',
    'clear_secret_cache',
    'get_cloud_tasks_client',   # stub → None
    
    # Encryption
    'get_cipher',
    'encrypt_token',
    'decrypt_token',
    'encrypt_bytes',
    'decrypt_bytes',
    
    # Storage
    'PROJECT_ROOT',
    'STATIC_BASE',
    'UPLOADS_BASE',
    'STORAGE_FOLDERS',
    'STORAGE_PATHS',
    'init_storage_directories',
    'get_storage_path',
    'save_file',
    'get_file_url',
    'download_file_content',
    'file_exists',
    'delete_file',
    'upload_to_gcs',
    'download_from_gcs',
    
    # Logging
    'secure_log',
    
    # OAuth
    'get_google_client_config',
    
    # Database
    'get_db_connection',
    'execute_query',
    'execute_many',
    'call_stored_procedure',
    
    # Session & Cache
    'get_session_fingerprint',
    'validate_session_security',
    'clear_user_session',
    'clear_creator_session',
    'clear_admin_session',
    'get_user_cache_key',
    'get_user_cache',
    'set_user_cache',
    'delete_user_cache',
    
    # Database OTP Management (NEW v14.0)
    'save_otp_to_database',
    'get_otp_from_database',
    'verify_otp_from_database',
    'delete_otp_from_database',
    'cleanup_expired_tokens_db',
    
    # Database Password Reset Token Management (NEW v14.0)
    'save_password_reset_token_db',
    'get_password_reset_token_db',
    'validate_password_reset_token_db',
    'delete_password_reset_token_db',
    
    # App Factory
    'create_app',

    # Database Lockout Management (NEW v15.0)
    'save_login_lockout_db',
    'get_login_lockout_db',
    'delete_login_lockout_db',
    'increment_failed_login_db',
    'reset_failed_login_db',
    'check_login_lockout_db',
]

