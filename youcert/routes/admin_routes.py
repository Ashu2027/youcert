import hashlib
"""
YOUCERT ADMIN CONTROL SYSTEM - v14.0 DATABASE OTP CENTRALIZED UPGRADE
================================================================
Complete admin panel with FULL CRUD operations + Bank Verification System

UPGRADE v14.0 - DATABASE OTP + FULL CLOUD COMPATIBILITY:
- Database-level OTP storage for multi-instance Cloud Run compatibility.
- All database operations refactored to use centralized execute_query/get_db_connection.
- All local file I/O replaced with centralized save_file/download_file_content/delete_file
  for seamless GCS/Local storage support.
- Centralized logging via secure_log preserved.
- Existing security features (password check, encryption, path security) maintained.

Route Prefix: /naanni/
Designation Hierarchy: Supreme(0) > Chief(1) > Major(2) > Hero(3)
================================================================
"""

from flask import Blueprint, render_template, session, url_for, redirect, request, flash, current_app, jsonify, g, abort, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

from youcert import (
    limiter, cache,
    validate_session_security, get_session_fingerprint,
    secure_log, get_db_connection, execute_query,
    save_file, get_file_url, download_file_content, delete_file,
    STORAGE_PATHS,
    # Encryption Functions
    encrypt_token, decrypt_token,
    # Database Token Management (v15.0 - Fully database-based)
    save_otp_to_database,
    verify_otp_from_database,
    delete_otp_from_database,
    save_password_reset_token_db,
    get_password_reset_token_db,
    validate_password_reset_token_db,
    delete_password_reset_token_db,
    cleanup_expired_tokens_db,
    # Database Lockout Management (v15.0)
    check_login_lockout_db,
    increment_failed_login_db,
    reset_failed_login_db,
    # Session Management
    clear_admin_session
)

from youcert.logic.email_service import (
    email_service, send_otp_email, verify_otp_email,
    send_password_reset_email, send_admin_welcome_email, send_admin_rejection_email
)

from config import Config

import random, os, json, mimetypes, io
from datetime import datetime, timedelta
from functools import wraps
import csv
import re
from urllib.parse import urlparse
import pyotp  # KEPT v14.0: Still needed for TOTP (authenticator apps) - different from email OTP
import qrcode
from io import BytesIO

# Create admin blueprint with secure prefix
admin_bp = Blueprint('sevak69', __name__, url_prefix='/naanni')



# Removed local file path definitions (ADMIN_LOG_FOLDER, ADMIN_DOCUMENT_FOLDERS)
# as file operations are now centralized via save_file/download_file_content

# NOTE: Storage paths are now centralized in __init__.py via STORAGE_PATHS
# Mapping admin folder keys to STORAGE_PATHS keys:
ADMIN_FOLDER_MAPPING = {
    'bank_docs': 'bank_documents',
    'uploads': 'uploads',
    'signatures': 'signatures',
    'profiles': 'profiles',
    'thumbnails': 'thumbnails',
    # Ensure all possible keys map correctly
    'transcripts': 'transcripts',
    'summaries': 'summaries',
    'certificates': 'certificates',
    'bank_documents': 'bank_documents',
}


def get_storage_folder_key(admin_key):
    """Map admin folder key to centralized STORAGE_PATHS key"""
    return ADMIN_FOLDER_MAPPING.get(admin_key, admin_key)


# Action codes for security logging
ACTION_CODES = {
    'login': 'SK01', 'logout': 'SK02', 'password_reset_request': 'SK03',
    'password_reset_complete': 'SK04', 'registration_request': 'SK05',
    'registration_complete': 'SK06', 'user_create': 'USR01', 'user_update': 'USR02',
    'user_delete': 'USR03', 'user_activate': 'USR04', 'user_deactivate': 'USR05',
    'creator_create': 'CRT01', 'creator_update': 'CRT02', 'creator_delete': 'CRT03',
    'creator_activate': 'CRT04', 'creator_deactivate': 'CRT05', 'bank_verify': 'BNK01',
    'bank_reject': 'BNK02', 'bank_update': 'BNK03', 'bank_freeze': 'BNK04',
    'bank_unfreeze': 'BNK05', 'bank_deactivate': 'BNK06', 'bank_activate': 'BNK07',
    'payout_process': 'PAY01', 'admin_create': 'ADM01', 'admin_update': 'ADM02',
    'admin_delete': 'ADM03', 'admin_approve': 'ADM04', 'admin_reject': 'ADM05',
    'document_upload': 'DOC01', 'document_view': 'DOC02', 'document_delete': 'DOC03',
    'search': 'SRC01', 'first_time_setup': 'SYS01', 'login_fail': 'SK99',
    'otp_send': 'SK10', 'otp_verify': 'SK11', 'otp_verify_fail': 'SK12'
}

# Designation levels and limits
DESIGNATION_LIMITS = {0: 1, 1: 3, 2: 8, 3: 20}
DESIGNATION_NAMES = {0: 'Supreme', 1: 'Chief', 2: 'Major', 3: 'Hero'}

# Entity CRUD configuration mapping - Must be secured with whitelisting
ENTITY_CRUD_MAP = {
    'user': {'db_name': 'user_base', 'table_name': 'user', 'pk_column': 'user_id', 'min_designation': 3, 'display_name': 'Users', 'allow_create': True, 'hidden_fields': ['password_hash', 'oauth_token', 'refresh_token', 'client_id', 'client_secret', 'token_uri'], 'readonly_fields': ['user_id', 'created_at', 'updated_at', 'last_login', 'token_expiry'], 'encrypted_fields': ['oauth_token', 'refresh_token', 'client_id', 'client_secret'], 'image_fields': ['profile_picture'], 'filter_fields': ['name', 'email', 'is_active', 'email_verified']},
    'user_result': {'db_name': 'user_base', 'table_name': 'user_result', 'pk_column': 'id', 'min_designation': 3, 'display_name': 'User Results', 'allow_create': True, 'hidden_fields': [], 'readonly_fields': ['id', 'unique_order_number', 'completed_at'], 'encrypted_fields': [], 'image_fields': [], 'filter_fields': ['user_id', 'channel_id', 'unique_exam_number', 'payment_date']},
    'exam': {'db_name': 'exam', 'table_name': 'listed_exams', 'pk_column': 'unique_exam_number', 'min_designation': 2, 'display_name': 'Listed Exams', 'allow_create': True, 'hidden_fields': [], 'readonly_fields': ['id', 'unique_exam_number', 'created_at', 'updated_at'], 'encrypted_fields': [], 'image_fields': ['thumbnail_image'], 'filter_fields': ['channel_id', 'channel_name', 'is_active', 'exam_price']},
    'purchase_exam': {'db_name': 'exam', 'table_name': 'purchased_exams', 'pk_column': 'unique_order_number', 'min_designation': 2, 'display_name': 'Purchased Exams', 'allow_create': True, 'hidden_fields': [], 'readonly_fields': ['id', 'unique_order_number', 'created_at', 'updated_at'], 'encrypted_fields': [], 'image_fields': [], 'filter_fields': ['user_id', 'channel_id', 'payment_status', 'payment_date']},
    'creator': {'db_name': 'creator_base', 'table_name': 'creators', 'pk_column': 'channel_id', 'min_designation': 2, 'display_name': 'Creators', 'allow_create': True, 'hidden_fields': ['password_hash', 'oauth_token', 'refresh_token', 'client_id', 'client_secret', 'token_uri'], 'readonly_fields': ['channel_id', 'created_at', 'updated_at', 'token_expiry'], 'encrypted_fields': ['oauth_token', 'refresh_token', 'client_id', 'client_secret'], 'image_fields': ['profile_photo_jpg', 'signature_jpg_file'], 'filter_fields': ['creator_name', 'email', 'is_active', 'oauth_connected']},
    'bank_details': {'db_name': 'creator_base', 'table_name': 'creator_bank_info', 'pk_column': 'id', 'min_designation': 1, 'display_name': 'Bank Details', 'allow_create': True, 'hidden_fields': [], 'readonly_fields': ['id', 'created_at', 'updated_at', 'verified_at'], 'encrypted_fields': ['account_number', 'id_number'], 'image_fields': ['id_image_path', 'bank_document_path'], 'filter_fields': ['channel_id', 'verification_status', 'is_active', 'is_frozen', 'country_code']},
    'admin': {'db_name': 'admin_base', 'table_name': 'admins', 'pk_column': 'admin_id', 'min_designation': 1, 'display_name': 'Admins', 'allow_create': True, 'hidden_fields': ['password_hash'], 'readonly_fields': ['id', 'admin_id', 'created_at', 'updated_at', 'date_joined', 'last_login'], 'encrypted_fields': [], 'image_fields': [], 'filter_fields': ['name', 'email', 'designation', 'is_active', 'is_approved']},
    'contact_query': {'db_name': 'query_base', 'table_name': 'contact_us_queries', 'pk_column': 'query_id', 'min_designation': 3, 'display_name': 'Contact Queries', 'allow_create': False, 'hidden_fields': ['visitor_ip'], 'readonly_fields': ['id', 'query_id', 'submitted_at', 'updated_at', 'resolved_at', 'resolved_by'], 'encrypted_fields': [], 'image_fields': [], 'filter_fields': ['name', 'email', 'subject', 'resolved']}
}

# FIXED: Whitelist for security against SQL Injection
ALLOWED_DB_NAMES = list(set(config['db_name'] for config in ENTITY_CRUD_MAP.values()))
ALLOWED_TABLE_NAMES = list(set(config['table_name'] for config in ENTITY_CRUD_MAP.values()))

# ============================================================================
# SECURITY HARDENING UTILITIES (v11.1 - SIMPLIFIED)
# ============================================================================

def validate_password_strength(password):
    """Validate password meets complexity requirements."""
    import re

    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r'[0-9]', password):
        return False, "Password must contain at least one number"
    if not re.search(r'[!@#$%^&*(),.?":{}|<>\-_]', password):
        return False, "Password must contain at least one special character (!@#$%^&*)"

    return True, "Password meets all requirements"

def check_login_lockout(email):
    """Check if admin account is locked due to failed login attempts."""
    return check_login_lockout_db(email, 'admin')

def increment_failed_login(email):
    """Increment failed login counter, lock account after 5 attempts."""
    ip_address = get_client_ip()
    return increment_failed_login_db(email, 'admin', max_attempts=5, 
                                    lockout_minutes=30, ip_address=ip_address)

def reset_failed_login(email):
    """Reset failed login counter on successful login."""
    reset_failed_login_db(email, 'admin')

# TiDB Compatible: Direct INSERT replaces LogAdminAction stored procedure.
def log_admin_action(action_code, target_type=None, target_id=None, details=''):
    """Log admin actions with coded messages for security (into DB) — TiDB Compatible."""
    admin_id = session.get('admin_id', 'SYSTEM')
    ip_address = get_client_ip()

    action_code = str(action_code)[:10] if action_code else 'UNKNOWN'
    target_type = str(target_type)[:50] if target_type else None
    target_id = str(target_id)[:100] if target_id else None
    details = str(details)[:1000] if details else ''

    try:
        execute_query(
            """
            INSERT INTO admin_base.admin_logs
            (admin_id, action_code, target_type, target_id, details, ip_address, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """,
            (admin_id, action_code, target_type, target_id, details, ip_address),
            commit=True
        )
    except Exception as e:
        secure_log(f"Failed to log admin action to DB (Code: {action_code}, Context: {details}): {str(e)}", 'error')
    
# Removed: log_admin_action duplicate that used direct cursor

# Removed: validate_file_content (not used by the new storage model)

def get_totp_secret(admin_id):
    """Get TOTP secret from database if it exists."""
    try:
        # Use execute_query for centralized DB access
        result = execute_query(
            "SELECT totp_secret FROM admin_base.admins WHERE admin_id = %s LIMIT 1",
            (admin_id,),
            fetch_one=True
        )
        if result and result.get('totp_secret'):
            return result['totp_secret']
        return None
    except Exception as e:
        secure_log(f"TOTP secret not found or DB error: {str(e)}", 'info')
        return None

# TOTP / QR code logic remains the same (no DB interaction)

def verify_totp_token(secret, token):
    """Verify 6-digit TOTP token from authenticator app."""
    if not secret:
        return False

    try:
        totp = pyotp.TOTP(secret)
        # Allow 30-second window before/after for clock skew
        is_valid = totp.verify(token, valid_window=1)

        if is_valid:
            secure_log("TOTP token verified", 'debug')
        else:
            secure_log("TOTP token verification failed", 'error')

        return is_valid
    except Exception as e:
        secure_log(f"TOTP verification error: {str(e)}", 'error')
        return False

def generate_totp_qr_code(admin_email, secret=None):
    """
    Generate TOTP secret and QR code for setup.
    Returns (secret, qr_svg_string)
    """
    if not secret:
        secret = pyotp.random_base32()

    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(
        name=admin_email,
        issuer_name='YOUCERT Admin'
    )

    # Generate QR code
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    # Convert to bytes
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)

    secure_log(f"TOTP QR code generated for {admin_email}", 'info')
    return secret, buffer.getvalue()


def get_client_ip():
    """Get real client IP address, handling proxies"""
    if request.headers.getlist("X-Forwarded-For"):
       ip = request.headers.getlist("X-Forwarded-For")[0].split(',')[0].strip()
    else:
       ip = request.remote_addr or '127.0.0.1'
    return ip

# Removed: send_email placeholder (using email_service instead)
# Removed: get_relative_path (no longer needed, save_file returns relative path automatically)


# ============================================================================
# FILE OPERATION HELPERS (Simplified to use Centralized functions)
# ============================================================================

def validate_file_path_security(file_path):
    """
    CRITICAL: Preserves original path traversal security logic from v11.1
    Checks if a relative path belongs to one of the configured storage categories.
    NOTE: This is mainly a fallback check as GCS inherently prevents traversal.
    """
    if not file_path: return False
    
    # Get all folder keys and check if the relative path starts with one of them
    parts = file_path.replace('\\', '/').split('/', 1)
    folder_name = parts[0]
    
    # Check if the folder name is a known storage category key
    return folder_name in STORAGE_PATHS.keys()


def load_file_from_storage(file_path, decrypt=False):
    """
    Load file from storage using centralized download_file_content.
    Includes path validation.
    """
    try:
        # Centralized check for path safety (ensures it's a known storage path)
        if not validate_file_path_security(file_path):
            secure_log(f"Path traversal attempt blocked: {file_path}", 'warning')
            return None
        
        # Use centralized function from __init__.py which handles GCS/Local + decryption
        return download_file_content(file_path, decrypt=decrypt)
        
    except Exception as e:
        secure_log(f"Error loading file: {str(e)}", 'error')
        return None


def save_file_to_storage(file_obj, folder_type, filename, encrypt=False):
    """
    Wrapper to save FileStorage object using centralized save_file.
    """
    try:
        # Map admin folder type to STORAGE_PATHS key
        storage_key = get_storage_folder_key(folder_type)
        
        # Use centralized function from __init__.py (supports FileStorage, BytesIO, bytes)
        file_obj.seek(0) # Ensure we start from the beginning
        return save_file(file_obj, storage_key, filename, encrypt=encrypt)
            
    except Exception as e:
        secure_log(f"Error saving file: {str(e)}", 'error')
        return None


def get_upload_folder_type(image_field, entity_key):
    """Get folder type key for save_file (maps to STORAGE_PATHS keys)"""
    if 'signature' in image_field:
        return 'signatures'
    elif 'profile' in image_field or 'photo' in image_field:
        return 'profiles'
    elif 'thumbnail' in image_field:
        return 'thumbnails'
    elif entity_key == 'bank_details':
        # Use the explicit key from STORAGE_PATHS
        return 'bank_documents'
    else:
        return 'uploads'


# ============================================================================
# DECORATORS FOR AUTHENTICATION AND AUTHORIZATION
# ============================================================================

def admin_login_required(f):
    """Decorator to require admin login with approval check and session validation"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        admin_id_in_session = session.get('admin_id')
        if not admin_id_in_session:
            flash('Please login to access admin panel.', 'error')
            return redirect(url_for('sevak69.login'))

        # CRITICAL FIX: Validate session security and clear session on failure
        if not validate_session_security():
            # Explicitly clear the session to stop the redirect loop
            clear_admin_session()
            flash('Session invalid or expired due to inactivity. Please log in again.', 'warning')
            return redirect(url_for('sevak69.login'))

        try:
            # Use execute_query for centralized DB access
            admin = execute_query(
                """
                SELECT designation, is_active, name, is_approved
                FROM admin_base.admins
                WHERE admin_id = %s AND is_active = 1
                """,
                (admin_id_in_session,),
                fetch_one=True
            )

            if not admin:
                clear_admin_session()
                flash('Session expired or account deactivated.', 'error')
                return redirect(url_for('sevak69.login'))

            # Check approval status (except Supreme who auto-approves)
            if admin['designation'] != 0 and not admin.get('is_approved', False):
                clear_admin_session()
                flash('Your admin account is pending approval from Supreme admin.', 'warning')
                return redirect(url_for('sevak69.login'))

            # Store admin info in g for access within the request context
            g.admin_id = admin_id_in_session
            g.admin_designation = admin['designation']
            g.admin_name = admin['name']

        except Exception as e:
            secure_log(f"Error during admin session validation: {str(e)}", 'error')
            clear_admin_session()
            flash('An unexpected error occurred. Please try logging in again.', 'error')
            return redirect(url_for('sevak69.login'))

        return f(*args, **kwargs)
    return decorated_function


def permission_required(min_designation):
    """Decorator to check admin designation permissions"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not hasattr(g, 'admin_designation') or g.admin_designation > min_designation:
                required_level = DESIGNATION_NAMES.get(min_designation, 'Unknown')
                current_level = DESIGNATION_NAMES.get(g.admin_designation, 'Unknown')
                secure_log(f"Access Denied. Required: {required_level}, Current: {current_level}. Endpoint: {request.path}", 'warning')
                flash(f'Access Denied. Required designation: {required_level} or higher.', 'error')
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def supreme_only(f):
    """Decorator to restrict access to supreme admins only (designation 0)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not hasattr(g, 'admin_designation') or g.admin_designation != 0:
            secure_log(f"Access Denied. Supreme only endpoint: {request.path}", 'warning')
            flash('Access Denied. This feature is restricted to supreme admins only.', 'error')
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

def can_manage_designation(admin_designation, target_designation):
    """Check if admin can manage target designation based on hierarchy rules"""
    if admin_designation == 0:
        return True
    elif admin_designation == 1 and target_designation > 1:
        return True
    elif admin_designation == 2 and target_designation == 3:
        return True
    return False

# ============================================================================
# HELPER FUNCTIONS FOR CRUD OPERATIONS
# ============================================================================

@cache.memoize(timeout=3600)
def get_table_schema(db_name, table_name):
    """Fetch table schema from database securely (Refactored for centralization)"""
    # FIXED: Whitelist validation
    if db_name not in ALLOWED_DB_NAMES or table_name not in ALLOWED_TABLE_NAMES:
        secure_log(f"Attempt to access disallowed schema: {db_name}.{table_name}", 'info')
        raise ValueError("Invalid database or table name specified.")

    try:
        # Use centralized connection and explicit cursor closure via context manager
        # FIXED v14.0: Removed cursor_class parameter (not supported)
        _output = execute_query("""
                SELECT COLUMN_NAME, DATA_TYPE, COLUMN_KEY, COLUMN_DEFAULT, IS_NULLABLE, COLUMN_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
            """, (db_name, table_name), fetch_all=True)
        return _output
    except Exception as e:
        secure_log(f"Error fetching table schema for {db_name}.{table_name}: {e}", 'error')
        # Re-raise to be caught by caller for error rendering
        raise


def prepare_record_for_display(record, entity_config):
    """
    Decrypt and prepare record for display with image URLs.
    Hides password hashes and provides image preview URLs.
    """
    if not record: return record

    for key, value in list(record.items()):
        
        if value is None:
            record[key] = ''
            value = ''

        # 1. Handle password hash hiding
        if key in ['password_hash', 'password']:
            record[key] = '***HIDDEN***'
            continue

        # 2. Handle decryption (Updated for Centralized Function)
        if key in entity_config.get('encrypted_fields', []) and value:
            # Centralized decrypt_token returns None on failure, no try/except needed
            decrypted = decrypt_token(value)
            
            if decrypted:
                # Apply partial masking for sensitive decrypted fields
                if key in ['account_number', 'id_number'] and len(decrypted) > 4:
                     record[key] = f"****{decrypted[-4:]}" # Mask most of it
                else:
                     record[key] = decrypted
            else:
                record[key] = '***DECRYPT_ERROR***'

        # 3. Handle hiding/masking
        elif key in entity_config.get('hidden_fields', []) and value != '***HIDDEN***':
            if record.get(key) != '***DECRYPT_ERROR***' and not str(record.get(key)).startswith('****'):
                record[key] = '***HIDDEN_CONFIG***'

        # 4. Handle image fields - create preview URLs
        if key in entity_config.get('image_fields', []) and value and isinstance(value, str):
            record[f'{key}_original'] = value
            try:
                record[f'{key}_url'] = get_file_url(value)
            except Exception:
                record[f'{key}_url'] = None

        # 5. Handle datetime conversion
        if isinstance(value, datetime):
            record[key] = value.strftime('%Y-%m-%d %H:%M:%S')
        elif isinstance(value, timedelta):
             record[key] = str(value)

    return record


# prepare_record_for_save and generate_unique_id remain the same, 
# but internally, generate_unique_id will be called by handle_entity_create.

def prepare_record_for_save(form_data, entity_config, schema, is_update=False):
    """Encrypt and prepare record for database save, validating against schema."""
    processed_data = {}
    allowed_columns = {col['COLUMN_NAME'] for col in schema}

    for key, value in form_data.items():
        # 1. Skip fields not in schema
        if key not in allowed_columns and key != 'password':
            continue
        # 2. Skip fields marked as readonly or hidden
        if key in entity_config.get('readonly_fields', []) or key in entity_config.get('hidden_fields', []):
            continue
        # 3. Skip control fields
        if key in ['csrf_token', 'confirm_password', 'current_admin_password']:
            continue

        if isinstance(value, str):
            value = value.strip()

        # Handle empty/NULL logic
        is_nullable = next((col['IS_NULLABLE'] == 'YES' for col in schema if col['COLUMN_NAME'] == key), False)
        if value == '' and is_nullable:
            processed_data[key] = None
            continue
        elif value == '' and not is_nullable:
             if key != entity_config.get('pk_column'):
                 continue

        # Handle password
        if key == 'password':
            if value and value != '***HIDDEN***':
                valid, msg = validate_password_strength(value)
                if not valid:
                    raise ValueError(msg)
                processed_data['password_hash'] = generate_password_hash(value, method='pbkdf2:sha256:260000')
            continue

        # Handle encryption (Updated for Centralized Function)
        if key in entity_config.get('encrypted_fields', []):
            if value:
                encrypted = encrypt_token(str(value))
                if encrypted:
                    processed_data[key] = encrypted
                else:
                    # If centralized encryption returns None, it failed
                    raise ValueError(f"System encryption failed for field: {key}")
            else:
                 processed_data[key] = None
            continue

        if value is not None and value != '':
            processed_data[key] = value
        elif is_update and value == '':
             if key not in entity_config.get('encrypted_fields', []):
                  processed_data[key] = value

    return processed_data


def generate_unique_id(prefix, db_name, table_name, id_column):
    """Generate unique ID for new records securely (Refactored for centralization)"""
    # FIXED: Whitelist Validation
    if db_name not in ALLOWED_DB_NAMES or table_name not in ALLOWED_TABLE_NAMES:
        secure_log(f"Generate ID attempt on disallowed DB/Table: {db_name}.{table_name}", 'info')
        raise ValueError("Invalid database or table specified.")
    
    # FIXED: Whitelist column name
    entity_config = next((config for config in ENTITY_CRUD_MAP.values()
                          if config['db_name'] == db_name and config['table_name'] == table_name), None)
    if not entity_config or id_column != entity_config['pk_column']:
         secure_log(f"Generate ID attempt on non-PK or disallowed column: {table_name}.{id_column}", 'info')
         raise ValueError("Invalid ID column specified.")


    try:
        # Use execute_query for centralized DB access
        query = f"""
            SELECT `{id_column}` FROM `{db_name}`.`{table_name}`
            WHERE `{id_column}` LIKE %s
            ORDER BY `{id_column}` DESC
            LIMIT 1
        """
        like_pattern = f"{prefix}%"
        last_record = execute_query(query, (like_pattern,), fetch_one=True)

        last_id_str = last_record[id_column] if last_record else None
        next_num = 1

        if last_id_str and last_id_str.startswith(prefix):
             suffix = last_id_str[len(prefix):]
             match = re.search(r'(\d+)$', suffix)
             if match:
                 num_str = match.group(1)
                 try:
                     next_num = int(num_str) + 1
                     num_len = len(num_str)
                     base_prefix = last_id_str[:-num_len]
                     return f"{base_prefix}{next_num:0{num_len}d}"
                 except ValueError:
                     pass # Fall through to default generation

        # Fallback: Use simple prefix + sequential number (original logic)
        return f"{prefix}{next_num:05d}"

    except Exception as e:
        secure_log(f"Error generating unique ID for {prefix} in {db_name}.{table_name}: {e}", 'error')
        # Robust fallback on error: use timestamp + random
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        rand_part = random.randint(100, 999)
        return f"{prefix}{timestamp[:8]}_{rand_part}"


# ============================================================================
# AUTHENTICATION ROUTES
# ============================================================================

@admin_bp.route('/first_time_setup/', methods=['GET', 'POST'])
@limiter.limit("5 per hour")
def first_time_setup():
    """First-time setup - Supreme admin registration with THREE-STEP OTP"""
    
    # Check if Supreme admin already exists (Refactored)
    try:
        result = execute_query(
            "SELECT COUNT(*) as count FROM admin_base.admins WHERE designation = 0", 
            fetch_one=True
        )
        if result and result['count'] > 0:
            flash('Supreme admin already exists. Please login.', 'info')
            return redirect(url_for('sevak69.login'))
    except Exception as e:
        secure_log(f"DB error checking Supreme admin: {e}", 'error')
        flash('Database error during setup check.', 'error')
        return render_template('admin_first_time_setup.html')

    if request.method == 'POST':
        action = request.form.get('action', '')
        
        # FIX: Infer action if coming from the redirected Login route
        if not action and 'confirm_password' in request.form:
            action = 'create_account'

        # STEP 1: Email + Name submission
        if action == 'submit_email':
            # ... (OTP submission logic remains the same)
            email = request.form.get('email', '').lower().strip()
            name = request.form.get('name', '').strip()
            
            if not email or not name:
                flash('Email and name are required.', 'error')
                return render_template('admin_first_time_setup.html')
            
            otp_result = send_otp_email(email, user_type='admin', to_name=name, purpose='first_time_setup')
            
            if otp_result:
                flash('OTP sent to your email! Check your inbox.', 'info')
                log_admin_action(ACTION_CODES['otp_send'], 'first_time_setup', email, 'OTP sent')
                session['temp_setup_name'] = name
                session.modified = True 
                return render_template('admin_otp_verification.html', email=email, purpose='first_time_setup')
            else:
                flash('Failed to send OTP. Please try again.', 'error')
                return render_template('admin_first_time_setup.html')
        
        # STEP 2: OTP verification (remains the same)
        elif action == 'verify_otp':
            email = request.form.get('email', '').lower().strip()
            otp_code = request.form.get('otp_code', '').strip()

            if not email or not otp_code:
                flash('Email and OTP code required.', 'error')
                return render_template('admin_otp_verification.html', email=email, purpose='first_time_setup')
            
            result = email_service.verify_otp('admin', email, otp_code, 'first_time_setup')

            if not result['verified']:
                flash('Invalid or expired OTP code.', 'error')
                return render_template('admin_otp_verification.html', email=email, purpose='first_time_setup')
            
            session[f'otp_verified_admin_{email}_first_time_setup'] = True
            # Delete verified OTP from database
            delete_otp_from_database('admin', email, purpose='first_time_setup')
            
            session[f'otp_verified_time_admin_{email}'] = datetime.now().isoformat()
            session.modified = True 
            
            flash('Email verified! Now enter your password.', 'success')
            name = session.get('temp_setup_name', 'Supreme Admin')
            return render_template('admin_setup_password.html', email=email, name=name)
        
        # STEP 3: Create account (Refactored)
        elif action == 'create_account':
            email = request.form.get('email', '').lower().strip()
            name = session.get('temp_setup_name', '').strip()
            # Handle case where name/email are lost in redirect
            if not name or not email:
                 email = request.form.get('email', '').lower().strip()
                 name = request.form.get('name', 'Supreme Admin').strip()

            contact_number = request.form.get('contact_number', '').strip()
            password = request.form.get('password', '')
            confirm_password = request.form.get('confirm_password', '')

            if not all([email, password, confirm_password]):
                flash('Email and passwords are required.', 'error')
                return render_template('admin_setup_password.html', email=email, name=name)

            if len(password) < 8:
                flash('Password must be at least 8 characters long.', 'error')
                return render_template('admin_setup_password.html', email=email, name=name)

            if password != confirm_password:
                flash('Passwords do not match.', 'error')
                return render_template('admin_setup_password.html', email=email, name=name)

            if not session.get(f'otp_verified_admin_{email}_first_time_setup'):
                secure_log("Warning: OTP session missing during creation (possibly lost in redirect)", 'warning')

            # === ROBUST DATABASE INSERTION (Refactored) ===
            try:
                password_hash = generate_password_hash(password, method='pbkdf2:sha256:260000')
                admin_id = 'ADM_SUPREME_001'

                secure_log(f"Inserting Supreme Admin: {email}", 'info')
                
                row_count = execute_query(
                    """
                    INSERT INTO admin_base.admins
                    (admin_id, email, contact_number, password_hash, designation,
                     name, is_active, is_approved, date_joined)
                    VALUES (%s, %s, %s, %s, 0, %s, 1, 1, NOW())
                    """, 
                    (admin_id, email, contact_number, password_hash, name),
                    commit=True
                )
                
                if row_count == 0:
                    raise Exception("Database reported 0 rows inserted.")

                # Cleanup
                session.pop(f'otp_verified_admin_{email}_first_time_setup', None)
                session.pop(f'otp_verified_time_admin_{email}', None)
                session.pop('temp_setup_name', None)
                session.modified = True
                
                log_admin_action(ACTION_CODES['first_time_setup'], 'admin', admin_id, 'Supreme admin created')
                flash('Supreme admin account created successfully! Please login.', 'success')
                return redirect(url_for('sevak69.login'))

            except Exception as e:
                secure_log(f"First-time setup DB ERROR: {str(e)}", 'error')
                flash(f'Setup failed due to database error: {str(e)}', 'error')
                return render_template('admin_setup_password.html', email=email, name=name)

    return render_template('admin_first_time_setup.html')


@admin_bp.route('/login/', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    """Secure admin login with 2 Steps: 1. Email/Password -> 2. Email OTP -> 3. Login"""
    
    # ====================================================================
    # TRAFFIC COP: REROUTE MISDIRECTED REQUESTS (MUST BE FIRST)
    # ====================================================================
    # We check this BEFORE 'admin_id' in session to allow registration/setup flows
    # to proceed even if a stale session exists or user is testing while logged in.
    if request.method == 'POST':
        # 1. Route Password Setup (Setup/Registration)
        if 'confirm_password' in request.form:
            secure_log("Routing misdirected Password Setup", 'info')
            if session.get('temp_registration') or request.form.get('action') == 'submit_request':
                return register_request()
            return first_time_setup()

        # 2. Route Registration Final Submit
        if request.form.get('action') == 'submit_request':
            secure_log("Routing misdirected Registration Final Submit", 'info')
            return register_request()

        # 3. Route OTP Verification based on 'purpose' field
        purpose = request.form.get('purpose')
        if purpose == 'registration':
            secure_log("Routing misdirected Registration OTP", 'info')
            return register_request()
        elif purpose == 'first_time_setup':
            secure_log("Routing misdirected Setup OTP", 'info')
            return first_time_setup()
    # ====================================================================

    # NOW check if already logged in (Only if it's a genuine login attempt)
    # CRITICAL FIX: Validate session before redirecting to prevent loop
    if 'admin_id' in session:
        # Validate session security before allowing redirect
        if validate_session_security():
            return redirect(url_for('sevak69.dashboard'))
        else:
            # Session is invalid, clear it to allow fresh login
            clear_admin_session()

    if request.method == 'POST':
        action = request.form.get('action', '')
        email = request.form.get('email', '').lower().strip()
        password = request.form.get('password', '')
        otp_code = request.form.get('otp_code', '').strip()

        # --- STEP 1: Email and Password Submission ---
        if action == 'submit_credentials' or (action == '' and password):
            if not email or not password:
                flash('Email and password are required.', 'error')
                return render_template('admin_login.html', email=email)

            try:
                # Use execute_query for centralized DB access
                admin = execute_query(
                    """
                    SELECT admin_id, password_hash, name, is_active, designation, is_approved
                    FROM admin_base.admins
                    WHERE email = %s
                    """,
                    (email,),
                    fetch_one=True
                )
            except Exception as e:
                secure_log(f"Login DB Error: {e}", 'error')
                flash('System error during login.', 'error')
                return render_template('admin_login.html', email=email)

            # Basic validation
            if not admin or not admin['is_active']:
                flash('Invalid credentials or account does not exist.', 'error')
                log_admin_action(ACTION_CODES['login_fail'], 'login', email, 'Email not found/Deactivated')
                return render_template('admin_login.html', email=email)

            if not check_password_hash(admin['password_hash'], password):
                flash('Invalid credentials.', 'error')
                log_admin_action(ACTION_CODES['login_fail'], 'login', admin['admin_id'], 'Wrong password')
                return render_template('admin_login.html', email=email)

            # Check approval status
            if admin['designation'] != 0 and not admin.get('is_approved', False):
                flash('Your account is pending approval from the Supreme admin.', 'warning')
                return render_template('admin_login.html', email=email)

            # --- Credentials verified! Proceed directly to Email OTP Step (Step 2) ---
            otp_result = send_otp_email(email, user_type='admin', to_name=admin['name'], purpose='login')

            if otp_result:
                session['temp_admin_auth'] = {
                    'admin_id': admin['admin_id'],
                    'email': email,
                    'name': admin['name'],
                    'designation': admin['designation']
                }
                session.modified = True
                flash('Email and password verified! OTP sent to your email.', 'info')
                log_admin_action(ACTION_CODES['otp_send'], 'login', admin['admin_id'], 'Login OTP sent')
                return render_template('admin_otp_verification.html', email=email, purpose='login')
            else:
                flash('Failed to send OTP. Please try again.', 'error')
                return render_template('admin_login.html', email=email)

        # --- STEP 2: Email OTP Verification (Final Auth) ---
        elif action == 'verify_otp':
            # This block now ONLY handles actual Login OTPs, because Registration OTPs
            # were caught by the Traffic Cop at the top.
            temp_auth_data = session.get('temp_admin_auth')

            if not temp_auth_data or temp_auth_data['email'] != email:
                flash('Login session expired. Please log in again.', 'error')
                return redirect(url_for('sevak69.login'))

            admin_id = temp_auth_data['admin_id']
            admin_name = temp_auth_data['name']
            
            result = email_service.verify_otp('admin', email, otp_code, 'login')

            if not result['verified']:
                flash('Invalid or expired verification code.', 'error')
                log_admin_action(ACTION_CODES['otp_verify_fail'], 'login', admin_id, 'Email OTP verification failed')
                return render_template('admin_otp_verification.html', email=email, purpose='login')

            # Delete verified OTP from database
            delete_otp_from_database('admin', email, purpose='login')
            
            # --- Verification Successful ---
            log_admin_action(ACTION_CODES['otp_verify'], 'login', admin_id, 'Email OTP successful')
            
            # Reset login attempts
            execute_query(
                "UPDATE admin_base.admins SET login_attempts=0, locked_until=NULL, last_login=NOW() WHERE admin_id=%s",
                (admin_id,),
                commit=True
            )

            # Set session
            clear_admin_session()
            session['admin_id'] = admin_id
            session['admin_name'] = admin_name
            session['admin_designation'] = temp_auth_data['designation']
            session['admin_email'] = email
            session.permanent = True
            session['fingerprint'] = get_session_fingerprint()
            session['last_activity'] = datetime.now().isoformat()
            
            log_admin_action(ACTION_CODES['login'], 'admin', admin_id, 'Successful login')
            flash(f'Welcome {admin_name}!', 'success')

            next_url = request.args.get('next')
            if next_url and urlparse(next_url).netloc == urlparse(request.host_url).netloc:
                return redirect(next_url)
            else:
                return redirect(url_for('sevak69.dashboard'))
    
    return render_template('admin_login.html')


@admin_bp.route('/logout/')
@limiter.limit("10 per minute")
@admin_login_required
def logout():
    """Logout admin"""
    admin_id = session.get('admin_id')
    log_admin_action(ACTION_CODES['logout'], 'admin', admin_id, 'Admin logged out')
    clear_admin_session()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('sevak69.login'))

# ============================================================================
# REGISTRATION REQUEST MANAGEMENT (LOGIN REQUIRED)
# ============================================================================

@admin_bp.route('/register_request/', methods=['GET', 'POST'])
@limiter.limit("5 per hour")
@admin_login_required
def register_request():
    """Admin registration request with Robust Session Recovery"""
    
    if request.method == 'POST':
        action = request.form.get('action', '')
        
        # STEP 1: Email + Details submission - send OTP
        if action == 'submit_email':
            email = request.form.get('email', '').lower().strip()
            name = request.form.get('name', '').strip()
            contact_number = request.form.get('contact_number', '').strip()
            reason = request.form.get('reason', '').strip()
            
            try:
                requested_designation = int(request.form.get('designation', 3))
            except: requested_designation = 3

            if not all([email, name, contact_number, reason]):
                flash('All fields are required.', 'error')
                return render_template('admin_register_request.html', designation_names=DESIGNATION_NAMES)

            # Check duplicate email
            exists = execute_query("SELECT email FROM admin_base.admins WHERE email=%s", (email,), fetch_one=True)
            if exists:
                flash('Email already registered. Please login.', 'error')
                return redirect(url_for('sevak69.login'))

            if send_otp_email(email, user_type='admin', to_name=name, purpose='registration'):
                flash('OTP sent to your email.', 'info')
                # Explicitly save session
                session['temp_registration'] = {
                    'email': email, 'name': name, 'contact_number': contact_number,
                    'reason': reason, 'requested_designation': requested_designation
                }
                session.modified = True 
                return render_template('admin_otp_verification.html', email=email, purpose='registration')
            else:
                flash('Failed to send OTP.', 'error')
                return render_template('admin_register_request.html', designation_names=DESIGNATION_NAMES)

        # STEP 2: OTP verification
        elif action == 'verify_otp':
            email = request.form.get('email', '').lower().strip()
            otp_code = request.form.get('otp_code', '').strip()

            result = email_service.verify_otp('admin', email, otp_code, 'registration')
            if not result['verified']:
                flash('Invalid OTP.', 'error')
                return render_template('admin_otp_verification.html', email=email, purpose='registration')

            session[f'otp_verified_admin_{email}_registration'] = True
            # Delete verified OTP from database
            delete_otp_from_database('admin', email, purpose='registration')
            
            session.modified = True
            
            # Retrieve data safely
            temp_data = session.get('temp_registration', {})
            if not temp_data:
                flash('Session expired. Please register again.', 'error')
                return redirect(url_for('sevak69.register_request'))

            return render_template('admin_register_request_confirm.html',
                                 email=email, name=temp_data.get('name'),
                                 contact_number=temp_data.get('contact_number'),
                                 reason=temp_data.get('reason'),
                                 requested_designation=temp_data.get('requested_designation'),
                                 designation_names=DESIGNATION_NAMES)

        # STEP 3: Submit registration request (With Recovery Logic)
        elif action == 'submit_request':
            email = request.form.get('email', '').lower().strip()
            
            # A. Attempt to get data from Session
            temp_data = session.get('temp_registration')
            
            # B. Data Recovery Strategy: If session is empty, look in the Form (Hidden Inputs)
            if not temp_data:
                name_form = request.form.get('name')
                contact_form = request.form.get('contact_number')
                
                if name_form and contact_form: # If hidden fields are present
                    secure_log(f"Recovering registration data from Form for {email}", 'info')
                    try:
                        desig_val = int(request.form.get('designation', 3))
                    except: desig_val = 3
                    
                    temp_data = {
                        'name': name_form,
                        'contact_number': contact_form,
                        'reason': request.form.get('reason', ''),
                        'requested_designation': desig_val
                    }

            # C. Final Validation
            if not temp_data:
                flash('Session data lost. Please fill the form again.', 'error')
                return redirect(url_for('sevak69.register_request'))

            try:
                request_id = f"REQ_{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(100, 999)}"
                
                # Using CORRECT table 'admin_base.registration_requests'
                execute_query(
                    """
                    INSERT INTO admin_base.registration_requests
                    (request_id, name, email, contact_number, reason, status, requested_designation, requested_by)
                    VALUES (%s, %s, %s, %s, %s, 'pending', %s, 'PUBLIC_USER')
                    """, 
                    (
                        request_id, 
                        temp_data['name'], 
                        email, 
                        temp_data['contact_number'], 
                        temp_data['reason'], 
                        temp_data['requested_designation']
                    ),
                    commit=True
                )

                # Cleanup only on success
                session.pop('temp_registration', None)
                session.pop(f'otp_verified_admin_{email}_registration', None)
                session.modified = True

                log_admin_action(ACTION_CODES['registration_request'], 'registration', email, 'Request submitted')

                flash('Registration request submitted successfully! Awaiting Supreme admin approval.', 'success')
                return redirect(url_for('sevak69.login'))

            except Exception as e:
                secure_log(f"Registration request DB ERROR: {str(e)}", 'error')
                flash(f'System error during submission: {str(e)}', 'error')
                # Fallback: keep them on confirmation page to retry
                return render_template('admin_register_request_confirm.html',
                                     email=email, name=temp_data.get('name'),
                                     contact_number=temp_data.get('contact_number'),
                                     reason=temp_data.get('reason'),
                                     requested_designation=temp_data.get('requested_designation'),
                                     designation_names=DESIGNATION_NAMES)

    return render_template('admin_register_request.html', designation_names=DESIGNATION_NAMES)


@admin_bp.route('/registration_requests/')
@limiter.limit("10 per minute")
@admin_login_required
@permission_required(0)  # SUPREME ONLY
def registration_requests():
    """View and manage registration requests (Supreme only) (Refactored)"""
    status_filter = request.args.get('status', 'pending')
    if status_filter not in ['pending', 'approved', 'rejected']: status_filter = 'pending'

    try:
        requests_data = execute_query(
            """
            SELECT rr.*, a.name as requested_by_name
            FROM admin_base.registration_requests rr
            LEFT JOIN admin_base.admins a ON rr.requested_by = a.admin_id
            WHERE rr.status = %s
            ORDER BY rr.created_at DESC
            """,
            (status_filter,),
            fetch_all=True
        )

        return render_template('admin_registration_requests.html',
                               requests=requests_data,
                               status_filter=status_filter,
                               DESIGNATION_NAMES=DESIGNATION_NAMES,
                               DESIGNATION_LIMITS=DESIGNATION_LIMITS)

    except Exception as e:
        secure_log(f"Error loading registration requests: {str(e)}", 'error')
        flash('Error loading requests.', 'error')
        return render_template('admin_registration_requests.html',
                               requests=[], status_filter=status_filter,
                               DESIGNATION_NAMES=DESIGNATION_NAMES,
                               DESIGNATION_LIMITS=DESIGNATION_LIMITS)


@admin_bp.route('/approve_registration/<request_id>', methods=['POST'])
@admin_login_required
@permission_required(0)  # SUPREME ONLY
@limiter.limit("5 per minute")
def approve_registration(request_id):
    """
    Approve registration request using a single atomic Stored Procedure.
    Merges 5 DB queries into 1 for performance and safety.
    """
    # --- 1. Security Check (Must happen in Python) ---
    current_password = request.form.get('current_admin_password', '').strip()
    admin_data = execute_query(
        "SELECT password_hash FROM admin_base.admins WHERE admin_id = %s",
        (session['admin_id'],),
        fetch_one=True
    )

    if not admin_data or not check_password_hash(admin_data['password_hash'], current_password):
        flash('Authentication failed: Incorrect Admin Password.', 'error')
        return redirect(url_for('sevak69.registration_requests'))

    # --- 2. Prepare Data ---
    try:
        try:
            designation = int(request.form.get('designation', 3))
        except (ValueError, TypeError):
            flash('Invalid designation format.', 'error')
            return redirect(url_for('sevak69.registration_requests'))

        new_password = request.form.get('password', '').strip()
        if not new_password or len(new_password) < 8:
            flash('New admin password must be at least 8 characters long.', 'error')
            return redirect(url_for('sevak69.registration_requests'))

        password_hash = generate_password_hash(new_password, method='pbkdf2:sha256:260000')
        limit = DESIGNATION_LIMITS.get(designation, 999)
        prefix = DESIGNATION_NAMES[designation].upper()

        # TiDB Compatible: Replaced ProcessAdminApproval stored procedure
        # with Python-level transaction logic.
        with get_db_connection() as (conn, cursor):
            # 1. Check designation limit
            cursor.execute(
                "SELECT COUNT(*) AS cnt FROM admin_base.admins WHERE designation = %s AND is_active = 1",
                (designation,)
            )
            cnt_row = cursor.fetchone()
            current_count = cnt_row.get('cnt', 0) if cnt_row else 0
            if current_count >= limit:
                flash(f'Limit reached for {DESIGNATION_NAMES[designation]} (Max: {limit}).', 'error')
                return redirect(url_for('sevak69.registration_requests'))

            # 2. Fetch the registration request
            cursor.execute(
                "SELECT * FROM admin_base.registration_requests WHERE request_id = %s AND status = 'pending'",
                (request_id,)
            )
            req = cursor.fetchone()
            if not req:
                flash('Request not found or already processed.', 'error')
                return redirect(url_for('sevak69.registration_requests'))

            email = req['email']
            name = req['name']

            # 3. Generate a new admin_id
            cursor.execute(
                "SELECT admin_id FROM admin_base.admins WHERE admin_id LIKE %s ORDER BY admin_id DESC LIMIT 1",
                (f"{prefix}%",)
            )
            last_row = cursor.fetchone()
            if last_row:
                import re as _re
                m = _re.search(r'(\d+)$', last_row['admin_id'])
                next_num = (int(m.group(1)) + 1) if m else 1
            else:
                next_num = 1
            new_admin_id = f"{prefix}_{next_num:05d}"

            # 4. Insert the new admin
            cursor.execute(
                """
                INSERT INTO admin_base.admins
                (admin_id, email, password_hash, designation, name, is_active, is_approved,
                 hoster_id, date_joined)
                VALUES (%s, %s, %s, %s, %s, 1, 1, %s, NOW())
                """,
                (new_admin_id, email, password_hash, designation, name, session['admin_id'])
            )

            # 5. Mark the request as approved
            cursor.execute(
                """
                UPDATE admin_base.registration_requests
                SET status = 'approved', approved_by = %s, approved_at = NOW()
                WHERE request_id = %s
                """,
                (session['admin_id'], request_id)
            )
            conn.commit()

        log_admin_action(ACTION_CODES['admin_approve'], 'admin', new_admin_id,
                         f'Approved {email} as {DESIGNATION_NAMES[designation]}')
        try:
            send_admin_welcome_email(email, name, new_admin_id, new_password)
        except Exception as e:
            secure_log(f"Email delivery failed for {email}: {e}", 'warning')
            flash(f'Admin created ({new_admin_id}), but welcome email failed.', 'warning')
            return redirect(url_for('sevak69.registration_requests'))

        flash(f'Registration approved! Admin {name} created with ID {new_admin_id}.', 'success')

    except Exception as e:
        secure_log(f"Approve registration critical error: {str(e)}", 'error')
        flash(f'System error during approval: {str(e)}', 'error')

    return redirect(url_for('sevak69.registration_requests'))


# TiDB Compatible: call_stored_procedure removed, using direct SQL.

@admin_bp.route('/reject_registration/<request_id>', methods=['POST'])
@admin_login_required
@permission_required(0)  # SUPREME ONLY
@limiter.limit("5 per minute")
def reject_registration(request_id):
    """
    Reject registration request using a single atomic Stored Procedure.
    Adapts to schema by using 'approved_by' to store the rejector ID.
    """
    reason = request.form.get('rejection_reason', '').strip()
    
    if not reason:
        flash('Rejection reason is required.', 'error')
        return redirect(url_for('sevak69.registration_requests'))

    try:
        # TiDB Compatible: Replaced RejectRegistrationRequest stored procedure
        # with direct SQL UPDATE + Python post-processing.
        req = execute_query(
            "SELECT email, name FROM admin_base.registration_requests WHERE request_id = %s AND status = 'pending'",
            (request_id,),
            fetch_one=True
        )
        if not req:
            flash('Request not found or already processed.', 'error')
            return redirect(url_for('sevak69.registration_requests'))

        email = req['email']
        name = req['name']

        execute_query(
            """
            UPDATE admin_base.registration_requests
            SET status = 'rejected',
                approved_by = %s,
                approved_at = NOW(),
                rejection_reason = %s
            WHERE request_id = %s AND status = 'pending'
            """,
            (session['admin_id'], reason, request_id),
            commit=True
        )

        log_admin_action(ACTION_CODES['admin_reject'], 'registration_request', request_id,
                         f'Rejected request for {email}. Reason: {reason}')
        try:
            send_admin_rejection_email(email, name, reason)
            flash(f'Request rejected and email sent to {email}.', 'success')
        except Exception as e:
            secure_log(f"Rejection email failed for {email}: {e}", 'warning')
            flash('Request rejected, but email delivery failed.', 'warning')

    except Exception as e:
        secure_log(f"Reject registration critical error: {str(e)}", 'error')
        flash(f'System error during rejection: {str(e)}', 'error')

    return redirect(url_for('sevak69.registration_requests'))

# ============================================================================
# BANK ACCOUNT VERIFICATION ROUTES
# ============================================================================

@admin_bp.route('/bank_verifications/')
@admin_login_required
@limiter.limit("10 per minute")
@permission_required(1)
def bank_verifications():
    """View all bank accounts pending verification (Refactored)"""
    status_filter = request.args.get('status', '0')
    if status_filter not in ['0', '1', '2', '3']: status_filter = '0'

    try:
        bank_accounts = execute_query(
            """
            SELECT bi.*, c.creator_name, c.email as creator_email
            FROM creator_base.creator_bank_info bi
            JOIN creator_base.creators c ON bi.channel_id = c.channel_id
            WHERE bi.verification_status = %s
            ORDER BY bi.created_at DESC
            """,
            (status_filter,),
            fetch_all=True
        )

        status_map = {'0': 'Pending Verification', '1': 'Verified', '2': 'Rejected', '3': 'Under Review'}

        for account in bank_accounts:
            # DECRYPTION: Use centralized function
            # Centralized decrypt_token returns None on failure
            decrypted_acc = decrypt_token(account.get('account_number'))
            decrypted_id = decrypt_token(account.get('id_number'))
            
            # Masking logic
            if decrypted_acc:
                account['account_number_masked'] = f"****{decrypted_acc[-4:]}" if len(decrypted_acc) > 4 else '****'
            else:
                account['account_number_masked'] = 'Error/Encrypted'

            if decrypted_id:
                account['id_number_masked'] = f"****{decrypted_id[-4:]}" if len(decrypted_id) > 4 else '****'
            else:
                account['id_number_masked'] = 'Error/Encrypted'

        return render_template('admin_bank_verifications.html',
                               bank_accounts=bank_accounts,
                               status_filter=status_filter,
                               status_map=status_map)

    except Exception as e:
        secure_log(f"Error loading bank verifications: {str(e)}", 'error')
        flash('Error loading bank accounts list.', 'error')
        return render_template('admin_bank_verifications.html', bank_accounts=[], status_filter=status_filter, status_map={})


@admin_bp.route('/bank_verify/<int:account_id>/')
@limiter.limit("10 per minute")
@admin_login_required
@permission_required(1)
def bank_verify_view(account_id):
    """View bank account details side-by-side with documents for verification"""
    try:
        account = execute_query(
            """
            SELECT bi.*, c.creator_name, c.email as creator_email, c.channel_name
            FROM creator_base.creator_bank_info bi
            JOIN creator_base.creators c ON bi.channel_id = c.channel_id
            WHERE bi.id = %s
            """,
            (account_id,),
            fetch_one=True
        )

        if not account:
            flash('Bank account not found.', 'error')
            return redirect(url_for('sevak69.bank_verifications'))

        # DECRYPTION: Full reveal for admin
        account['account_number_decrypted'] = decrypt_token(account.get('account_number')) or "[Decryption Failed]"
        account['id_number_decrypted'] = decrypt_token(account.get('id_number')) or "[Decryption Failed]"

        # Create URLs for viewing encrypted documents
        account['id_image_url'] = url_for('sevak69.view_bank_document', account_id=account_id, doc_type='id_image') if account.get('id_image_path') else None
        account['bank_document_url'] = url_for('sevak69.view_bank_document', account_id=account_id, doc_type='bank_statement') if account.get('bank_document_path') else None

        status_map = {0: 'Pending Verification', 1: 'Verified', 2: 'Rejected', 3: 'Under Review'}
        account['status_display'] = status_map.get(account['verification_status'], 'Unknown')

        return render_template('admin_bank_verify_view.html', account=account)

    except Exception as e:
        secure_log(f"Error loading bank account {account_id} for verification: {str(e)}", 'error')
        flash('Error loading bank account details.', 'error')
        return redirect(url_for('sevak69.bank_verifications'))


@admin_bp.route('/bank_document/<int:account_id>/<doc_type>/')
@admin_login_required
@limiter.limit("100 per minute")  # Increased for image loading
@permission_required(1)
def view_bank_document(account_id, doc_type):
    """View encrypted bank document (decrypt on-the-fly) with auto-detection (Refactored for GCS/Local)"""
    if doc_type not in ['id_image', 'bank_statement']:
        flash('Invalid document type specified.', 'error')
        abort(404)

    try:
        column_name = 'id_image_path' if doc_type == 'id_image' else 'bank_document_path'

        # Retrieve the path from the creator_bank_info table
        bank_info = execute_query(
            f"SELECT {column_name} FROM creator_base.creator_bank_info WHERE id = %s",
            (account_id,),
            fetch_one=True
        )
        doc_path = bank_info.get(column_name) if bank_info else None

        if not doc_path:
            flash('Document path not found in bank info record.', 'error')
            return redirect(url_for('sevak69.bank_verify_view', account_id=account_id))

        # --- CENTRALIZED FILE LOAD AND DECRYPT ---
        # download_file_content handles GCS/Local and uses the cipher automatically
        try:
            decrypted_data = download_file_content(doc_path, decrypt=True)
        except Exception as decrypt_error:
            secure_log(f"Decryption error for account {account_id}: {decrypt_error}", 'error')
            decrypted_data = None

        if not decrypted_data:
            secure_log(f"Failed to decrypt or find document for account {account_id} at {doc_path}", 'error')
            # Return a placeholder image instead of redirecting
            from flask import Response
            placeholder_svg = '''<svg width="400" height="300" xmlns="http://www.w3.org/2000/svg">
                <rect width="400" height="300" fill="#f3f4f6"/>
                <text x="200" y="150" font-family="Arial" font-size="16" fill="#6b7280" text-anchor="middle">
                    Failed to decrypt document
                </text>
            </svg>'''
            return Response(placeholder_svg, mimetype='image/svg+xml')

        # Log document view
        log_admin_action(ACTION_CODES['document_view'], 'bank_document', str(account_id), f'Viewed {doc_type} by {g.admin_name}')

        # --- FIX: Detect file type from Magic Numbers (Header Bytes) ---
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
            # Fallback logic if magic number is unknown
            mimetype = 'application/octet-stream'
            ext = 'dat'

        download_name = f"{doc_type}_{account_id}.{ext}"

        return send_file(
            io.BytesIO(decrypted_data),
            mimetype=mimetype,
            as_attachment=False, # Open inline in browser
            download_name=download_name
        )

    except Exception as e:
        secure_log(f"Error viewing bank document for account {account_id}: {str(e)}", 'error')
        flash('Error accessing document.', 'error')
        return redirect(url_for('sevak69.bank_verify_view', account_id=account_id))


@admin_bp.route('/bank_verify/<int:account_id>/approve/', methods=['POST'])
@admin_login_required
@permission_required(1)
@limiter.limit("15 per minute")
def approve_bank_account(account_id):
    """
    Bank account approval — TiDB Compatible.
    Replaced ApproveAndActivateBankAccount stored procedure with Python transaction.
    """
    admin_id = session.get('admin_id')

    try:
        if not admin_id:
            abort(403)

        with get_db_connection() as (conn, cursor):
            # 1. Check bank account exists and is in pending state
            cursor.execute(
                """
                SELECT id, channel_id, verification_status
                FROM creator_base.creator_bank_info
                WHERE id = %s
                """,
                (account_id,)
            )
            bank = cursor.fetchone()

            if not bank:
                flash('Bank account not found.', 'error')
                return redirect(url_for('sevak69.bank_verifications'))

            if bank['verification_status'] != 0:
                flash('Bank account is already verified or rejected.', 'warning')
                return redirect(url_for('sevak69.bank_verify_view', account_id=account_id))

            channel_id = bank['channel_id']

            # 2. Deactivate all other bank accounts for this channel
            cursor.execute(
                """
                UPDATE creator_base.creator_bank_info
                SET is_active = 0
                WHERE channel_id = %s AND id != %s
                """,
                (channel_id, account_id)
            )

            # 3. Approve and activate this bank account
            cursor.execute(
                """
                UPDATE creator_base.creator_bank_info
                SET verification_status = 1,
                    is_active = 1,
                    verified_by = %s,
                    verified_at = NOW()
                WHERE id = %s
                """,
                (admin_id, account_id)
            )

            # 4. Log the verification event in bank_verifications table
            cursor.execute(
                """
                INSERT INTO admin_base.bank_verifications
                (channel_id, bank_info_id, verified_by, verification_status,
                 documents_verified, id_verified, bank_details_verified)
                VALUES (%s, %s, %s, 1, 1, 1, 1)
                """,
                (channel_id, account_id, admin_id)
            )
            conn.commit()

        log_admin_action(ACTION_CODES['bank_verify'], 'bank_account', str(account_id),
                         f'Bank account verified & activated by {g.admin_name}')
        flash('Bank account verified and set as active payment method!', 'success')
        return redirect(url_for('sevak69.bank_verifications'))

    except Exception as e:
        secure_log(f"Approval error: {str(e)}", 'error')
        flash('System error during approval.', 'error')
        return redirect(url_for('sevak69.bank_verify_view', account_id=account_id))


@admin_bp.route('/bank_verify/<int:account_id>/reject/', methods=['POST'])
@admin_login_required
@permission_required(1)
@limiter.limit("10 per minute")
def reject_bank_account(account_id):
    """Reject bank account verification with reason (Refactored for centralization)"""
    rejection_reason = request.form.get('rejection_reason', '').strip()

    if not rejection_reason or len(rejection_reason) > 500:
        flash('Please provide a rejection reason (max 500 chars).', 'error')
        return redirect(url_for('sevak69.bank_verify_view', account_id=account_id))

    try:
        row_count = execute_query(
            """
            UPDATE creator_base.creator_bank_info
            SET verification_status = 2, verified_by = %s, verified_at = NOW(),
                rejection_reason = %s, is_active = 0, -- Deactivate on rejection
                updated_by = %s, updated_at = NOW()
            WHERE id = %s AND verification_status IN (0, 3)
            """,
            (session['admin_id'], rejection_reason, session['admin_id'], account_id),
            commit=True
        )

        if row_count == 0:
             flash('Account not in pending/review state or not found.', 'warning')
        else:
             log_admin_action(ACTION_CODES['bank_reject'], 'bank_account', str(account_id), f'Bank account rejected by {g.admin_name}')
             flash('Bank account rejected. Reason recorded.', 'success')

        return redirect(url_for('sevak69.bank_verifications', status='2'))

    except Exception as e:
        secure_log(f"Error rejecting bank account {account_id}: {str(e)}", 'error')
        flash('Error rejecting bank account.', 'error')
        return redirect(url_for('sevak69.bank_verify_view', account_id=account_id))


@admin_bp.route('/bank_verify/<int:account_id>/freeze/', methods=['POST'])
@admin_login_required
@permission_required(0)
@limiter.limit("5 per minute")
def freeze_bank_account(account_id):
    """Freeze bank account (emergency action) (Refactored for centralization)"""
    try:
        row_count = execute_query(
            """
            UPDATE creator_base.creator_bank_info
            SET is_frozen = 1, is_active = 0,
                updated_by = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (session['admin_id'], account_id),
            commit=True
        )

        if row_count == 0: flash('Bank account not found.', 'error')
        else:
            log_admin_action(ACTION_CODES['bank_freeze'], 'bank_account', str(account_id), f'Bank account FROZEN by {g.admin_name}')
            flash('Bank account frozen successfully! All payments disabled.', 'warning')

    except Exception as e:
        secure_log(f"Error freezing bank account {account_id}: {str(e)}", 'error')
        flash('Error freezing bank account.', 'error')
    
    return redirect(url_for('sevak69.bank_verify_view', account_id=account_id))

@admin_bp.route('/bank_verify/<int:account_id>/unfreeze/', methods=['POST'])
@admin_login_required
@permission_required(0)
@limiter.limit("5 per minute")
def unfreeze_bank_account(account_id):
    """Unfreeze bank account (Refactored for centralization)"""
    try:
        row_count = execute_query(
            """
            UPDATE creator_base.creator_bank_info
            SET is_frozen = 0, updated_by = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (session['admin_id'], account_id),
            commit=True
        )

        if row_count == 0: flash('Bank account not found.', 'error')
        else:
             log_admin_action(ACTION_CODES['bank_unfreeze'], 'bank_account', str(account_id), f'Bank account UNFROZEN by {g.admin_name}')
             flash('Bank account unfrozen successfully!', 'success')

    except Exception as e:
        secure_log(f"Error unfreezing bank account {account_id}: {str(e)}", 'error')
        flash('Error unfreezing bank account.', 'error')
    
    return redirect(url_for('sevak69.bank_verify_view', account_id=account_id))

@admin_bp.route('/bank_verify/<int:account_id>/toggle_active/', methods=['POST'])
@admin_login_required
@permission_required(1)
@limiter.limit("20 per minute")
def toggle_bank_account_active(account_id):
    """Activate/Deactivate bank account (AJAX endpoint) (Refactored for centralization)"""
    try:
        account = execute_query(
            """
            SELECT is_active, is_frozen, verification_status
            FROM creator_base.creator_bank_info
            WHERE id = %s
            """,
            (account_id,),
            fetch_one=True
        )

        if not account:
            return jsonify({'success': False, 'message': 'Bank account not found.'}), 404
        if account['is_frozen']:
            return jsonify({'success': False, 'message': 'Cannot activate/deactivate a frozen account.'}), 400
        if account['verification_status'] != 1:
            return jsonify({'success': False, 'message': 'Can only activate verified accounts.'}), 400

        new_status = not account['is_active']
        action_code = ACTION_CODES['bank_activate'] if new_status else ACTION_CODES['bank_deactivate']

        row_count = execute_query(
            """
            UPDATE creator_base.creator_bank_info
            SET is_active = %s, updated_by = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (new_status, session['admin_id'], account_id),
            commit=True
        )

        if row_count == 0:
            return jsonify({'success': False, 'message': 'Failed to update account status.'}), 500
        else:
            log_admin_action(action_code, 'bank_account', str(account_id), f'Bank account {"activated" if new_status else "deactivated"} by {g.admin_name}')
            return jsonify({
                'success': True,
                'message': f'Bank account {"activated" if new_status else "deactivated"} successfully!',
                'new_status': new_status,
                'status_display': 'Active' if new_status else 'Inactive'
            })

    except Exception as e:
        secure_log(f"Error toggling bank account {account_id} status: {str(e)}", 'error')
        return jsonify({'success': False, 'message': 'Error updating status.'}), 500


# ============================================================================
# DASHBOARD ROUTE WITH EARNINGS ANALYSIS
# ============================================================================

# Ensure 'get_db_connection' is imported from 'youcert' at the top of the file

@admin_bp.route('/dashboard/')
@admin_bp.route('/')
@limiter.limit("15 per minute")
@admin_login_required
def dashboard():
    """
    Optimized Dashboard: Fetches Stats, Logs, and Alerts.
    TiDB Compatible: Replaced GetFullAdminDashboardData stored procedure
    with individual direct SQL queries.
    """
    try:
        is_supreme = (g.admin_designation == 0)

        # --- Query 1: Basic Stats ---
        stats = execute_query("""
            SELECT
                (SELECT COUNT(*) FROM user_base.user WHERE is_active = 1) AS active_users,
                (SELECT COUNT(*) FROM user_base.user) AS total_users,
                (SELECT COUNT(*) FROM creator_base.creators WHERE is_active = 1) AS active_creators,
                (SELECT COUNT(*) FROM creator_base.creators) AS total_creators,
                (SELECT COUNT(*) FROM exam.listed_exams WHERE is_active = 1) AS active_exams,
                (SELECT COUNT(*) FROM exam.purchased_exams) AS total_purchases,
                (SELECT COALESCE(SUM(amount_paid), 0) FROM exam.purchased_exams WHERE payment_status = 'completed') AS total_revenue,
                (SELECT COUNT(*) FROM creator_base.creator_bank_info WHERE verification_status = 0) AS pending_verifications
        """, fetch_one=True) or {}

        # --- Query 2: Monthly Stats ---
        monthly_stats = execute_query("""
            SELECT
                COUNT(*) AS monthly_sales,
                COALESCE(SUM(amount_paid), 0) AS monthly_revenue
            FROM exam.purchased_exams
            WHERE payment_status = 'completed'
              AND YEAR(payment_date) = YEAR(CURDATE())
              AND MONTH(payment_date) = MONTH(CURDATE())
        """, fetch_one=True) or {}

        # --- Query 3: Recent Admin Activities ---
        if is_supreme:
            recent_activities = execute_query("""
                SELECT admin_id, action_code, target_type, target_id, details, ip_address, timestamp
                FROM admin_base.admin_logs
                ORDER BY timestamp DESC
                LIMIT 20
            """, fetch_all=True) or []
        else:
            recent_activities = execute_query("""
                SELECT admin_id, action_code, target_type, target_id, details, ip_address, timestamp
                FROM admin_base.admin_logs
                WHERE admin_id = %s
                ORDER BY timestamp DESC
                LIMIT 20
            """, (g.admin_id,), fetch_all=True) or []

        # --- Query 4: Pending Registration Requests ---
        pending_res = execute_query("""
            SELECT COUNT(*) AS pending_registrations
            FROM admin_base.registration_requests
            WHERE status = 'pending'
        """, fetch_one=True)
        pending_registrations = pending_res['pending_registrations'] if pending_res else 0

        # Prepare Data for Frontend
        dashboard_data = {
            'active_users': stats.get('active_users', 0),
            'total_users': stats.get('total_users', 0),
            'active_creators': stats.get('active_creators', 0),
            'total_creators': stats.get('total_creators', 0),
            'active_exams': stats.get('active_exams', 0),
            'total_purchases': stats.get('total_purchases', 0),
            'total_revenue': float(stats.get('total_revenue', 0.0)),
            'pending_verifications': stats.get('pending_verifications', 0),
            'monthly_sales': monthly_stats.get('monthly_sales', 0),
            'monthly_revenue': float(monthly_stats.get('monthly_revenue', 0.0)),
        }

        return render_template('admin_dashboard.html',
                               stats=dashboard_data,
                               recent_activities=recent_activities,
                               pending_registrations=pending_registrations,
                               designation_names=DESIGNATION_NAMES,
                               action_codes_reverse={v: k for k, v in ACTION_CODES.items()})

    except Exception as e:
        secure_log(f"Dashboard Error: {str(e)}", 'error')
        flash('Could not load dashboard data.', 'error')
        return render_template('admin_dashboard.html', stats={}, recent_activities=[], pending_registrations=0, designation_names=DESIGNATION_NAMES, action_codes_reverse={})


@admin_bp.route('/earnings_analysis/')
@limiter.limit("15 per minute")
@admin_login_required
@permission_required(1)
def earnings_analysis():
    """
    Optimized Earning Analysis: Single DB call with Date Filtering.
    """
    # 1. Date Logic
    default_end = datetime.now()
    default_start = default_end - timedelta(days=30)
    
    start_date_str = request.args.get('start_date', default_start.strftime('%Y-%m-%d'))
    end_date_str = request.args.get('end_date', default_end.strftime('%Y-%m-%d'))

    try:
        # TiDB Compatible: Replaced GetAdminEarningAnalysis stored procedure
        # with individual direct SQL queries.

        # --- Query 1: Totals ---
        totals = execute_query("""
            SELECT
                COALESCE(SUM(amount_paid), 0) AS total_revenue,
                COUNT(*) AS total_transactions,
                COALESCE(AVG(amount_paid), 0) AS avg_order_value,
                COUNT(DISTINCT user_id) AS unique_buyers
            FROM exam.purchased_exams
            WHERE payment_status = 'completed'
              AND payment_date BETWEEN %s AND %s
        """, (start_date_str, end_date_str), fetch_one=True) or {
            'total_revenue': 0, 'total_transactions': 0, 'avg_order_value': 0, 'unique_buyers': 0
        }

        # --- Query 2: Daily Revenue Trend ---
        trend_data = execute_query("""
            SELECT
                DATE_FORMAT(payment_date, '%%d %%b') AS date_label,
                COALESCE(SUM(amount_paid), 0) AS daily_revenue,
                COUNT(*) AS daily_sales
            FROM exam.purchased_exams
            WHERE payment_status = 'completed'
              AND payment_date BETWEEN %s AND %s
            GROUP BY payment_date
            ORDER BY payment_date ASC
        """, (start_date_str, end_date_str), fetch_all=True) or []

        # --- Query 3: Top Creators by Revenue ---
        top_creators = execute_query("""
            SELECT
                pe.channel_id,
                c.creator_name,
                COUNT(*) AS total_sales,
                COALESCE(SUM(pe.amount_paid), 0) AS total_revenue
            FROM exam.purchased_exams pe
            LEFT JOIN creator_base.creators c ON pe.channel_id = c.channel_id
            WHERE pe.payment_status = 'completed'
              AND pe.payment_date BETWEEN %s AND %s
            GROUP BY pe.channel_id, c.creator_name
            ORDER BY total_revenue DESC
            LIMIT 10
        """, (start_date_str, end_date_str), fetch_all=True) or []

        # --- Query 4: Recent Transactions ---
        recent_sales = execute_query("""
            SELECT
                pe.unique_order_number,
                pe.user_id,
                pe.channel_id,
                pe.unique_exam_number,
                pe.amount_paid,
                pe.payment_date,
                pe.payment_status,
                le.exam_title
            FROM exam.purchased_exams pe
            LEFT JOIN exam.listed_exams le ON pe.unique_exam_number = le.unique_exam_number
            WHERE pe.payment_status = 'completed'
              AND pe.payment_date BETWEEN %s AND %s
            ORDER BY pe.created_at DESC
            LIMIT 20
        """, (start_date_str, end_date_str), fetch_all=True) or []

        # Prepare Graph Data
        chart_labels = [row['date_label'] for row in trend_data]
        chart_revenue = [float(row['daily_revenue']) for row in trend_data]
        chart_sales = [int(row['daily_sales']) for row in trend_data]

        return render_template('admin_earnings_analysis.html',
                               totals=totals,
                               top_creators=top_creators,
                               recent_sales=recent_sales,
                               chart_labels=json.dumps(chart_labels),
                               chart_revenue=json.dumps(chart_revenue),
                               chart_sales=json.dumps(chart_sales),
                               start_date=start_date_str,
                               end_date=end_date_str)

    except Exception as e:
        secure_log(f"Earning Analysis Error: {str(e)}", 'error')
        flash('Error loading analysis data.', 'error')
        return render_template('admin_earnings_analysis.html',
                               totals={}, top_creators=[], recent_sales=[],
                               chart_labels='[]', chart_revenue='[]', chart_sales='[]',
                               start_date=start_date_str, end_date=end_date_str)
    
    

# ============================================================================
# GENERIC CRUD HANDLERS WITH FILTERING
# ============================================================================

def apply_filters(query, table_name, entity_config, filters):
    """Apply filters to SQL query (Preserved)"""
    conditions = []
    params = []

    filter_fields = entity_config.get('filter_fields', [])

    for field in filter_fields:
        filter_value = filters.get(field)
        if filter_value is not None and filter_value != '':
             # Basic field name validation here would mitigate some risk, but is not guaranteed.
             # Relying on parameterization of filter_value for safety.
            if field.endswith('_date') or field in ['created_at', 'updated_at', 'payment_date', 'date_joined', 'last_login', 'verified_at']:
                conditions.append(f"`{field}` >= %s")
                params.append(filter_value)
            elif field in ['is_active', 'is_frozen', 'email_verified', 'oauth_connected', 'is_approved', 'resolved']:
                conditions.append(f"`{field}` = %s")
                params.append(1 if str(filter_value).lower() in ['true', '1'] else 0)
            elif field in ['verification_status', 'designation']:
                try:
                    conditions.append(f"`{field}` = %s")
                    params.append(int(filter_value))
                except ValueError: continue
            else:
                conditions.append(f"`{field}` LIKE %s")
                params.append(f"%{filter_value}%")

    if conditions:
        where_clause = " AND " + " AND ".join(conditions)
        return query.replace("WHERE 1=1", f"WHERE 1=1 {where_clause}"), params

    return query, params

def handle_entity_list(entity_key):
    """Generic handler for listing entities (Refactored for centralization)"""
    entity_config = ENTITY_CRUD_MAP.get(entity_key)
    if not entity_config or g.admin_designation > entity_config['min_designation']:
        flash('Access denied.', 'error')
        return redirect(url_for('sevak69.dashboard'))

    # FIXED: Whitelist validation for table/db
    db_name = entity_config['db_name']
    table_name = entity_config['table_name']
    if db_name not in ALLOWED_DB_NAMES or table_name not in ALLOWED_TABLE_NAMES:
         secure_log(f"Disallowed DB/Table access attempt: {db_name}.{table_name}", 'critical')
         flash('System configuration error (disallowed table).', 'error'); return redirect(url_for('sevak69.dashboard'))

    search_query = request.args.get('search', '').strip()
    page = int(request.args.get('page', 1))
    per_page = 50
    offset = (page - 1) * per_page
    filters = {field: request.args.get(f'filter_{field}') for field in entity_config.get('filter_fields', []) if request.args.get(f'filter_{field}')}

    base_query = f"FROM `{db_name}`.`{table_name}`"
    where_clause = "WHERE 1=1"
    params = []

    try:
        schema = get_table_schema(db_name, table_name)
    except ValueError:
         flash('Internal error retrieving table schema.', 'error')
         return redirect(url_for('sevak69.dashboard'))
    except Exception as e:
         secure_log(f"Error fetching schema for {entity_key}: {e}", 'error')
         flash('Database error retrieving table schema.', 'error')
         return redirect(url_for('sevak69.dashboard'))


    # Apply search
    if search_query:
        searchable_cols = [col['COLUMN_NAME'] for col in schema if col['DATA_TYPE'] in ('varchar', 'text', 'char', 'longtext')]
        if searchable_cols:
            search_conditions = ' OR '.join([f"`{col}` LIKE %s" for col in searchable_cols])
            where_clause += f" AND ({search_conditions})"
            params = [f"%{search_query}%"] * len(searchable_cols)

    query_with_where = f"SELECT * {base_query} {where_clause}"

    # Apply filters
    filtered_query, filter_params = apply_filters(query_with_where, table_name, entity_config, filters)
    params.extend(filter_params)

    # Count query
    count_query = f"SELECT COUNT(*) as total {base_query} {where_clause}"
    count_query, _ = apply_filters(count_query, table_name, entity_config, filters) # Must re-run for filter-specific params

    try:
        # Fetch total count
        total_result = execute_query(count_query, params, fetch_one=True)
        total = total_result['total'] if total_result else 0

        # Fetch data query
        list_query = f"{filtered_query} ORDER BY `{entity_config['pk_column']}` DESC LIMIT %s OFFSET %s"
        records = execute_query(list_query, params + [per_page, offset], fetch_all=True)

        # Prepare records for display
        for record in records:
            prepare_record_for_display(record, entity_config)

        log_admin_action(ACTION_CODES['search'], table_name, None, f"Viewed list (search: {search_query}, filters: {filters})")

        return render_template('admin_entity_list.html',
                               entity_key=entity_key, entity_config=entity_config, records=records,
                               total=total, page=page, per_page=per_page, search_query=search_query, filters=filters,
                               designation_names=DESIGNATION_NAMES)

    except Exception as e:
        secure_log(f"Error listing {entity_key}: {str(e)}", 'error')
        flash('Error loading data.', 'error')
        return render_template('admin_entity_list.html',
                               entity_key=entity_key, entity_config=entity_config, records=[],
                               total=0, page=1, per_page=50, search_query='', filters={},
                               designation_names=DESIGNATION_NAMES)


def handle_entity_edit(entity_key, pk_value):
    """
    Generic handler for editing entities (UPDATE) (Refactored for centralization)
    """
    entity_config = ENTITY_CRUD_MAP.get(entity_key)
    if not entity_config or g.admin_designation > entity_config['min_designation']:
        flash('Access denied.', 'error')
        return redirect(url_for('sevak69.dashboard'))

    # Special check for admin entity - restrict editing based on hierarchy
    if entity_key == 'admin':
        target_admin = execute_query("SELECT designation FROM admin_base.admins WHERE admin_id = %s", (pk_value,), fetch_one=True)
        target_admin_designation = target_admin['designation'] if target_admin else None

        if target_admin_designation is not None and not can_manage_designation(g.admin_designation, target_admin_designation):
            flash('You do not have permission to edit an admin of this level or higher.', 'error')
            return redirect(url_for('sevak69.admin'))

    # FIXED: Whitelist validation for table/db
    db_name = entity_config['db_name']
    table_name = entity_config['table_name']
    if db_name not in ALLOWED_DB_NAMES or table_name not in ALLOWED_TABLE_NAMES:
         secure_log(f"Disallowed DB/Table access attempt: {db_name}.{table_name}", 'critical')
         flash('System configuration error (disallowed table).', 'error'); return redirect(url_for('sevak69.dashboard'))

    try:
        schema = get_table_schema(db_name, table_name)
    except Exception as e:
        flash(f'Database error retrieving table schema: {e}', 'error'); return redirect(url_for('sevak69.dashboard'))


    if request.method == 'POST':
        # --- PASSWORD VERIFICATION ---
        current_password = request.form.get('current_admin_password', '').strip()
        admin_data = execute_query("SELECT password_hash FROM admin_base.admins WHERE admin_id = %s", (session['admin_id'],), fetch_one=True)

        if not current_password or not admin_data or not check_password_hash(admin_data['password_hash'], current_password):
            flash('Admin password confirmation failed. Invalid password. Changes not saved.', 'error')
            log_admin_action(ACTION_CODES['login_fail'], 'update_fail', session.get('admin_id'), f'Password check failed for {entity_key} update ID {pk_value}')
            # Reload existing data to show form again
            select_query = f"SELECT * FROM `{db_name}`.`{table_name}` WHERE `{entity_config['pk_column']}` = %s"
            record = execute_query(select_query, (pk_value,), fetch_one=True)
            if record: prepare_record_for_display(record, entity_config)
            return render_template('admin_entity_edit.html', entity_key=entity_key, entity_config=entity_config, record=record or {}, schema=schema, is_create=False, designation_names=DESIGNATION_NAMES if entity_key == 'admin' else None)

        # --- Password verified, proceed with update ---
        try:
            form_data = request.form.to_dict()
            processed_data = prepare_record_for_save(form_data, entity_config, schema, is_update=True)

            # Handle image uploads (Refactored for centralization)
            for image_field in entity_config.get('image_fields', []):
                if image_field in request.files:
                    file = request.files[image_field]
                    if file and file.filename:
                        # 1. Validation
                        file.seek(0, os.SEEK_END)
                        file_size = file.tell()
                        file.seek(0)
                        if file_size > 5 * 1024 * 1024:
                             flash(f"Error: {image_field} file size exceeds 5MB limit.", 'error')
                             raise ValueError("File size exceeded.")

                        # 2. Prepare filename and storage keys
                        filename = secure_filename(file.filename)
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                        name_part, ext_part = os.path.splitext(filename)
                        new_filename = f"{image_field}_{pk_value}_{timestamp}{ext_part.lower()}"
                        
                        storage_key = get_upload_folder_type(image_field, entity_key)
                        encrypt_needed = storage_key == 'bank_documents' 

                        # 3. Centralized Save
                        stored_path = save_file_to_storage(file, storage_key, new_filename, encrypt=encrypt_needed)

                        if stored_path:
                            processed_data[image_field] = stored_path
                        else:
                            flash(f'Error saving {image_field} to storage.', 'error')
                            raise RuntimeError("Central file save failed.")


            if not processed_data:
                flash('No changes detected or data to update.', 'info')
                return redirect(url_for(f'sevak69.{entity_key}'))

            set_clause = ', '.join([f"`{key}` = %s" for key in processed_data.keys()])
            update_query = f"""
                UPDATE `{db_name}`.`{table_name}`
                SET {set_clause}
                WHERE `{entity_config['pk_column']}` = %s
            """
            # Execute and commit using centralized function
            execute_query(update_query, list(processed_data.values()) + [pk_value], commit=True)

            log_admin_action(ACTION_CODES.get(f"{entity_key}_update", 'SRC01'), table_name, pk_value, f"Updated by {g.admin_name}")

            flash('Record updated successfully.', 'success')
            return redirect(url_for(f'sevak69.{entity_key}'))

        except (ValueError, RuntimeError) as ve:
            flash(f'Error updating record: {str(ve)}', 'error')
        except Exception as e:
            secure_log(f"Error updating {entity_key} ID {pk_value}: {str(e)}", 'error')
            flash(f'Error updating record: {str(e)}', 'error')
        
        # Fallback render/redirect on error
        select_query = f"SELECT * FROM `{db_name}`.`{table_name}` WHERE `{entity_config['pk_column']}` = %s"
        record = execute_query(select_query, (pk_value,), fetch_one=True)
        if record: prepare_record_for_display(record, entity_config)
        return render_template('admin_entity_edit.html', entity_key=entity_key, entity_config=entity_config, record=record or {}, schema=schema, is_create=False, designation_names=DESIGNATION_NAMES if entity_key == 'admin' else None)

    # --- GET Request to display the form ---
    try:
        select_query = f"SELECT * FROM `{db_name}`.`{table_name}` WHERE `{entity_config['pk_column']}` = %s"
        record = execute_query(select_query, (pk_value,), fetch_one=True)

        if not record:
            flash('Record not found.', 'error')
            return redirect(url_for(f'sevak69.{entity_key}'))

        prepare_record_for_display(record, entity_config)

        return render_template('admin_entity_edit.html', entity_key=entity_key, entity_config=entity_config, record=record, schema=schema, is_create=False, designation_names=DESIGNATION_NAMES if entity_key == 'admin' else None)

    except Exception as e:
        secure_log(f"Error loading {entity_key} ID {pk_value} for edit: {str(e)}", 'error')
        flash('Error loading record for editing.', 'error')
        return redirect(url_for(f'sevak69.{entity_key}'))


def handle_entity_create(entity_key):
    """Generic handler for creating new entities (CREATE) (Refactored for centralization)"""
    entity_config = ENTITY_CRUD_MAP.get(entity_key)
    if not entity_config or not entity_config.get('allow_create', False) or g.admin_designation > entity_config['min_designation']:
        flash('Access denied or creation not allowed.', 'error')
        return redirect(url_for('sevak69.dashboard'))

    # FIXED: Whitelist validation for table/db
    db_name = entity_config['db_name']
    table_name = entity_config['table_name']
    if db_name not in ALLOWED_DB_NAMES or table_name not in ALLOWED_TABLE_NAMES:
         secure_log(f"Disallowed DB/Table access attempt: {db_name}.{table_name}", 'critical')
         flash('System configuration error (disallowed table).', 'error'); return redirect(url_for('sevak69.dashboard'))

    try:
        schema = get_table_schema(db_name, table_name)
    except Exception as e:
        flash(f'Database error retrieving table schema: {e}', 'error'); return redirect(url_for('sevak69.dashboard'))


    if request.method == 'POST':
        form_data = request.form.to_dict() # Get form data early for fallback
        try:
            processed_data = prepare_record_for_save(form_data, entity_config, schema, is_update=False)

            if not processed_data:
                flash('No data to create.', 'error')
                return redirect(url_for(f'sevak69.{entity_key}_create'))

            # Generate unique ID if not provided
            pk_col = entity_config['pk_column']
            if pk_col not in processed_data:
                if entity_key == 'user': prefix = 'USR_'
                elif entity_key == 'creator': prefix = 'CRT_'
                elif entity_key == 'admin':
                    designation = int(form_data.get('designation', 3)); designation_prefix = DESIGNATION_NAMES[designation].upper()
                    prefix = f'ADM_{designation_prefix}_'
                    processed_data['is_approved'] = True if designation == 0 else False
                elif entity_key == 'exam': prefix = 'EXM_'
                elif entity_key in ['user_result', 'purchase_exam']: prefix = 'ORD_'
                else: prefix = 'ID_'

                # Call secure unique ID generation
                new_id = generate_unique_id(prefix, db_name, table_name, pk_col)
                processed_data[pk_col] = new_id

            # Handle image uploads (Refactored for centralization)
            new_pk_value = processed_data[pk_col]
            for image_field in entity_config.get('image_fields', []):
                if image_field in request.files:
                    file = request.files[image_field]
                    if file and file.filename:
                        # 1. Validation
                        if file.content_length > 5 * 1024 * 1024:
                             flash(f"Error: {image_field} file size exceeds 5MB limit.", 'error')
                             raise ValueError("File size exceeded.")

                        # 2. Prepare filename and storage keys
                        filename = secure_filename(file.filename)
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                        name_part, ext_part = os.path.splitext(filename)
                        new_filename = f"{image_field}_{new_pk_value}_{timestamp}{ext_part.lower()}"
                        
                        storage_key = get_upload_folder_type(image_field, entity_key)
                        encrypt_needed = storage_key == 'bank_documents' 

                        # 3. Centralized Save
                        stored_path = save_file_to_storage(file, storage_key, new_filename, encrypt=encrypt_needed)

                        if stored_path:
                            processed_data[image_field] = stored_path
                        else:
                            flash(f'Error saving {image_field} to storage.', 'error')
                            raise RuntimeError("Central file save failed.")


            columns = ', '.join([f"`{key}`" for key in processed_data.keys()])
            placeholders = ', '.join(['%s'] * len(processed_data))
            insert_query = f"""
                INSERT INTO `{db_name}`.`{table_name}`
                ({columns})
                VALUES ({placeholders})
            """

            # Execute and commit using centralized function
            execute_query(insert_query, list(processed_data.values()), commit=True)

            log_admin_action(ACTION_CODES.get(f"{entity_key}_create", 'SRC01'), table_name, new_pk_value, f"Created by {g.admin_name}")

            flash('Record created successfully.', 'success')
            return redirect(url_for(f'sevak69.{entity_key}'))

        except (ValueError, RuntimeError) as ve:
             flash(f'Validation error creating record: {str(ve)}', 'error')
        except Exception as e:
            secure_log(f"Error creating {entity_key}: {str(e)}", 'error')
            flash(f'Error creating record: {str(e)}', 'error')

        # Fallback rendering on error
        return render_template('admin_entity_edit.html', entity_key=entity_key, entity_config=entity_config, record=form_data, schema=schema, is_create=True, designation_names=DESIGNATION_NAMES if entity_key == 'admin' else None)

    # GET Request to display the creation form
    try:
        schema = get_table_schema(db_name, table_name)

        return render_template('admin_entity_edit.html', entity_key=entity_key, entity_config=entity_config, record={}, schema=schema, is_create=True, designation_names=DESIGNATION_NAMES if entity_key == 'admin' else None)

    except Exception as e:
        secure_log(f"Error loading create form for {entity_key}: {str(e)}", 'error')
        flash('Error loading form.', 'error')
        return redirect(url_for(f'sevak69.{entity_key}'))


# ============================================================================
# CRUD ROUTES FOR EACH ENTITY (Remains the same, calling refactored handlers)
# ============================================================================

@admin_bp.route('/user/', methods=['GET'])
@admin_login_required
@permission_required(3)
@limiter.limit("10 per minute")
def user():
    return handle_entity_list('user')

@admin_bp.route('/user/create/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(3)
@limiter.limit("10 per minute")
def user_create():
    return handle_entity_create('user')

@admin_bp.route('/user/<pk_value>/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(3)
@limiter.limit("10 per minute")
def user_edit(pk_value):
    return handle_entity_edit('user', pk_value)

@admin_bp.route('/user_result/', methods=['GET'])
@admin_login_required
@permission_required(3)
@limiter.limit("10 per minute")
def user_result():
    return handle_entity_list('user_result')

@admin_bp.route('/user_result/create/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(3)
@limiter.limit("10 per minute")
def user_result_create():
    return handle_entity_create('user_result')

@admin_bp.route('/user_result/<pk_value>/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(3)
@limiter.limit("10 per minute")
def user_result_edit(pk_value):
    return handle_entity_edit('user_result', pk_value)

@admin_bp.route('/exam/', methods=['GET'])
@admin_login_required
@permission_required(2)
@limiter.limit("10 per minute")
def exam():
    return handle_entity_list('exam')

@admin_bp.route('/exam/create/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(2)
@limiter.limit("10 per minute")
def exam_create():
    return handle_entity_create('exam')

@admin_bp.route('/exam/<pk_value>/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(2)
@limiter.limit("10 per minute")
def exam_edit(pk_value):
    return handle_entity_edit('exam', pk_value)

@admin_bp.route('/purchase_exam/', methods=['GET'])
@admin_login_required
@permission_required(2)
@limiter.limit("10 per minute")
def purchase_exam():
    return handle_entity_list('purchase_exam')

@admin_bp.route('/purchase_exam/create/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(2)
@limiter.limit("10 per minute")
def purchase_exam_create():
    return handle_entity_create('purchase_exam')

@admin_bp.route('/purchase_exam/<pk_value>/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(2)
@limiter.limit("10 per minute")
def purchase_exam_edit(pk_value):
    return handle_entity_edit('purchase_exam', pk_value)

@admin_bp.route('/creator/', methods=['GET'])
@admin_login_required
@permission_required(2)
@limiter.limit("10 per minute")
def creator():
    return handle_entity_list('creator')

@admin_bp.route('/creator/create/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(2)
@limiter.limit("10 per minute")
def creator_create():
    return handle_entity_create('creator')

@admin_bp.route('/creator/<pk_value>/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(2)
@limiter.limit("10 per minute")
def creator_edit(pk_value):
    return handle_entity_edit('creator', pk_value)

@admin_bp.route('/bank_details/', methods=['GET'])
@admin_login_required
@permission_required(1)
@limiter.limit("10 per minute")
def bank_details():
    return handle_entity_list('bank_details')

@admin_bp.route('/bank_details/create/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(1)
@limiter.limit("10 per minute")
def bank_details_create():
    return handle_entity_create('bank_details')

@admin_bp.route('/bank_details/<pk_value>/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(1)
@limiter.limit("10 per minute")
def bank_details_edit(pk_value):
    return handle_entity_edit('bank_details', pk_value)

@admin_bp.route('/admin/', methods=['GET'])
@admin_login_required
@permission_required(1)
@limiter.limit("10 per minute")
def admin():
    return handle_entity_list('admin')

@admin_bp.route('/admin/create/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(1)
@limiter.limit("10 per minute")
def admin_create():
    return handle_entity_create('admin')

@admin_bp.route('/admin/<pk_value>/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(1)
@limiter.limit("10 per minute")
def admin_edit(pk_value):
    return handle_entity_edit('admin', pk_value)

# ============================================================================
# LOGS ROUTE
# ============================================================================

@admin_bp.route('/logs/')
@admin_login_required
@permission_required(1)
@limiter.limit("10 per minute")
def logs():
    """View admin logs, bank verifications, and documents (Refactored)"""
    try:
        log_type = request.args.get('type', 'admin')
        start_date = request.args.get('start_date', (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d'))
        end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))
        page = int(request.args.get('page', 1))
        per_page = 50
        offset = (page - 1) * per_page

        logs = []
        total = 0
        
        where_params = (start_date, end_date)
        limit_params = (per_page, offset)
        
        if log_type == 'admin':
            logs = execute_query(
                """
                SELECT l.*, a.name as admin_name
                FROM admin_base.admin_logs l
                JOIN admin_base.admins a ON l.admin_id = a.admin_id
                WHERE DATE(l.timestamp) BETWEEN %s AND %s
                ORDER BY l.timestamp DESC
                LIMIT %s OFFSET %s
                """,
                where_params + limit_params,
                fetch_all=True
            )
            total_result = execute_query("SELECT COUNT(*) as total FROM admin_base.admin_logs l WHERE DATE(l.timestamp) BETWEEN %s AND %s", where_params, fetch_one=True)
            total = total_result['total'] if total_result else 0

        elif log_type == 'bank':
            logs = execute_query(
                """
                SELECT * FROM admin_base.bank_verifications
                WHERE DATE(created_at) BETWEEN %s AND %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                where_params + limit_params,
                fetch_all=True
            )
            total_result = execute_query("SELECT COUNT(*) as total FROM admin_base.bank_verifications WHERE DATE(created_at) BETWEEN %s AND %s", where_params, fetch_one=True)
            total = total_result['total'] if total_result else 0

        elif log_type == 'documents':
            logs = execute_query(
                """
                SELECT d.*, a.name as uploaded_by_name
                FROM admin_base.admin_documents d
                JOIN admin_base.admins a ON d.uploaded_by = a.admin_id
                WHERE DATE(d.created_at) BETWEEN %s AND %s
                ORDER BY d.created_at DESC
                LIMIT %s OFFSET %s
                """,
                where_params + limit_params,
                fetch_all=True
            )
            total_result = execute_query("SELECT COUNT(*) as total FROM admin_base.admin_documents d WHERE DATE(d.created_at) BETWEEN %s AND %s", where_params, fetch_one=True)
            total = total_result['total'] if total_result else 0

        return render_template('admin_logs.html',
                               logs=logs, total=total, log_type=log_type,
                               start_date=start_date, end_date=end_date,
                               page=page, per_page=per_page,
                               action_codes=ACTION_CODES)

    except Exception as e:
        secure_log(f"Error loading logs: {str(e)}", 'error')
        flash('Error loading logs.', 'error')
        return render_template('admin_logs.html', logs=[], total=0, log_type='admin', start_date=start_date, end_date=end_date, page=1, per_page=50, action_codes=ACTION_CODES)


# ============================================================================
# PAYOUT ROUTE
# ============================================================================

@admin_bp.route('/payout/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(0)
@limiter.limit("5 per minute")
def payout():
    """Process monthly payouts (Supreme only) (Refactored)"""
    current_month_str = datetime.now().strftime('%Y-%m')

    try:
        if request.method == 'POST':
            payout_month = request.form.get('payout_month')

            if not payout_month:
                flash('Please select a payout month.', 'error')
                return redirect(url_for('sevak69.payout'))

            commission_percentage = current_app.config.get('PLATFORM_COMMISSION_PERCENTAGE', 35.0)
            commission_rate = float(commission_percentage) / 100.0

            # TiDB Compatible: Replaced ProcessMonthlyPayouts stored procedure
            # with Python-level payout loop and individual transactions.
            with get_db_connection() as (conn, cursor):
                # 1. Prevent duplicate payout for same month
                cursor.execute(
                    "SELECT id FROM admin_base.monthly_payouts WHERE payout_month = %s",
                    (payout_month,)
                )
                if cursor.fetchone():
                    flash(f'Payout for {payout_month} has already been processed.', 'warning')
                    return redirect(url_for('sevak69.payout'))

                # 2. Find creators with earnings in the given month
                cursor.execute("""
                    SELECT
                        pe.channel_id,
                        SUM(pe.amount_paid) AS gross_earnings,
                        cbi.id AS bank_id
                    FROM exam.purchased_exams pe
                    INNER JOIN creator_base.creator_bank_info cbi
                        ON pe.channel_id = cbi.channel_id
                        AND cbi.verification_status = 1
                        AND cbi.is_active = 1
                        AND cbi.is_frozen = 0
                    WHERE pe.payment_status = 'completed'
                      AND DATE_FORMAT(pe.payment_date, '%%Y-%%m') = %s
                    GROUP BY pe.channel_id, cbi.id
                    HAVING SUM(pe.amount_paid) > 0
                """, (payout_month,))
                creators = cursor.fetchall()

                if not creators:
                    flash('No eligible creators found for this month.', 'info')
                    return redirect(url_for('sevak69.payout'))

                # 3. Calculate totals
                total_gross = sum(float(c['gross_earnings']) for c in creators)
                total_net = sum(float(c['gross_earnings']) * (1 - commission_rate) for c in creators)
                total_commission = total_gross - total_net

                # 4. Insert monthly_payouts header
                cursor.execute("""
                    INSERT INTO admin_base.monthly_payouts
                    (payout_month, processed_by, total_creators, total_amount,
                     platform_commission, status)
                    VALUES (%s, %s, %s, %s, %s, 'processing')
                """, (payout_month, session['admin_id'], len(creators), total_net, total_commission))
                payout_id = cursor.lastrowid

                # 5. Insert payout_details for each creator
                for creator in creators:
                    gross = float(creator['gross_earnings'])
                    commission = gross * commission_rate
                    net_payout = gross - commission
                    cursor.execute("""
                        INSERT INTO admin_base.payout_details
                        (payout_id, channel_id, gross_earnings, platform_commission,
                         transfer_charge, net_payout, payment_status)
                        VALUES (%s, %s, %s, %s, 0.00, %s, 'pending')
                    """, (payout_id, creator['channel_id'], gross, commission, net_payout))

                # 6. Mark payout as completed
                cursor.execute("""
                    UPDATE admin_base.monthly_payouts
                    SET status = 'completed', completed_at = NOW()
                    WHERE id = %s
                """, (payout_id,))
                conn.commit()

            flash(f"Payout processed! {len(creators)} creators scheduled. Total: ₹{total_net:,.2f}", 'success')
            log_admin_action(ACTION_CODES['payout_process'], 'payout', payout_month,
                             f"Processed by {g.admin_name}")
            return redirect(url_for('sevak69.payout'))

        # --- GET Request Logic ---
        payout_history = execute_query(
            "SELECT * FROM admin_base.monthly_payouts ORDER BY payout_month DESC LIMIT 12",
            fetch_all=True
        )

        return render_template('admin_payout.html', payout_history=payout_history or [], current_month=current_month_str)

    except Exception as e:
        secure_log(f"Error in payout route: {str(e)}", 'error')
        flash(f'An unexpected error occurred: {str(e)}', 'error')
        return render_template('admin_payout.html', payout_history=[], current_month=current_month_str)


# ============================================================================
# DOCUMENT MANAGEMENT
# ============================================================================

@admin_bp.route('/documents/')
@admin_login_required
@permission_required(2)
@limiter.limit("10 per minute")
def documents():
    """View all uploaded documents (Refactored)"""
    target_type = request.args.get('type', 'all')
    page = int(request.args.get('page', 1))
    per_page = 50
    offset = (page - 1) * per_page

    try:
        # Build where clause safely (not from user input directly)
        where_clause = ""
        params = []
        if target_type != 'all':
            where_clause = "WHERE target_type = %s"
            params.append(target_type)

        # Build query safely - where_clause is internally constructed, not user input
        query = f"""
            SELECT d.*, a.name as uploaded_by_name
            FROM admin_base.admin_documents d
            JOIN admin_base.admins a ON d.uploaded_by = a.admin_id
            {where_clause}
            ORDER BY d.created_at DESC
            LIMIT %s OFFSET %s
        """
        documents = execute_query(query, params + [per_page, offset], fetch_all=True)

        # Count query
        count_query = f"SELECT COUNT(*) as total FROM admin_base.admin_documents {where_clause}"
        total_result = execute_query(count_query, params, fetch_one=True)
        total = total_result['total'] if total_result else 0

        return render_template('admin_documents.html', documents=documents, total=total, target_type=target_type, page=page, per_page=per_page)

    except Exception as e:
        secure_log(f"Error loading documents: {str(e)}", 'error')
        flash('Error loading documents.', 'error')
        return render_template('admin_documents.html', documents=[], total=0, target_type='all', page=1, per_page=50)


@admin_bp.route('/upload_document/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(2)
@limiter.limit("10 per minute")
def upload_document():
    """Upload document on behalf of user/creator/admin (Refactored for centralization)"""
    if request.method == 'POST':
        target_type = request.form.get('target_type')
        target_id = request.form.get('target_id', '').strip()
        document_type = request.form.get('document_type', '').strip()
        description = request.form.get('description', '').strip()

        if not all([target_type, target_id, document_type]):
            flash('All fields are required.', 'error')
            return render_template('admin_upload_document.html')

        if target_type not in ['user', 'creator', 'admin']:
            flash('Invalid target type.', 'error')
            return render_template('admin_upload_document.html')

        doc_file = request.files.get('document_file')
        if not doc_file or not doc_file.filename:
            flash('Please select a file to upload.', 'error')
            return render_template('admin_upload_document.html')

        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            original_filename = secure_filename(doc_file.filename)
            file_extension = original_filename.split('.')[-1]
            # Encrypted files are stored in the 'uploads' category (mapped by get_storage_folder_key)
            encrypted_filename = f"{target_type}_{target_id}_{timestamp}.{file_extension}.enc"
            
            # FIXED: File size check BEFORE save
            doc_file.seek(0, os.SEEK_END)
            file_size = doc_file.tell()
            doc_file.seek(0)
            if file_size > 10 * 1024 * 1024: # 10MB limit for general docs
                 flash('File size exceeds 10MB limit.', 'error')
                 return render_template('admin_upload_document.html')

            # --- CENTRALIZED SAVE AND ENCRYPTION ---
            # Use save_file (via wrapper) to handle GCS/Local and encryption
            # For admin_documents, we must encrypt as these are internal/sensitive
            stored_path = save_file_to_storage(doc_file, 'uploads', encrypted_filename, encrypt=True)

            if not stored_path:
                flash('Error saving file to storage.', 'error')
                return render_template('admin_upload_document.html')
            
            # --- DATABASE INSERTION ---
            row_count = execute_query(
                """
                INSERT INTO admin_base.admin_documents
                (target_type, target_id, document_type, original_filename,
                 encrypted_filename, file_path, uploaded_by, description, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                """,
                (target_type, target_id, document_type, original_filename,
                 encrypted_filename, stored_path, # Use stored_path from centralized save
                 session['admin_id'], description),
                 commit=True
            )
            
            if row_count == 0:
                 raise Exception("Database reported 0 rows inserted for document metadata.")

            log_admin_action(ACTION_CODES['document_upload'], target_type, target_id, f'Document uploaded: {document_type}')

            flash('Document uploaded successfully.', 'success')
            return redirect(url_for('sevak69.documents'))

        except Exception as e:
            secure_log(f"Document upload error: {str(e)}", 'error')
            flash('Error uploading document.', 'error')

    return render_template('admin_upload_document.html')

@admin_bp.route('/view_document/<int:doc_id>')
@admin_login_required
@permission_required(2)
@limiter.limit("20 per minute")
def view_document(doc_id):
    """View/download encrypted document (Refactored for centralization)"""
    try:
        document = execute_query("SELECT * FROM admin_base.admin_documents WHERE id = %s", (doc_id,), fetch_one=True)

        if not document:
            flash('Document not found.', 'error')
            return redirect(url_for('sevak69.documents'))

        doc_path = document['file_path']
        
        # --- CENTRALIZED FILE LOAD AND DECRYPT ---
        # download_file_content handles GCS/Local and decryption
        decrypted_data = download_file_content(doc_path, decrypt=True)

        if not decrypted_data:
            secure_log(f"Failed to decrypt or find document {doc_id} at {doc_path}", 'error')
            flash('Error decrypting or accessing document.', 'error')
            return redirect(url_for('sevak69.documents'))

        log_admin_action(ACTION_CODES['document_view'], document['target_type'], document['target_id'], f'Viewed document: {document["document_type"]}')

        mimetype = mimetypes.guess_type(document['original_filename'])[0] or 'application/octet-stream'

        return send_file(
            io.BytesIO(decrypted_data),
            as_attachment=True,
            download_name=document['original_filename'],
            mimetype=mimetype
        )

    except Exception as e:
        secure_log(f"Document view error: {str(e)}", 'error')
        flash('Error viewing document.', 'error')
        return redirect(url_for('sevak69.documents'))

@admin_bp.route('/delete_document/<int:doc_id>', methods=['POST'])
@admin_login_required
@permission_required(1)
@limiter.limit("10 per minute")
def delete_document(doc_id):
    """Delete uploaded document (Refactored for centralization)"""
    try:
        document = execute_query("SELECT * FROM admin_base.admin_documents WHERE id = %s", (doc_id,), fetch_one=True)

        if not document:
            flash('Document not found.', 'error')
            return redirect(url_for('sevak69.documents'))

        doc_path = document['file_path']
        
        # --- CENTRALIZED FILE DELETION ---
        # delete_file handles GCS/Local file deletion.
        delete_file(doc_path)

        # Delete database record
        row_count = execute_query("DELETE FROM admin_base.admin_documents WHERE id = %s", (doc_id,), commit=True)
        
        if row_count > 0:
            log_admin_action(ACTION_CODES['document_delete'], document['target_type'], document['target_id'], f'Deleted document: {document["document_type"]}')
            flash('Document deleted successfully.', 'success')
        else:
             flash('Document metadata not found or already deleted.', 'warning')

    except Exception as e:
        secure_log(f"Document delete error: {str(e)}", 'error')
        flash('Error deleting document.', 'error')

    return redirect(url_for('sevak69.documents'))

# ============================================================================
# FIXED: PASSWORD RESET ROUTES
# ============================================================================

@admin_bp.route('/request_password_reset/', methods=['GET', 'POST'])
@limiter.limit("15 per hour")
def request_password_reset():
    """Handle request for admin password reset link (Refactored)"""

    # CRITICAL FIX: Validate session before redirecting to prevent loop
    if 'admin_id' in session:
        if validate_session_security():
            return redirect(url_for('sevak69.dashboard'))
        else:
            clear_admin_session()
    
    if request.method == 'POST':
        email = request.form.get('email', '').lower().strip()
        
        try:
            admin = execute_query(
                "SELECT admin_id, name FROM admin_base.admins WHERE email = %s AND is_active = 1", 
                (email,), 
                fetch_one=True
            )
            
            if admin:
                import secrets
                reset_token = secrets.token_urlsafe(32)
                token_hash = hashlib.sha256(reset_token.encode()).hexdigest()
                save_password_reset_token_db('admin', email, token_hash, expiry_seconds=3600, ip_address=get_client_ip())
                
                reset_link = url_for('sevak69.reset_password', token=reset_token, _external=True)
                
                # USE EMAIL SERVICE - Send password reset email 
                send_password_reset_email(email, reset_link, admin['name'])
            
            flash("If an active account with that email exists, a password reset link has been sent.", "info")
            return redirect(url_for('sevak69.login'))
        
        except Exception as e:
            secure_log(f"Error in request_password_reset: {str(e)}", 'error')
            flash("An error occurred. Please try again later.", "error")
    
    return render_template('admin_request_password_reset.html')


@admin_bp.route('/reset_password/<token>', methods=['GET', 'POST'])
@limiter.limit("15 per hour") # Limit attempts even with a token
def reset_password(token):
    """Handle password reset using the token (Refactored)"""
    # CRITICAL FIX: Validate session before redirecting to prevent loop
    if 'admin_id' in session:
        if validate_session_security():
            return redirect(url_for('sevak69.dashboard'))
        else:
            clear_admin_session()

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    token_data = get_password_reset_token_db(token_hash)
    
    if not token_data or token_data.get('user_type') != 'admin':
        flash("Invalid or expired password reset link.", "error")
        return redirect(url_for('sevak69.login'))

    email = token_data.get('email')

    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if not password or not confirm_password:
            flash('Both password fields are required.', 'error')
            return render_template('admin_reset_password.html', token=token)
        
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('admin_reset_password.html', token=token)
        
        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'error')
            return render_template('admin_reset_password.html', token=token)

        try:
            new_hash = generate_password_hash(password, method='pbkdf2:sha256:260000')
            
            # Update password and reset lock/attempts
            row_count = execute_query(
                """
                UPDATE admin_base.admins
                SET password_hash = %s, login_attempts = 0, locked_until = NULL, updated_at = NOW()
                WHERE email = %s
                """, 
                (new_hash, email),
                commit=True
            )
            
            if row_count == 0:
                 flash('Could not find user to update. Please try the reset process again.', 'error')
            else:
                # CRITICAL: Delete the password reset token after successful reset
                delete_password_reset_token_db(token_hash)
                
                log_admin_action(ACTION_CODES['password_reset_complete'], 'admin_auth', email, 'Password reset completed')
                flash('Password reset successfully. You can now log in.', 'success')
            
            return redirect(url_for('sevak69.login'))

        except Exception as e:
            secure_log(f"Error resetting password for {email}: {str(e)}", 'error')
            flash('An error occurred while resetting the password. Please try again.', 'error')

    return render_template('admin_reset_password.html', token=token)



# ============================================================================
# OTP VERIFICATION ROUTES (NEW IN v9.7 - Used by login/registration)
# ============================================================================

@admin_bp.route('/send_otp/', methods=['POST'])
@limiter.limit("4 per 5 minutes")
def send_otp():
    """Send OTP to admin email for verification (Refactored)"""
    email = request.form.get('email', '').lower().strip()
    purpose = request.form.get('purpose', 'login')  # login, registration, first_time_setup

    if not email:
        return jsonify({'success': False, 'message': 'Email is required'}), 400

    try:
        # Verify email exists for login, doesn't exist for registration/first_time
        if purpose == 'login':
            admin = execute_query(
                "SELECT admin_id, name FROM admin_base.admins WHERE email = %s AND is_active = 1", 
                (email,), 
                fetch_one=True
            )
            if not admin:
                return jsonify({'success': False, 'message': 'Invalid email address'}), 404
            name = admin['name']
        elif purpose == 'first_time_setup':
            result = execute_query("SELECT COUNT(*) as count FROM admin_base.admins WHERE designation = 0", fetch_one=True)
            if result and result['count'] > 0:
                return jsonify({'success': False, 'message': 'Supreme admin already exists'}), 400
            name = request.form.get('name', 'Admin')
        else:  # registration
            name = request.form.get('name', 'Admin')

        # Send OTP using email service
        otp_result = send_otp_email(email, user_type='admin', to_name=name, purpose=purpose)

        if otp_result:
            log_admin_action(ACTION_CODES['otp_send'], 'otp', email, f'OTP sent for {purpose}')
            return jsonify({'success': True, 'message': 'OTP sent successfully to your email'}), 200
        else:
            return jsonify({'success': False, 'message': 'Failed to send OTP. Please try again'}), 500

    except Exception as e:
        secure_log(f"Error sending OTP to {email}: {str(e)}", 'error')
        return jsonify({'success': False, 'message': 'Error sending OTP'}), 500

@admin_bp.route('/verify_otp/', methods=['POST'])
@limiter.limit("5 per minute")
def verify_otp():
    """Verify OTP code (Remains the same - no DB interaction)"""
    email = request.form.get('email', '').lower().strip()
    otp_code = request.form.get('otp_code', '').strip()
    purpose = request.form.get('purpose', 'login')

    if not email or not otp_code:
        return jsonify({'success': False, 'message': 'Email and OTP code are required'}), 400

    try:
        # Verify OTP using email service
        is_valid = verify_otp_email(email, otp_code)

        if is_valid:
            log_admin_action(ACTION_CODES['otp_verify'], 'otp', email, f'OTP verified for {purpose}')
            # Store verification in session temporarily
            session[f'otp_verified_{email}_{purpose}'] = True
            session[f'otp_verified_time_{email}'] = datetime.now().isoformat()
            return jsonify({'success': True, 'message': 'OTP verified successfully'}), 200
        else:
            log_admin_action(ACTION_CODES.get('otp_verify_fail', 'SK12'), 'otp', email, f'OTP verification failed for {purpose}')
            return jsonify({'success': False, 'message': 'Invalid or expired OTP code'}), 401

    except Exception as e:
        secure_log(f"Error verifying OTP for {email}: {str(e)}", 'error')
        return jsonify({'success': False, 'message': 'Error verifying OTP'}), 500

def check_otp_verification(email, purpose, max_age_minutes=10):
    """Check if OTP was recently verified for this email and purpose (Remains the same)"""
    verification_key = f'otp_verified_{email}_{purpose}'
    time_key = f'otp_verified_time_{email}'

    if not session.get(verification_key):
        return False

    # Check if verification is still valid (within max_age_minutes)
    verified_time_str = session.get(time_key)
    if verified_time_str:
        try:
            verified_time = datetime.fromisoformat(verified_time_str)
            if datetime.now() - verified_time > timedelta(minutes=max_age_minutes):
                # OTP verification expired
                session.pop(verification_key, None)
                session.pop(time_key, None)
                return False
        except:
            return False

    return True


# ============================================================================
# CREATOR PAYMENT SEARCH AND CSV DOWNLOAD (v9.8 NEW)
# ============================================================================

@admin_bp.route('/creator_payment_search/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(1)
@limiter.limit("20 per minute")
def creator_payment_search():
    """Search creator-wise monthly payment amount after applying commission rate (Refactored)"""
    results = []
    search_month = request.args.get('month') or request.form.get('month') or datetime.now().strftime('%Y-%m')
    creator_search = request.args.get('creator') or request.form.get('creator', '').strip()

    try:
        commission_percentage = current_app.config.get('PLATFORM_COMMISSION_PERCENTAGE', 35.0)
        commission_rate_float = float(commission_percentage) / 100.0

        year, month = search_month.split('-')
        start_date = f"{year}-{month}-01"
        if int(month) == 12:
            end_date = f"{int(year)+1}-01-01"
        else:
            end_date = f"{year}-{int(month)+1:02d}-01"

        query = """
            SELECT 
                c.channel_id,
                c.creator_name,
                c.email,
                COUNT(pe.id) as total_sales,
                COALESCE(SUM(pe.amount_paid), 0.00) as gross_revenue,
                COALESCE(SUM(pe.amount_paid * %s), 0.00) as platform_commission,
                COALESCE(SUM(pe.amount_paid * (1 - %s)), 0.00) as creator_payment
            FROM creator_base.creators c
            LEFT JOIN exam.purchased_exams pe ON c.channel_id = pe.channel_id
                AND pe.payment_status = 'completed'
                AND pe.payment_date >= %s
                AND pe.payment_date < %s
        """

        params = [commission_rate_float, commission_rate_float, start_date, end_date]

        if creator_search:
            query += " WHERE c.creator_name LIKE %s OR c.email LIKE %s OR c.channel_id LIKE %s"
            search_param = f"%{creator_search}%"
            params.extend([search_param, search_param, search_param])

        query += " GROUP BY c.channel_id, c.creator_name, c.email ORDER BY creator_payment DESC"

        results = execute_query(query, params, fetch_all=True)

        for row in results:
            row['gross_revenue_formatted'] = f"Rs {row['gross_revenue']:,.2f}"
            row['platform_commission_formatted'] = f"Rs {row['platform_commission']:,.2f}"
            row['creator_payment_formatted'] = f"Rs {row['creator_payment']:,.2f}"

        log_admin_action(ACTION_CODES['search'], 'creator_payment', search_month, 'Payment search')

        return render_template('admin_creator_payment_search.html',
                             results=results,
                             search_month=search_month,
                             creator_search=creator_search,
                             commission_percentage=commission_percentage)

    except Exception as e:
        secure_log(f"Error in creator payment search: {str(e)}", 'error')
        flash('Error loading payment data.', 'error')
        return render_template('admin_creator_payment_search.html',
                             results=[],
                             search_month=search_month,
                             creator_search='',
                             commission_percentage=35.0)


@admin_bp.route('/download_monthly_payments_csv/', methods=['GET'])
@admin_login_required
@permission_required(1)
@limiter.limit("10 per 5 minute")
def download_monthly_payments_csv():
    """Download monthly CSV file with creator account details and combined payment amounts"""
    month = request.args.get('month') or datetime.now().strftime('%Y-%m')

    try:
        commission_percentage = current_app.config.get('PLATFORM_COMMISSION_PERCENTAGE', 35.0)
        commission_rate_float = float(commission_percentage) / 100.0

        year, month_num = month.split('-')
        start_date = f"{year}-{month_num}-01"
        if int(month_num) == 12:
            end_date = f"{int(year)+1}-01-01"
        else:
            end_date = f"{year}-{int(month_num)+1:02d}-01"

        query = """
            SELECT 
                c.channel_id,
                c.creator_name,
                c.email,
                c.contact_phone,
                bi.account_holder_name,
                bi.account_number,
                bi.bank_name,
                bi.ifsc_code,
                bi.branch_name,
                bi.country_code,
                COUNT(pe.id) as total_sales,
                COALESCE(SUM(pe.amount_paid), 0.00) as gross_revenue,
                COALESCE(SUM(pe.amount_paid * %s), 0.00) as platform_commission,
                COALESCE(SUM(pe.amount_paid * (1 - %s)), 0.00) as creator_payment
            FROM creator_base.creators c
            LEFT JOIN creator_base.creator_bank_info bi ON c.channel_id = bi.channel_id 
                AND bi.is_active = 1 
                AND bi.verification_status = 1
            LEFT JOIN exam.purchased_exams pe ON c.channel_id = pe.channel_id
                AND pe.payment_status = 'completed'
                AND pe.payment_date >= %s
                AND pe.payment_date < %s
            GROUP BY c.channel_id, c.creator_name, c.email, c.contact_phone,
                     bi.account_holder_name, bi.account_number, bi.bank_name, 
                     bi.ifsc_code, bi.branch_name, bi.country_code
            HAVING creator_payment > 0
            ORDER BY creator_payment DESC
        """

        results = execute_query(query, [commission_rate_float, commission_rate_float, start_date, end_date], fetch_all=True)

        for row in results:
            if row.get('account_number'):
                # DECRYPTION: Use centralized function
                row['account_number'] = decrypt_token(row['account_number']) or 'DECRYPT_ERROR'

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            'Month', 'Channel ID', 'Creator Name', 'Email', 'Contact Phone',
            'Account Holder Name', 'Account Number', 'Bank Name', 'IFSC Code',
            'Branch Name', 'Country Code', 'Total Sales', 'Gross Revenue',
            'Platform Commission', 'Creator Payment (After Commission)'
        ])

        for row in results:
            writer.writerow([
                month, row['channel_id'], row['creator_name'], row['email'],
                row['contact_phone'] or '', row['account_holder_name'] or 'N/A',
                row['account_number'] or 'N/A', row['bank_name'] or 'N/A',
                row['ifsc_code'] or 'N/A', row['branch_name'] or 'N/A',
                row['country_code'] or 'N/A', row['total_sales'],
                f"{row['gross_revenue']:.2f}", f"{row['platform_commission']:.2f}",
                f"{row['creator_payment']:.2f}"
            ])

        output.seek(0)
        filename = f"creator_payments_{month}.csv"

        log_admin_action(ACTION_CODES['search'], 'csv_download', month, 'CSV downloaded')

        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8-sig')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        secure_log(f"Error generating payment CSV: {str(e)}", 'error')
        flash('Error generating CSV file.', 'error')
        return redirect(url_for('sevak69.creator_payment_search'))


@admin_bp.route('/contact_query/', methods=['GET'])
@admin_login_required
@permission_required(3)
@limiter.limit("30 per minute")
def contact_query_list():
    """List view for contact queries."""
    return handle_entity_list('contact_query')

# FIXED ROUTE: Removed trailing slash to prevent 308/405 errors
@admin_bp.route('/contact_query/<query_id>/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(3)
@limiter.limit("30 per minute")
def contact_query_detail_action(query_id):
    """
    GET: Views the full details of a single contact query.
    POST: Marks the query as resolved.
    """
    entity_key = 'contact_query'
    entity_config = ENTITY_CRUD_MAP.get(entity_key)
    
    if not entity_config:
        flash('Invalid entity configuration.', 'error')
        return redirect(url_for('sevak69.contact_query_list'))

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'resolve':
            # --- ACTION: Mark as Resolved (Refactored) ---
            try:
                admin_id = g.admin_id
                
                row_count = execute_query(
                    """
                    UPDATE query_base.contact_us_queries
                    SET resolved = 1, 
                        resolved_at = NOW(),
                        resolved_by = %s,
                        updated_at = NOW()
                    WHERE query_id = %s AND resolved = 0
                    """, 
                    (admin_id, query_id), 
                    commit=True
                )

                if row_count == 0:
                    flash('Query not found or already resolved.', 'warning')
                else:
                    log_admin_action(ACTION_CODES.get('admin_approve', 'ADM04'), entity_key, query_id, f'Query resolved by {g.admin_name}')
                    flash(f'Query {query_id} successfully marked as resolved.', 'success')
                
                return redirect(url_for('sevak69.contact_query_list'))

            except Exception as e:
                secure_log(f"Error resolving query {query_id}: {str(e)}", 'error')
                flash('Error processing query resolution.', 'error')
                
        else:
             flash('Invalid action.', 'error')
             return redirect(url_for('sevak69.contact_query_list'))

    # --- GET: View Query Details (Refactored) ---
    try:
        # Direct query using the query_id passed in URL
        record = execute_query(
            f"SELECT * FROM query_base.contact_us_queries WHERE query_id = %s", 
            (query_id,), 
            fetch_one=True
        )

        if not record:
            flash('Query record not found.', 'error')
            return redirect(url_for('sevak69.contact_query_list'))

        prepare_record_for_display(record, entity_config)

        return render_template('admin_contact_query_detail.html', 
                               entity_config=entity_config, 
                               record=record,
                               query_id=query_id,
                               is_resolved=record.get('resolved', 0) == 1)

    except Exception as e:
        secure_log(f"Error loading query {query_id} for detail view: {str(e)}", 'error')
        flash('Error loading query details.', 'error')
        return redirect(url_for('sevak69.contact_query_list'))


# ============================================================================
# CREATOR JOIN REQUEST MANAGEMENT (NEW)
# ============================================================================

@admin_bp.route('/creator_requests/')
@admin_login_required
@permission_required(2)  # Major Level (2) required to vet creators
@limiter.limit("15 per minute")
def creator_requests_list():
    """List view for Creator Join Requests with status filtering (Refactored)."""
    status_filter = request.args.get('status', 'pending')
    page = int(request.args.get('page', 1))
    per_page = 50
    offset = (page - 1) * per_page

    allowed_statuses = ['pending', 'reviewed', 'contacted', 'rejected', 'approved', 'all']
    if status_filter not in allowed_statuses: status_filter = 'pending'

    try:
        where_clause = ""
        params = []
        
        if status_filter != 'all':
            where_clause = "WHERE status = %s"
            params.append(status_filter)

        # 1. Get Data
        query = f"""
            SELECT * FROM query_base.creator_join_requests
            {where_clause}
            ORDER BY submitted_at DESC
            LIMIT %s OFFSET %s
        """
        requests_data = execute_query(query, params + [per_page, offset], fetch_all=True)

        # 2. Get Total Count (for pagination)
        count_query = f"SELECT COUNT(*) as total FROM query_base.creator_join_requests {where_clause}"
        total_result = execute_query(count_query, params, fetch_one=True)
        total = total_result['total'] if total_result else 0

        # Log the view action
        log_admin_action(ACTION_CODES.get('search', 'SRC01'), 'creator_request', None, f"Viewed {status_filter} requests")

        return render_template('admin_creator_requests_list.html',
                               requests=requests_data,
                               status_filter=status_filter,
                               total=total,
                               page=page,
                               per_page=per_page)

    except Exception as e:
        secure_log(f"Error loading creator requests: {str(e)}", 'error')
        flash('Error loading requests.', 'error')
        return render_template('admin_creator_requests_list.html', requests=[], status_filter='pending', total=0, page=1, per_page=50)


@admin_bp.route('/creator_requests/<request_id>/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(2) # Major Level (2) required to vet creators
@limiter.limit("10 per minute")
def creator_request_detail_action(request_id):
    """
    GET: View full details of a creator request.
    POST: Perform actions (Contacted, Approve, Reject). (Refactored)
    """
    try:
        # --- HANDLE POST ACTIONS ---
        if request.method == 'POST':
            action = request.form.get('action')
            
            new_status = None
            log_msg = ""

            if action == 'mark_reviewed':
                new_status = 'reviewed'
                log_msg = "Marked as Reviewed"
            elif action == 'mark_contacted':
                new_status = 'contacted'
                log_msg = "Marked as Contacted"
            elif action == 'approve':
                new_status = 'approved'
                log_msg = "Approved for onboarding"
            elif action == 'reject':
                new_status = 'rejected'
                log_msg = "Rejected request"
            
            if new_status:
                update_query = """
                    UPDATE query_base.creator_join_requests
                    SET status = %s, updated_at = NOW()
                    WHERE request_id = %s
                """
                row_count = execute_query(update_query, (new_status, request_id), commit=True)

                if row_count > 0:
                    log_admin_action(ACTION_CODES.get('creator_update', 'CRT02'), 'creator_request', request_id, f"{log_msg} by {g.admin_name}")
                    flash(f"Request status updated to: {new_status.upper()}", 'success')
                else:
                    flash("Request not found or status already set.", 'warning')
                
                return redirect(url_for('sevak69.creator_requests_list'))
            else:
                flash("Invalid action selected.", 'error')

        # --- HANDLE GET VIEW ---
        req_data = execute_query("SELECT * FROM query_base.creator_join_requests WHERE request_id = %s", (request_id,), fetch_one=True)

        if not req_data:
            flash('Creator request not found.', 'error')
            return redirect(url_for('sevak69.creator_requests_list'))

        return render_template('admin_creator_request_detail.html', record=req_data)

    except Exception as e:
        secure_log(f"Error processing creator request {request_id}: {str(e)}", 'error')
        flash('An error occurred while processing the request.', 'error')
        return redirect(url_for('sevak69.creator_requests_list'))


# ============================================================================
# FEATURED EXAMS MANAGEMENT ROUTES
# ============================================================================

@admin_bp.route('/featured_exams/', methods=['GET'])
@admin_login_required
@permission_required(1)  # Chief Level (1) required to manage featured exams
@limiter.limit("30 per minute")
def featured_exams_page():
    """
    GET: Display featured exams management page with 5 slots
    """
    try:
        # Get current featured exams with exam details
        query = """
            SELECT
                afe.id,
                afe.exam_id,
                afe.display_order,
                afe.is_active,
                e.unique_exam_number AS exam_number,
                e.exam_title AS title,
                e.exam_price AS price,
                COALESCE(
                    (SELECT COUNT(*)
                     FROM exam.purchased_exams pe
                     WHERE pe.unique_exam_number = e.unique_exam_number
                       AND pe.payment_status = 'completed'),
                    0
                ) as purchase_count,
                cb.creator_name as creator_name
            FROM admin_base.admin_featured_exams afe
            JOIN exam.listed_exams e ON afe.exam_id = e.id
            JOIN creator_base.creators cb ON e.channel_id = cb.channel_id
            WHERE afe.is_active = TRUE
            ORDER BY afe.display_order ASC
        """
        featured_exams_data = execute_query(query, fetch_all=True) or []

        # Create array with 5 slots (None for empty slots)
        featured_exams = [None] * 5
        for exam in featured_exams_data:
            if 1 <= exam['display_order'] <= 5:
                featured_exams[exam['display_order'] - 1] = exam

        # Get total active exams count
        total_query = "SELECT COUNT(*) as total FROM exam.listed_exams WHERE is_active = TRUE"
        total_result = execute_query(total_query, fetch_one=True)
        total_exams = total_result['total'] if total_result else 0

        # Count filled slots
        featured_count = len([e for e in featured_exams if e is not None])

        log_admin_action(ACTION_CODES.get('search', 'SRC01'), 'featured_exams', None, "Viewed featured exams page")

        return render_template('admin_featured_exams.html',
                             featured_exams=featured_exams,
                             featured_count=featured_count,
                             total_exams=total_exams)

    except Exception as e:
        secure_log(f"Error loading featured exams page: {str(e)}", 'error')
        flash('Error loading featured exams page.', 'error')
        return render_template('admin_featured_exams.html',
                             featured_exams=[None]*5,
                             featured_count=0,
                             total_exams=0)


@admin_bp.route('/api/search_exams', methods=['GET'])
@admin_login_required
@permission_required(1)
@limiter.limit("60 per minute")
def api_search_exams():
    """
    API: Search exams for featured exams selection
    Query params: q (search query)
    """
    try:
        search_query = request.args.get('q', '').strip()

        # Get all active exams with creator info
        query = """
            SELECT
                e.id,
                e.unique_exam_number AS exam_number,
                e.exam_title AS title,
                e.exam_price AS price,
                cb.creator_name as creator_name,
                COALESCE(
                    (SELECT COUNT(*)
                     FROM exam.purchased_exams pe
                     WHERE pe.unique_exam_number = e.unique_exam_number
                       AND pe.payment_status = 'completed'),
                    0
                ) as purchase_count
            FROM exam.listed_exams e
            JOIN creator_base.creators cb ON e.channel_id = cb.channel_id
            WHERE e.is_active = TRUE
        """

        params = []

        # Add search filter if provided
        if search_query:
            query += """
                AND (
                    e.exam_title LIKE %s OR
                    e.unique_exam_number LIKE %s OR
                    cb.creator_name LIKE %s
                )
            """
            search_param = f"%{search_query}%"
            params = [search_param, search_param, search_param]

        query += " ORDER BY purchase_count DESC, e.created_at DESC LIMIT 100"

        exams = execute_query(query, params, fetch_all=True) or []

        return jsonify({
            'success': True,
            'exams': exams
        })

    except Exception as e:
        secure_log(f"Error searching exams: {str(e)}", 'error')
        return jsonify({
            'success': False,
            'message': 'Error searching exams',
            'exams': []
        }), 500


@admin_bp.route('/api/featured_exams/add', methods=['POST'])
@admin_login_required
@permission_required(1)
@limiter.limit("20 per minute")
def api_add_featured_exam():
    """
    API: Add an exam to featured exams list
    JSON body: {exam_id, display_order}
    """
    try:
        data = request.get_json()
        exam_id = data.get('exam_id')
        display_order = data.get('display_order')

        if not exam_id or not display_order:
            return jsonify({
                'success': False,
                'message': 'Missing exam_id or display_order'
            }), 400

        if display_order < 1 or display_order > 5:
            return jsonify({
                'success': False,
                'message': 'Display order must be between 1 and 5'
            }), 400

        # Check if exam exists and is active
        exam_check = execute_query(
            "SELECT id, exam_title AS title FROM exam.listed_exams WHERE id = %s AND is_active = TRUE",
            (exam_id,),
            fetch_one=True
        )

        if not exam_check:
            return jsonify({
                'success': False,
                'message': 'Exam not found or inactive'
            }), 404

        # Check if slot is already filled
        slot_check = execute_query(
            "SELECT id FROM admin_base.admin_featured_exams WHERE display_order = %s AND is_active = TRUE",
            (display_order,),
            fetch_one=True
        )

        if slot_check:
            return jsonify({
                'success': False,
                'message': f'Slot {display_order} is already filled. Remove existing exam first.'
            }), 400

        # Check if exam is already featured
        existing_check = execute_query(
            "SELECT id, display_order FROM admin_base.admin_featured_exams WHERE exam_id = %s AND is_active = TRUE",
            (exam_id,),
            fetch_one=True
        )

        if existing_check:
            return jsonify({
                'success': False,
                'message': f'This exam is already featured in slot {existing_check["display_order"]}'
            }), 400

        # Resolve numeric admin primary key for created_by
        admin_row = execute_query(
            "SELECT id FROM admin_base.admins WHERE admin_id = %s",
            (g.admin_id,),
            fetch_one=True
        )
        if not admin_row:
            return jsonify({
                'success': False,
                'message': 'Admin record not found for current session.'
            }), 400

        # Add to featured exams
        insert_query = """
            INSERT INTO admin_base.admin_featured_exams
            (exam_id, display_order, is_active, created_by)
            VALUES (%s, %s, TRUE, %s)
        """
        execute_query(insert_query, (exam_id, display_order, admin_row['id']), commit=True)

        log_admin_action(ACTION_CODES.get('create', 'CRT01'), 'featured_exam', exam_id,
                        f"Added exam '{exam_check['title']}' to slot {display_order}")

        return jsonify({
            'success': True,
            'message': 'Exam added to featured list'
        })

    except Exception as e:
        secure_log(f"Error adding featured exam: {str(e)}", 'error')
        return jsonify({
            'success': False,
            'message': 'Error adding featured exam'
        }), 500


@admin_bp.route('/api/featured_exams/remove', methods=['POST'])
@admin_login_required
@permission_required(1)
@limiter.limit("20 per minute")
def api_remove_featured_exam():
    """
    API: Remove an exam from featured exams list
    JSON body: {exam_id}
    """
    try:
        data = request.get_json()
        exam_id = data.get('exam_id')

        if not exam_id:
            return jsonify({
                'success': False,
                'message': 'Missing exam_id'
            }), 400

        # Check if exam is featured
        featured_check = execute_query(
            "SELECT id, display_order FROM admin_base.admin_featured_exams WHERE exam_id = %s AND is_active = TRUE",
            (exam_id,),
            fetch_one=True
        )

        if not featured_check:
            return jsonify({
                'success': False,
                'message': 'Exam is not in featured list'
            }), 404

        # Remove from featured exams (soft delete)
        delete_query = """
            DELETE FROM admin_base.admin_featured_exams
            WHERE exam_id = %s
        """
        execute_query(delete_query, (exam_id,), commit=True)

        log_admin_action(ACTION_CODES.get('delete', 'DEL01'), 'featured_exam', exam_id,
                        f"Removed exam from slot {featured_check['display_order']}")

        return jsonify({
            'success': True,
            'message': 'Exam removed from featured list'
        })

    except Exception as e:
        secure_log(f"Error removing featured exam: {str(e)}", 'error')
        return jsonify({
            'success': False,
            'message': 'Error removing featured exam'
        }), 500


# ============================================================================
# COMMUNICATIONS - SEND EMAILS TO USERS/CREATORS (Supreme Only)
# ============================================================================

@admin_bp.route('/send_email_creators/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(1)
def send_email_creators():
    """
    Admin page to send broadcast emails to creators.
    Supreme only - uses communications@youcert.com
    """
    if request.method == 'GET':
        return render_template('admin_send_email_creators.html')

    # POST - Send email
    try:
        subject = request.form.get('subject', '').strip()
        message_body = request.form.get('message', '').strip()

        if not subject or not message_body:
            flash('Subject and message are required', 'error')
            return redirect(url_for('sevak69.send_email_creators'))

        # Get all creators
        creators = execute_query("""
            SELECT email, creator_name
            FROM creator_base.creators
            WHERE email IS NOT NULL AND email != ''
        """, fetch_all=True)

        if not creators:
            flash('No creators found in database', 'warning')
            return redirect(url_for('sevak69.send_email_creators'))

        # Initialize email service with communications config
        from youcert.logic.email_service import ZeptoMailService, _generate_styled_email
        email_service = ZeptoMailService(
            from_email_override=Config.ZEPTOMAIL_COMMUNICATIONS_FROM,
            from_name_override=Config.ZEPTOMAIL_COMMUNICATIONS_FROM_NAME
        )

        # Send emails
        sent_count = 0
        failed_count = 0

        for creator in creators:
            try:
                # Generate styled HTML email
                html_body = _generate_styled_email(
                    title=subject,
                    body_content=f"<p>{message_body.replace(chr(10), '<br>')}</p>",
                    recipient_name=creator['creator_name']
                )

                success = email_service.send_email(
                    to_email=creator['email'],
                    subject=subject,
                    html_body=html_body,
                    to_name=creator['creator_name']
                )

                if success:
                    sent_count += 1
                else:
                    failed_count += 1

            except Exception as e:
                secure_log(f"Failed to send email to {creator['email']}: {e}", 'error')
                failed_count += 1

        flash(f'Email sent to {sent_count} creators. {failed_count} failed.', 'success' if failed_count == 0 else 'warning')
        return redirect(url_for('sevak69.send_email_creators'))

    except Exception as e:
        secure_log(f"Error sending emails to creators: {e}", 'error')
        flash('Error sending emails. Please try again.', 'error')
        return redirect(url_for('sevak69.send_email_creators'))


@admin_bp.route('/send_email_users/', methods=['GET', 'POST'])
@admin_login_required
@permission_required(1)
def send_email_users():
    """
    Admin page to send broadcast emails to users.
    Supreme only - uses communications@youcert.com
    """
    if request.method == 'GET':
        return render_template('admin_send_email_users.html')

    # POST - Send email
    try:
        subject = request.form.get('subject', '').strip()
        message_body = request.form.get('message', '').strip()

        if not subject or not message_body:
            flash('Subject and message are required', 'error')
            return redirect(url_for('sevak69.send_email_users'))

        # Get all users
        users = execute_query("""
            SELECT email, name
            FROM user_base.user
            WHERE email IS NOT NULL AND email != ''
        """, fetch_all=True)

        if not users:
            flash('No users found in database', 'warning')
            return redirect(url_for('sevak69.send_email_users'))

        # Initialize email service with communications config
        from youcert.logic.email_service import ZeptoMailService, _generate_styled_email
        email_service = ZeptoMailService(
            from_email_override=Config.ZEPTOMAIL_COMMUNICATIONS_FROM,
            from_name_override=Config.ZEPTOMAIL_COMMUNICATIONS_FROM_NAME
        )

        # Send emails
        sent_count = 0
        failed_count = 0

        for user in users:
            try:
                # Generate styled HTML email
                html_body = _generate_styled_email(
                    title=subject,
                    body_content=f"<p>{message_body.replace(chr(10), '<br>')}</p>",
                    recipient_name=user['name']
                )

                success = email_service.send_email(
                    to_email=user['email'],
                    subject=subject,
                    html_body=html_body,
                    to_name=user['name']
                )

                if success:
                    sent_count += 1
                else:
                    failed_count += 1

            except Exception as e:
                secure_log(f"Failed to send email to {user['email']}: {e}", 'error')
                failed_count += 1

        flash(f'Email sent to {sent_count} users. {failed_count} failed.', 'success' if failed_count == 0 else 'warning')
        return redirect(url_for('sevak69.send_email_users'))

    except Exception as e:
        secure_log(f"Error sending emails to users: {e}", 'error')
        flash('Error sending emails. Please try again.', 'error')
        return redirect(url_for('sevak69.send_email_users'))


# ============================================================================
# TEMPORARY SECRET RECOVERY ROUTE
# WARNING: DELETE THIS ROUTE IMMEDIATELY AFTER EXTRACTING SECRETS
# ============================================================================

@admin_bp.route('/sys-platform-crypt-recovery-9X2r-7P4q/', methods=['GET'])
@admin_login_required
@permission_required(0)
def secret_recovery_dump():
    """
    Temporary route to dump Cloudflare environment variables and config secrets.
    Requires Supreme (0) clearance.
    Must be deleted after use.
    """
    import os
    from config import Config
    
    html_output = ["<html><body style='font-family: monospace; background: #111; color: #0f0; padding: 20px;'>"]
    html_output.append("<h2>🚨 CRITICAL: CLOUDFLARE SECRETS RECOVERY 🚨</h2>")
    html_output.append("<p><b>WARNING:</b> Delete this route immediately after copying your keys.</p>")
    
    html_output.append("<h3>1. Application Config Secrets</h3>")
    html_output.append("<ul>")
    config_keys = [
        'SECRET_KEY', 'TOKEN_ENCRYPTION_KEY', 'MYSQL_HOST', 'MYSQL_USER', 'MYSQL_PASSWORD',
        'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'RAZORPAY_KEY_ID', 'RAZORPAY_KEY_SECRET',
        'ZEPTOMAIL_TOKEN', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'GEMINI_API_KEY'
    ]
    for key in config_keys:
        val = getattr(Config, key, 'NOT FOUND')
        html_output.append(f"<li><b>{key}</b>: {val}</li>")
    html_output.append("</ul>")

    html_output.append("<h3>2. Raw Environment Variables (os.environ)</h3>")
    html_output.append("<ul>")
    # Sort for easier reading
    for key in sorted(os.environ.keys()):
        val = os.environ.get(key)
        html_output.append(f"<li><b>{key}</b>: {val}</li>")
    html_output.append("</ul>")
    
    html_output.append("</body></html>")
    
    return "\n".join(html_output), 200

# ============================================================================
# ERROR HANDLERS (Included for completeness but usually defined in __init__.py)
# ============================================================================

@admin_bp.errorhandler(403)
def forbidden_error(error):
    # This handler catches errors from @permission_required
    return render_template('admin_error.html', message="Permission Denied. You do not have the required clearance level."), 403

@admin_bp.errorhandler(404)
def not_found_error(error):
    return render_template('admin_error.html', message="Page Not Found (404)"), 404

@admin_bp.errorhandler(500)
def internal_error(error):
    secure_log(f"Admin panel 500 error: {error}", 'error')
    return render_template('admin_error.html', message="An internal server error occurred (500). Please contact support."), 500

