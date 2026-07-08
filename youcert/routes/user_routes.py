"""
Enhanced User Routes - CENTRALIZED DB & LOGGING VERSION
Restored full functionality with optimized infrastructure.
"""

from flask import Blueprint, render_template, session, url_for, redirect, request, flash, current_app, send_file, jsonify, g
from youcert import limiter
from youcert.logic import generate_certificate
# Import centralized utilities
from youcert import (
    execute_query, secure_log, get_user_cache, set_user_cache, delete_user_cache,
    save_file, get_file_url, get_google_client_config, download_file_content,
    encrypt_token, decrypt_token, validate_session_security, clear_user_session
)
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from cryptography.fernet import Fernet
import random
import string
import time
import tempfile
import os
import json
import mimetypes
import re
from datetime import datetime
from functools import wraps
from PIL import Image
import razorpay
import uuid
import traceback

user_bp = Blueprint('user', __name__)


# ============================================================================
# CONFIGURATION AND CONSTANTS
# ============================================================================

GOOGLE_SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/userinfo.email'
]


# File upload configurations
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MAX_FILE_SIZE = 8 * 1024 * 1024  # 8MB limit
VALID_IMAGE_MIMES = {'image/jpeg', 'image/png', 'image/gif'}
MAX_IMAGE_DIMENSION = 4096  # Maximum 4096x4096 pixels (prevents memory exhaustion)
# UPDATED: Changed exam cache timeout to 3 hours
EXAM_CACHE_TIMEOUT = 10800

CERTIFICATE_TEMPLATE_PATH = "youcert/static/certificate_templates/YOUCERT (6).png"
PASSING_PERCENTAGE = 80 # As requested

# ============================================================================
# ENHANCED SECURITY UTILITIES
# ============================================================================



def secure_login_user(user_id, name, email):
    """Enhanced secure login with session management and CSRF regeneration"""
    from youcert import get_session_fingerprint
    
    session['user_id'] = user_id
    session['name'] = name
    session['email'] = email
    session.permanent = True
    
    # Add session fingerprinting
    session['fingerprint'] = get_session_fingerprint()
    session['last_activity'] = datetime.now().isoformat()
    
    # Regenerate CSRF token after login for security
    from flask_wtf.csrf import generate_csrf
    generate_csrf()


# File validation utilities
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def is_valid_image(file):
    """Enhanced file validation with MIME type, size, and magic bytes checks"""
    if not file or not file.filename:
        return False
    
    # Check file size
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    
    if size > MAX_FILE_SIZE:
        return False
    
    # Check MIME type from filename
    mime_type = mimetypes.guess_type(file.filename)[0]
    if mime_type not in VALID_IMAGE_MIMES:
        return False
    
    # Check magic bytes using PIL
    try:
        file.seek(0)
        img = Image.open(file)
        img.verify()
        
        if img.format.lower() not in ['jpeg', 'png', 'gif']:
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
        secure_log(f"Image validation failed: {str(e)}", 'warning')
        return False


# ============================================================================
# ENHANCED DECORATORS
# ============================================================================

# In user_routes.py

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id_in_session = session.get('user_id')
        if not user_id_in_session:
            flash('Please log in first.', 'warning')
            return redirect(url_for('user.oauth_login'))

        # 1. CRITICAL FIX: Validate session security and clear session on failure
        if not validate_session_security():
            # Explicitly clear the session to stop the redirect loop
            clear_user_session()
            flash('Session expired. Please log in again.', 'warning')
            return redirect(url_for('user.oauth_login'))

        # 2. CHECK CACHE FIRST (The 15k RPS Fix)
        # We cache the user status for 300 seconds (5 minutes)
        cache_key = f"user_active_status_{user_id_in_session}"
        cached_user = get_user_cache(cache_key, user_id=user_id_in_session)

        if cached_user:
            # If in cache, use it (0 Database impact)
            user = cached_user
        else:
            # If not in cache, query DB (Once every 5 mins per user)
            try:
                user = execute_query("""
                    SELECT user_id, name, email, is_active
                    FROM user_base.user
                    WHERE user_id = %s
                """, (user_id_in_session,), fetch_one=True)
                
                # Save to cache
                if user:
                    set_user_cache(cache_key, user, user_id=user_id_in_session, timeout=300)
            except Exception as e:
                secure_log(f"Session DB check failed: {e}", 'error', user_id=user_id_in_session)
                return redirect(url_for('user.oauth_login'))

        # 3. Validation Logic
        if not user or not user['is_active']:
            clear_user_session()  # Only clear user session, preserve creator/admin
            # Clear cache if they are banned
            delete_user_cache(cache_key, user_id=user_id_in_session)
            flash('Account deactivated.', 'error')
            return redirect(url_for('user.oauth_login'))

        g.user_id = user['user_id']
        g.user_name = user['name']
        
        return f(*args, **kwargs)
    return decorated_function


def require_origin_validation(f):
    """Enhanced decorator to validate origin for sensitive AJAX routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == 'POST' and request.is_json:
            origin = request.headers.get('Origin')
            referer = request.headers.get('Referer')
            
            # FIXED: Include production URLs (both www and non-www)
            allowed_origins = [
                'http://localhost:5000',
                'http://127.0.0.1:5000',
                'http://localhost:5001',
                'http://127.0.0.1:5001',
                'https://youcert.com',
                'https://www.youcert.com'
            ]
            
            origin_valid = origin in allowed_origins if origin else False
            referer_valid = any(referer and referer.startswith(orig) for orig in allowed_origins) if referer else False
            
            if not (origin_valid or referer_valid):
                secure_log(f"Invalid origin/referer for request", 'warning')
                return jsonify({'error': 'Invalid origin'}), 403
        
        return f(*args, **kwargs)
    return decorated_function


# ============================================================================
# BUSINESS LOGIC UTILITIES
# ============================================================================

def get_razorpay_client():
    """Initialize Razorpay client with enhanced error handling"""
    try:
        key_id = current_app.config.get('RAZORPAY_KEY_ID', '').strip()
        key_secret = current_app.config.get('RAZORPAY_KEY_SECRET', '').strip()
        
        if not key_id or not key_secret:
            secure_log("Razorpay credentials missing in config", 'error')
            return None
        
        if len(key_id) < 10 or len(key_secret) < 10:
            secure_log("Razorpay credentials appear invalid", 'error')
            return None
        
        secure_log(f"Initializing Razorpay with key format: {key_id[:8]}...", 'info')
        client = razorpay.Client(auth=(key_id, key_secret))
        
        try:
            client.payment.fetch_all({'count': 1})
            secure_log("Razorpay client initialized successfully", 'info')
        except Exception as test_error:
            secure_log(f"Razorpay authentication failed: {str(test_error)}", 'error')
            return None
        
        return client
    except Exception as e:
        secure_log(f"Razorpay client initialization failed: {str(e)}", 'error')
        return None


def generate_unique_order_number():
    """Generate unique order number for payments"""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"ORD{timestamp}{random_suffix}"


# ============================================================================
# AUTH CHECK API (FOR PUBLIC PAGES)
# ============================================================================

@user_bp.route('/api/check-auth', methods=['GET'])
@limiter.limit("60 per minute")
def check_auth():
    """
    Check if user is authenticated.
    Used by public pages to determine login status before payment.

    Returns:
        JSON with authenticated status
    """
    try:
        if 'user_id' in session and validate_session_security():
            return jsonify({
                'authenticated': True,
                'user_id': session.get('user_id')
            })
        return jsonify({
            'authenticated': False
        })
    except Exception as e:
        secure_log(f"Auth check error: {str(e)}", 'error')
        return jsonify({
            'authenticated': False
        })


# ============================================================================
# OAUTH AUTHENTICATION ROUTES
# ============================================================================

@user_bp.route('/login/')
@limiter.limit("10 per minute")
def oauth_login():
    """Initiate OAuth login process with enhanced security"""
    # Get the 'next' parameter for post-login redirect
    next_url = request.args.get('next', '')

    # 1. CRITICAL FIX: Validate session before redirecting to prevent loop
    if 'user_id' in session:
        if validate_session_security():
            # If already logged in and has next URL, redirect there
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect(url_for('user.index'))
        else:
            clear_user_session()

    try:
        # 2. Configure the OAuth Flow
        client_config = get_google_client_config()
        flow = InstalledAppFlow.from_client_config(client_config, GOOGLE_SCOPES)

        # --- FIX: Explicitly set the Redirect URI ---
        # This adds the '&redirect_uri=...' parameter to the Google URL
        flow.redirect_uri = url_for('user.oauth_callback', _external=True)

        # 3. Generate the Google Login URL
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent' # Forces refresh_token generation
        )

        # 4. Save state to session for security (CSRF protection)
        session['oauth_state'] = state
        session['oauth_state_timestamp'] = time.time()

        # 5. Save next URL for post-login redirect (only internal URLs)
        if next_url and next_url.startswith('/'):
            session['login_next_url'] = next_url

        secure_log(f"OAuth login initiated. Redirecting to: {flow.redirect_uri}")
        return redirect(authorization_url)
    
    except Exception as e:
        secure_log(f"OAuth initiation error: {str(e)}", 'error')
        flash("Login failed. Please try again.", "error")
        return render_template("base.html")


@user_bp.route('/oauth_callback/')
@limiter.limit("10 per minute")
def oauth_callback():
    """Enhanced OAuth callback using execute_query and centralized encryption"""
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    
    stored_state = session.get('oauth_state')
    state_timestamp = session.get('oauth_state_timestamp', 0)
    
    if time.time() - state_timestamp > 600:
        secure_log("OAuth state expired", 'warning')
        flash("Authentication session expired. Please try again.", "error")
        return redirect(url_for('user.oauth_login'))
    
    if error or not code or state != stored_state:
        secure_log("OAuth callback failed - invalid state or error", 'warning')
        flash("Authentication failed. Please try again.", "error")
        return redirect(url_for('user.oauth_login'))
    
    try:
        client_config = get_google_client_config()
        flow = InstalledAppFlow.from_client_config(client_config, GOOGLE_SCOPES)
        flow.redirect_uri = url_for('user.oauth_callback', _external=True)
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
        oauth2_service = build('oauth2', 'v2', credentials=credentials)
        user_info = oauth2_service.userinfo().get().execute()

        google_id = user_info.get('id')
        email = user_info.get('email')
        name = user_info.get('name')
        raw_profile_picture_url = user_info.get('picture')  # Get Google profile picture URL
        
        # Download and save the profile picture to R2 locally instead of retaining the raw URL
        profile_picture_url = raw_profile_picture_url
        if raw_profile_picture_url:
            try:
                import requests
                from PIL import Image
                import io
                
                response = requests.get(raw_profile_picture_url, timeout=10)
                if response.status_code == 200:
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
                    
                    # Generate a unique filename and save via centralized storage
                    filename = f"user_{google_id}_{int(time.time())}.jpg"
                    saved_path = save_file(output, 'profile_pictures', filename)
                    if saved_path:
                        profile_picture_url = saved_path
                        secure_log(f"User profile picture downloaded to R2: {profile_picture_url}", 'info')
            except Exception as e:
                secure_log(f"Failed to download Google profile picture for user {email}: {str(e)}", 'warning')
                # Fallback to the raw URL if download fails so login isn't blocked
                profile_picture_url = raw_profile_picture_url

        if not google_id or not email or not name:
            secure_log("Failed to retrieve user info from Google", 'warning')
            flash("Failed to retrieve user information from Google.", "error")
            return redirect(url_for('user.oauth_login'))
        
        # Use the cached config dictionary
        client_id = client_config['web']['client_id']
        client_secret = client_config['web']['client_secret']
        
        # Check if user already exists
        existing_user = execute_query(
            "SELECT user_id, name, email, is_active FROM user_base.user WHERE email = %s",
            (email,), fetch_one=True
        )
        
        # Encrypt tokens using centralized function
        encrypted_token = encrypt_token(credentials.token)
        encrypted_refresh_token = encrypt_token(credentials.refresh_token) if credentials.refresh_token else None
        encrypted_client_id = encrypt_token(client_id)
        encrypted_client_secret = encrypt_token(client_secret)
        encrypted_token_uri = encrypt_token(credentials.token_uri or 'https://oauth2.googleapis.com/token')

        # Check for encryption failure
        if not encrypted_token or not encrypted_client_id or not encrypted_client_secret:
            secure_log("Centralized encryption failed during OAuth callback", 'error')
            flash("System error during login encryption. Please try again.", "error")
            return redirect(url_for('user.oauth_login'))
        
        if existing_user:
            if not existing_user['is_active']:
                secure_log(f"Login attempt failed for deactivated user: {email}", 'warning', existing_user['user_id'])
                flash("Your account has been deactivated. Please contact support.", "error")
                return redirect(url_for('user.oauth_login'))

            execute_query("""
                UPDATE user_base.user
                SET oauth_token = %s, refresh_token = %s, client_id = %s,
                    client_secret = %s, token_uri = %s, token_expiry = %s,
                    profile_picture = %s, last_login = NOW(), updated_at = NOW()
                WHERE user_id = %s
            """, (encrypted_token, encrypted_refresh_token, encrypted_client_id,
                  encrypted_client_secret, encrypted_token_uri, credentials.expiry,
                  profile_picture_url, existing_user['user_id']), commit=True)
            
            secure_login_user(existing_user['user_id'], existing_user['name'], existing_user['email'])

            secure_log("User login successful", 'info', existing_user['user_id'])
            flash(f"Welcome back, {existing_user['name']}!", "success")

            # Check for post-login redirect URL (from shareable exam links, etc.)
            next_url = session.pop('login_next_url', None)
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect(url_for('user.index'))
        else:
            # New user
            user_id = f"USR_{int(time.time())}_{random.randint(1000, 9999)}"
            
            execute_query("""
                INSERT INTO user_base.user
                (user_id, name, email, oauth_token, refresh_token, client_id,
                 client_secret, token_uri, token_expiry, profile_picture, email_verified, is_active, password_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (user_id, name, email, encrypted_token, encrypted_refresh_token,
                  encrypted_client_id, encrypted_client_secret, encrypted_token_uri,
                  credentials.expiry, profile_picture_url, True, True, ''), commit=True)
            
            secure_login_user(user_id, name, email)
            session['new_user'] = True
            
            secure_log("New user registered", 'info', user_id)
            flash(f"Welcome to the platform, {name}! Please complete your profile.", "success")
            return redirect(url_for('user.complete_profile'))
    
    except Exception as e:
        secure_log(f"OAuth callback error: {str(e)}", 'error')
        flash("Authentication failed. Please try again.", "error")
        return redirect(url_for('user.oauth_login'))
    finally:
        session.pop('oauth_state', None)
        session.pop('oauth_state_timestamp', None)


@user_bp.route('/complete_profile/', methods=['GET', 'POST'])
@login_required
@limiter.limit("10 per minute")
def complete_profile():
    """Complete user profile using execute_query"""
    if not session.get('new_user'):
        return redirect(url_for('user.index'))
    
    if request.method == 'POST':
        try:
            name_in_certificate = request.form.get('name_in_certificate', '').strip()
            phone = request.form.get('phone', '').strip()
            date_of_birth = request.form.get('date_of_birth')
            gender = request.form.get('gender')
            address = request.form.get('address', '').strip()

            # Validate certificate name (required field)
            if not name_in_certificate:
                flash("Certificate name is required.", "error")
                return render_template('complete_profile.html')

            if not re.match(r'^[\w\s\-\.]{2,200}$', name_in_certificate):
                flash("Invalid characters in certificate name. Only letters, spaces, hyphens, and periods are allowed.", "error")
                return render_template('complete_profile.html')

            if len(name_in_certificate) > 200:
                flash("Certificate name is too long. Maximum 200 characters.", "error")
                return render_template('complete_profile.html')

            if phone and not re.match(r'^[+]?[1-9][0-9]{9,14}$', phone):
                flash("Please enter a valid phone number.", "error")
                return render_template('complete_profile.html')

            execute_query("""
                UPDATE user_base.user
                SET name_in_certificate = %s, phone = %s, date_of_birth = %s, gender = %s, address = %s, updated_at = NOW()
                WHERE user_id = %s
            """, (name_in_certificate, phone, date_of_birth, gender, address, session['user_id']), commit=True)
            
            session.pop('new_user', None)

            secure_log("Profile completed successfully", 'info', session['user_id'])
            flash("Profile completed successfully! Welcome to the platform.", "success")

            # Check for post-login redirect URL (from shareable exam links, etc.)
            next_url = session.pop('login_next_url', None)
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect(url_for('user.index'))
        
        except Exception as e:
            secure_log(f"Profile completion error: {str(e)}", 'error', session['user_id'])
            flash("Could not complete profile. Please try again.", "error")
    
    return render_template('complete_profile.html')


@user_bp.route('/logout/')
@limiter.limit("10 per minute")
def logout():
    if 'user_id' in session:
        user_name = session.get('name', 'User')
        user_id = session.get('user_id')
        clear_user_session()  # Only clear user session, preserve creator/admin
        secure_log("User logout successful", 'info', user_id)
        flash(f"Goodbye {user_name}! You have been successfully logged out.", "success")
    else:
        flash("You were not logged in.", "info")

    return redirect(url_for('user.oauth_login'))


# ============================================================================
# PROTECTED USER DASHBOARD ROUTES
# ============================================================================

@user_bp.route('/home/')
@limiter.limit("30 per minute")
@login_required
def index():
    secure_log("Dashboard accessed", 'info', session['user_id'])
    return render_template('index.html')


@user_bp.route('/api/dashboard_data')
@login_required
@require_origin_validation
@limiter.limit("30 per minute")
def get_dashboard_data():
    """API endpoint to get dashboard data using execute_query"""
    try:
        user_id = session['user_id']
        
        # Get user statistics
        stats = execute_query("""
            SELECT
            COUNT(DISTINCT ur.unique_exam_number) as completed_exams,
            COUNT(DISTINCT pe.unique_exam_number) as purchased_exams,
            COALESCE(SUM(ur.amount_paid), 0) as total_spent,
            COALESCE(AVG(ur.marks_obtained), 0) as avg_marks,
            COALESCE(AVG((ur.marks_obtained/ur.total_marks)*100), 0) as avg_percentage
            FROM user_base.user_result ur
            RIGHT JOIN exam.purchased_exams pe ON ur.user_id = pe.user_id
            AND ur.unique_exam_number = pe.unique_exam_number
            WHERE pe.user_id = %s AND pe.payment_status = 'completed'
        """, (user_id,), fetch_one=True)
        
        # Get recent exam activity
        recent_exams = execute_query("""
            SELECT ur.unique_exam_number, ur.marks_obtained, ur.total_marks,
            ur.completed_at, le.exam_title, le.channel_name,
            ROUND((ur.marks_obtained/ur.total_marks)*100, 2) as percentage,
            ur.certificate_url
            FROM user_base.user_result ur
            JOIN exam.listed_exams le ON ur.unique_exam_number = le.unique_exam_number
            WHERE ur.user_id = %s
            ORDER BY ur.completed_at DESC
            LIMIT 5
        """, (user_id,), fetch_all=True)
        
        stats_dict = dict(stats) if stats else {}
        for key in stats_dict:
            if isinstance(stats_dict[key], (int, float)):
                stats_dict[key] = float(stats_dict[key]) if isinstance(stats_dict[key], float) else int(stats_dict[key])
        
        recent_list = []
        if recent_exams:
            for exam in recent_exams:
                exam_dict = dict(exam)
                if exam_dict.get('completed_at'):
                    exam_dict['completed_at'] = exam_dict['completed_at'].strftime('%Y-%m-%d %H:%M')
                recent_list.append(exam_dict)
        
        return jsonify({
            'success': True,
            'stats': stats_dict,
            'recent_exams': recent_list
        })
    except Exception as e:
        secure_log(f"Dashboard API error: {str(e)}", 'error', session['user_id'])
        return jsonify({'success': False, 'message': 'Could not load dashboard data'})


@user_bp.route('/api/search_exams')
@login_required
@require_origin_validation
@limiter.limit("20 per minute")
def search_exams():
    query = request.args.get('q', '').strip()
    if not query or len(query) < 2:
        return jsonify({'success': False, 'message': 'Search query must be at least 2 characters'})

    query = re.sub(r'[^a-zA-Z0-9\s\-_]', '', query)
    if not query:
        return jsonify({'success': False, 'message': 'Invalid search query'})

    try:
        user_id = session.get('user_id')
        search_pattern = f"%{query}%"

        # Include purchase and completion status in search results
        exams = execute_query("""
            SELECT le.unique_exam_number, le.exam_title, le.exam_description,
                   le.channel_name, le.exam_price, le.thumbnail_image, le.is_active,
                   CASE WHEN pe.unique_exam_number IS NOT NULL THEN 1 ELSE 0 END as is_purchased,
                   CASE WHEN ur.unique_exam_number IS NOT NULL THEN 1 ELSE 0 END as is_completed
            FROM exam.listed_exams le
            LEFT JOIN exam.purchased_exams pe
                ON le.unique_exam_number = pe.unique_exam_number
                AND pe.user_id = %s AND pe.payment_status = 'completed'
            LEFT JOIN user_base.user_result ur
                ON le.unique_exam_number = ur.unique_exam_number
                AND ur.user_id = %s
            WHERE (le.exam_title LIKE %s OR le.exam_description LIKE %s OR le.channel_name LIKE %s)
            AND le.is_active = true
            ORDER BY le.exam_title
            LIMIT 10
        """, (user_id, user_id, search_pattern, search_pattern, search_pattern), fetch_all=True)

        # Process thumbnails and convert to dict
        exam_list = []
        if exams:
            for exam in exams:
                d = dict(exam)
                if d.get('thumbnail_image'):
                    d['thumbnail_image'] = get_file_url(d['thumbnail_image'])
                # Convert int to bool for frontend
                d['is_purchased'] = bool(d.get('is_purchased', 0))
                d['is_completed'] = bool(d.get('is_completed', 0))
                exam_list.append(d)

        return jsonify({
            'success': True,
            'exams': exam_list
        })
    except Exception as e:
        secure_log(f"Search API error: {str(e)}", 'error', session.get('user_id'))
        return jsonify({'success': False, 'message': 'Search failed'})


# ============================================================================
# USER PROFILE MANAGEMENT ROUTES
# ============================================================================

@user_bp.route('/user_profile/')
@limiter.limit("20 per minute")
@login_required
def user_profile():
    try:
        user_data = execute_query("""
            SELECT user_id, name, name_in_certificate, email, phone, date_of_birth, 
                   gender, address, created_at, last_login, profile_picture,
                   email_verified, is_active, updated_at
            FROM user_base.user WHERE user_id = %s
        """, (session['user_id'],), fetch_one=True)
        
        if not user_data:
            flash("User profile not found.", "error")
            return redirect(url_for('user.index'))
            
        # Convert relative profile picture path to a valid storage URL
        user_dict = dict(user_data)
        profile_pic = user_dict.get('profile_picture')
        if profile_pic and not profile_pic.startswith('http'):
            user_dict['profile_picture'] = get_file_url(profile_pic)
            
        stats = execute_query("""
            SELECT
            COUNT(DISTINCT pe.unique_exam_number) as total_purchased,
            COUNT(DISTINCT ur.unique_exam_number) as total_completed,
            COALESCE(AVG((ur.marks_obtained/ur.total_marks)*100), 0) as average_score,
            COALESCE(SUM(ur.amount_paid), 0) as total_spent
            FROM user_base.user u
            LEFT JOIN exam.purchased_exams pe ON u.user_id = pe.user_id
            AND pe.payment_status = 'completed'
            LEFT JOIN user_base.user_result ur ON u.user_id = ur.user_id
            WHERE u.user_id = %s
        """, (session['user_id'],), fetch_one=True)
        
        secure_log("Profile page accessed", 'info', session['user_id'])
        return render_template('user_profile.html', user=user_dict, stats=stats)
    
    except Exception as e:
        secure_log(f"Profile error: {str(e)}", 'error', session['user_id'])
        flash("Could not load profile data.", "error")
        return render_template('user_profile.html', user=None, stats=None)


@user_bp.route('/update_certificate_name/', methods=['POST'])
@login_required
@limiter.limit("3 per minute")
def update_certificate_name():
    user_id = session.get('user_id')
    new_name = request.form.get('name_in_certificate', '').strip()

    if not new_name:
        flash("Certificate name cannot be empty.", "error")
        return redirect(url_for('user.user_profile'))
    
    if not re.match(r'^[\w\s\-\.]{2,200}$', new_name):
         flash("Invalid characters in name. Only letters, spaces, hyphens, and periods are allowed.", "error")
         return redirect(url_for('user.user_profile'))
    
    if len(new_name) > 200:
        flash("Name is too long. Maximum 200 characters.", "error")
        return redirect(url_for('user.user_profile'))
    
    try:
        user = execute_query("SELECT name_in_certificate FROM user_base.user WHERE user_id = %s", (user_id,), fetch_one=True)
        
        if not user:
            flash("User not found.", "error")
            return redirect(url_for('user.user_profile'))
        
        if user.get('name_in_certificate') and user['name_in_certificate'].strip():
            flash("Certificate name is already set and cannot be changed.", "warning")
            return redirect(url_for('user.user_profile'))

        # execute_query returns None on commit. We trust the query logic.
        execute_query("""
            UPDATE user_base.user
            SET name_in_certificate = %s, updated_at = NOW()
            WHERE user_id = %s AND (name_in_certificate IS NULL OR name_in_certificate = '')
        """, (new_name, user_id), commit=True)
        
        secure_log(f"Certificate name set successfully for user {user_id}", 'info', user_id)
        flash("Certificate name updated successfully!", "success")
    
    except Exception as e:
        secure_log(f"Certificate name update error: {str(e)}", 'error', user_id)
        flash("An error occurred. Please try again.", "error")

    return redirect(url_for('user.user_profile'))


@user_bp.route('/update_profile/', methods=['POST'])
@login_required
@limiter.limit("5 per minute")
def update_profile():
    try:
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()
        
        if phone and not re.match(r'^[+]?[1-9][0-9]{9,14}$', phone):
            flash("Please enter a valid phone number.", "error")
            return redirect(url_for('user.user_profile'))
        
        if len(address) > 500:
            flash("Address is too long. Maximum 500 characters allowed.", "error")
            return redirect(url_for('user.user_profile'))
        
        execute_query("""
            UPDATE user_base.user
            SET phone = %s, address = %s, updated_at = NOW()
            WHERE user_id = %s
        """, (phone, address, session['user_id']), commit=True)
        
        secure_log("Profile updated successfully", 'info', session['user_id'])
        flash("Profile updated successfully.", "success")
        return redirect(url_for('user.user_profile'))
    except Exception as e:
        secure_log(f"Profile update error", 'error', session['user_id'])
        flash("Could not update profile. Please try again.", "error")
        return redirect(url_for('user.user_profile'))


# ============================================================================
# EXAM BROWSING AND PURCHASE ROUTES
# ============================================================================

@user_bp.route('/exams/')
@limiter.limit("20 per minute")
@login_required
def exams():
    secure_log("Exams page accessed", 'info', session['user_id'])
    return render_template('exams.html')


@user_bp.route('/api/available_exams')
@login_required
@require_origin_validation
@limiter.limit("30 per minute")
def get_available_exams():
    try:
        page = int(request.args.get('page', 1))
        per_page = min(int(request.args.get('per_page', 10)), 50)
        offset = (page - 1) * per_page
        
        total_data = execute_query("SELECT COUNT(*) as total FROM exam.listed_exams WHERE is_active = true", fetch_one=True)
        total_count = total_data['total']
        
        exams = execute_query("""
            SELECT unique_exam_number, exam_title, exam_description, channel_name,
            exam_price, thumbnail_image, created_at
            FROM exam.listed_exams
            WHERE is_active = true
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, (per_page, offset), fetch_all=True)
        
        # [FIX] Process exams to generate correct URLs
        exam_list = []
        if exams:
            for exam in exams:
                exam_dict = dict(exam)
                # Convert raw DB path to clean URL
                if exam_dict.get('thumbnail_image'):
                    exam_dict['thumbnail_image'] = get_file_url(exam_dict['thumbnail_image'])
                exam_list.append(exam_dict)
        
        return jsonify({
            'success': True,
            'exams': exam_list,
            'pagination': {
                'current_page': page,
                'per_page': per_page,
                'total_count': total_count,
                'total_pages': (total_count + per_page - 1) // per_page
            }
        })
    except Exception as e:
        secure_log(f"Available exams API error: {str(e)}", 'error', session['user_id'])
        return jsonify({'success': False, 'message': 'Could not load exams'})


@user_bp.route('/view_exams/<exam_id>')
@limiter.limit("20 per minute")
@login_required
def view_exams(exam_id):
    exam_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(exam_id))
    if not exam_id:
        flash("Invalid exam ID.", "error")
        return redirect(url_for('user.exams'))
    
    try:
        exam = execute_query("""
            SELECT le.*,
            CASE WHEN pe.unique_exam_number IS NOT NULL THEN 1 ELSE 0 END as is_purchased,
            CASE WHEN ur.unique_exam_number IS NOT NULL THEN 1 ELSE 0 END as is_completed
            FROM exam.listed_exams le
            LEFT JOIN exam.purchased_exams pe ON le.unique_exam_number = pe.unique_exam_number
            AND pe.user_id = %s AND pe.payment_status = 'completed'
            LEFT JOIN user_base.user_result ur ON le.unique_exam_number = ur.unique_exam_number
            AND ur.user_id = %s
            WHERE le.unique_exam_number = %s AND le.is_active = true
        """, (session['user_id'], session['user_id'], exam_id), fetch_one=True)
        
        if not exam:
            flash("Exam not found or no longer available.", "error")
            return redirect(url_for('user.exams'))
        
        # Fix thumbnail URL for template rendering
        exam = dict(exam)
        if exam.get('thumbnail_image'):
            exam['thumbnail_image'] = get_file_url(exam['thumbnail_image'])

        secure_log("Exam details viewed", 'info', session['user_id'])
        return render_template('view_exams.html', exam=exam)
    except Exception as e:
        secure_log(f"View exam error", 'error', session['user_id'])
        flash("Could not load exam details.", "error")
        return redirect(url_for('user.exams'))


@user_bp.route('/api/exam_details/<exam_id>')
@login_required
@require_origin_validation
@limiter.limit("20 per minute")
def get_exam_details(exam_id):
    exam_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(exam_id))
    if not exam_id:
        return jsonify({'success': False, 'message': 'Invalid exam ID'})

    try:
        exam = execute_query("""
            SELECT le.*,
            cb.profile_photo_jpg as creator_profile_photo,
            CASE WHEN pe.unique_exam_number IS NOT NULL THEN 1 ELSE 0 END as is_purchased,
            CASE WHEN ur.unique_exam_number IS NOT NULL THEN 1 ELSE 0 END as is_completed
            FROM exam.listed_exams le
            LEFT JOIN creator_base.creators cb ON le.channel_id = cb.channel_id
            LEFT JOIN exam.purchased_exams pe ON le.unique_exam_number = pe.unique_exam_number
            AND pe.user_id = %s AND pe.payment_status = 'completed'
            LEFT JOIN user_base.user_result ur ON le.unique_exam_number = ur.unique_exam_number
            AND ur.user_id = %s
            WHERE le.unique_exam_number = %s AND le.is_active = true
        """, (session['user_id'], session['user_id'], exam_id), fetch_one=True)
        
        if not exam:
            return jsonify({'success': False, 'message': 'Exam not found'})
        
        # [FIX] Convert to dict and fix image path
        exam_dict = dict(exam)

        if exam_dict.get('thumbnail_image'):
            # Convert 'thumbnails/img.jpg' -> '/static/thumbnails/img.jpg'
            exam_dict['thumbnail_image'] = get_file_url(exam_dict['thumbnail_image'])

        # Convert creator profile photo URL
        if exam_dict.get('creator_profile_photo'):
            exam_dict['creator_profile_photo'] = get_file_url(exam_dict['creator_profile_photo'])

        # Add YouTube source URL (video or playlist)
        youtube_url = None
        if exam_dict.get('video_id'):
            youtube_url = f"https://www.youtube.com/watch?v={exam_dict['video_id']}"
        elif exam_dict.get('playlist_id'):
            youtube_url = f"https://www.youtube.com/playlist?list={exam_dict['playlist_id']}"

        exam_dict['youtube_url'] = youtube_url
        exam_dict['source_type'] = 'video' if exam_dict.get('video_id') else ('playlist' if exam_dict.get('playlist_id') else None)

        return jsonify({
            'success': True,
            'exam': exam_dict
        })
    except Exception as e:
        secure_log(f"Exam details API error", 'error', session['user_id'])
        return jsonify({'success': False, 'message': 'Could not load exam details'})


# ============================================================================
# PAYMENT AND PURCHASE ROUTES
# ============================================================================

@user_bp.route('/api/create_order', methods=['POST'])
@login_required
@require_origin_validation
@limiter.limit("10 per minute")
def create_order():
    try:
        data = request.get_json()
        exam_id = data.get('exam_id', '').strip()
        exam_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(exam_id))
        
        if not exam_id:
            return jsonify({'success': False, 'message': 'Invalid exam ID'})
        
        exam = execute_query("""
            SELECT unique_exam_number, exam_title, exam_price, channel_id
            FROM exam.listed_exams
            WHERE unique_exam_number = %s AND is_active = true
        """, (exam_id,), fetch_one=True)
        
        if not exam:
            return jsonify({'success': False, 'message': 'Exam not found'})
        
        exam_price = float(exam['exam_price'])
        if exam_price <= 0:
            return jsonify({'success': False, 'message': 'Invalid exam price'})
        
        existing = execute_query("""
            SELECT unique_order_number FROM exam.purchased_exams
            WHERE user_id = %s AND unique_exam_number = %s AND payment_status = 'completed'
        """, (session['user_id'], exam_id), fetch_one=True)
        
        if existing:
            return jsonify({'success': False, 'message': 'You have already purchased this exam'})
        
        razorpay_client = get_razorpay_client()
        if not razorpay_client:
            secure_log("Razorpay client initialization failed", 'error', session['user_id'])
            return jsonify({'success': False, 'message': 'Payment service unavailable.'})
        
        amount_in_paise = int(exam_price * 100)
        receipt_id = f"ex_{exam_id}_{session['user_id']}"[:40]
        
        order_data = {
            'amount': amount_in_paise,
            'currency': 'INR',
            'receipt': receipt_id,
            'payment_capture': 1,
            'notes': {
                'exam_id': exam_id,
                'user_id': session['user_id'],
                'exam_title': exam['exam_title'][:50]
            }
        }
        
        try:
            razorpay_order = razorpay_client.order.create(data=order_data)
        except Exception as e:
            secure_log(f"Razorpay order creation error: {str(e)}", 'error', session['user_id'])
            return jsonify({'success': False, 'message': f'Payment initialization failed: {str(e)}'})
        
        unique_order_number = generate_unique_order_number()
        
        execute_query("""
            INSERT INTO exam.purchased_exams
            (unique_order_number, user_id, channel_id, unique_exam_number,
            payment_date, payment_time, payment_id, amount_paid, payment_status,
            payment_method, razorpay_order_id)
            VALUES (%s, %s, %s, %s, CURDATE(), CURTIME(), %s, %s, %s, %s, %s)
        """, (unique_order_number, session['user_id'], exam['channel_id'], exam_id,
              razorpay_order['id'], exam_price, 'pending', 'razorpay',
              razorpay_order['id']), commit=True)
        
        secure_log("Order created successfully", 'info', session['user_id'])
        
        return jsonify({
            'success': True,
            'order_id': razorpay_order['id'],
            'amount': amount_in_paise,
            'currency': 'INR',
            'exam_title': exam['exam_title'],
            'unique_order_number': unique_order_number,
            'key_id': current_app.config.get('RAZORPAY_KEY_ID')
        })
    except Exception as e:
        secure_log(f"Create order error: {str(e)}", 'error', session['user_id'])
        return jsonify({'success': False, 'message': f'Order creation failed: {str(e)}'})


@user_bp.route('/api/verify_payment', methods=['POST'])
@login_required
@require_origin_validation
@limiter.limit("15 per minute")
def verify_payment():
    try:
        data = request.get_json()
        razorpay_order_id = data.get('razorpay_order_id')
        razorpay_payment_id = data.get('razorpay_payment_id')
        razorpay_signature = data.get('razorpay_signature')
        exam_id = data.get('exam_id')
        
        if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
            return jsonify({'success': False, 'message': 'Missing payment details'})
        
        razorpay_client = get_razorpay_client()
        if not razorpay_client:
            return jsonify({'success': False, 'message': 'Payment service unavailable'})
        
        razorpay_client.utility.verify_payment_signature({
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        })
        
        execute_query("""
            UPDATE exam.purchased_exams
            SET payment_status = 'completed',
            razorpay_payment_id = %s,
            razorpay_signature = %s,
            updated_at = NOW()
            WHERE razorpay_order_id = %s AND user_id = %s AND payment_status = 'pending'
        """, (razorpay_payment_id, razorpay_signature, razorpay_order_id, session['user_id']), commit=True)
        
        secure_log("Payment verified successfully", 'info', session['user_id'])
        
        return jsonify({
            'success': True,
            'message': 'Payment successful! You can now access the exam.',
            'redirect_url': f'/exam_form/{exam_id}' if exam_id else '/completed_exams/'
        })
    except Exception as e:
        secure_log(f"Payment verification error: {str(e)}", 'error', session['user_id'])
        return jsonify({'success': False, 'message': 'Payment verification failed'})


@user_bp.route('/api/purchased_exams')
@limiter.limit("20 per minute")
@login_required
def get_purchased_exams():
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'User not logged in'})
        
        # ... (Query remains the same) ...
        sql_query = """
            SELECT
                pe.unique_exam_number, pe.unique_order_number, pe.payment_date,
                pe.amount_paid, pe.payment_status, le.exam_title,
                le.exam_description, le.channel_name, le.thumbnail_image,
                le.exam_price, ur.marks_obtained, ur.total_marks, ur.completed_at
            FROM exam.purchased_exams pe
            JOIN exam.listed_exams le ON pe.unique_exam_number = le.unique_exam_number
            LEFT JOIN user_base.user_result ur ON pe.unique_exam_number = ur.unique_exam_number AND pe.user_id = ur.user_id
            WHERE pe.user_id = %s AND pe.payment_status = 'completed' AND le.is_active = 1
            ORDER BY pe.created_at DESC;
        """
        
        all_exam_records = execute_query(sql_query, (user_id,), fetch_all=True)
        
        if not all_exam_records:
            return jsonify({'success': True, 'exams': [], 'total_count': 0})

        final_exams = []
        for record in all_exam_records:
            combined_exam = {
                # ... (other fields remain the same) ...
                'unique_exam_number': record['unique_exam_number'],
                'exam_title': record['exam_title'],
                'exam_description': record['exam_description'],
                'channel_name': record['channel_name'],
                'exam_price': float(record['exam_price']),
                'amount_paid': float(record['amount_paid']),
                'payment_date': record['payment_date'].strftime('%Y-%m-%d') if record['payment_date'] else '',
                'payment_status': record['payment_status'],
                'unique_order_number': record['unique_order_number'],
                # ... (completion logic remains the same) ...
                'is_completed': False # Default
            }
            
            # ... (Marks logic remains the same) ...
            if record['marks_obtained'] is not None:
                combined_exam['is_completed'] = True
                combined_exam['marks_obtained'] = record['marks_obtained']
                combined_exam['total_marks'] = record['total_marks']
                combined_exam['percentage_score'] = round((record['marks_obtained'] / record['total_marks']) * 100, 2)
            else:
                 combined_exam['marks_obtained'] = None
                 combined_exam['percentage_score'] = None

            # [FIX] Use get_file_url instead of manual string manipulation
            if record['thumbnail_image']:
                combined_exam['thumbnail_image'] = get_file_url(record['thumbnail_image'])
            else:
                combined_exam['thumbnail_image'] = None # or a default image URL
            
            final_exams.append(combined_exam)
        
        return jsonify({
            'success': True,
            'exams': final_exams,
            'total_count': len(final_exams)
        })
        
    except Exception as e:
        secure_log(f"Get purchased exams error: {str(e)}", 'error', session.get('user_id'))
        return jsonify({'success': False, 'message': 'Could not load purchased exams'})


# ============================================================================
# EXAM TAKING ROUTES
# ============================================================================

@user_bp.route('/api/exam_start/<exam_id>')
@login_required
@require_origin_validation
@limiter.limit("10 per minute")
def get_exam_questions(exam_id):
    """
    API endpoint to initialize exam and return ALL questions.
    NEW: Client-side exam system - all questions sent at once.
    """
    exam_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(exam_id))
    if not exam_id:
        return jsonify({'success': False, 'message': 'Invalid exam ID'})
    
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'User session not found.'})

    try:
        # Verify purchase
        exam_details = execute_query("""
            SELECT le.exam_title, le.exam_description, le.video_id, le.playlist_id, le.channel_id,
            pe.amount_paid
            FROM exam.purchased_exams pe
            JOIN exam.listed_exams le ON pe.unique_exam_number = le.unique_exam_number
            WHERE pe.user_id = %s AND pe.unique_exam_number = %s
            AND pe.payment_status = 'completed' AND le.is_active = true
        """, (user_id, exam_id), fetch_one=True)
        
        if not exam_details:
            return jsonify({'success': False, 'message': 'Exam not purchased or is no longer active.'})
        
        # Get all questions
        questions_data = execute_query("""
            SELECT questions_json FROM exam.exam_questions
            WHERE unique_exam_number = %s
        """, (exam_id,), fetch_one=True)
        
        if not questions_data or not questions_data['questions_json']:
            return jsonify({'success': False, 'message': 'Questions not found for this exam.'})
        
        # Parse and shuffle questions
        questions = json.loads(questions_data['questions_json'])
        random.shuffle(questions)

        # NEW: Send FULL questions with answers to client-side JavaScript
        # Client will store in JS variables, NOT in cookies/localStorage
        # Questions will be sent with question number index for validation
        client_questions = []
        for idx, q in enumerate(questions):
            client_q = {
                'index': idx,  # Question number for answer validation
                'question': q.get('question', ''),
                'options': q.get('options', {}),
                'correct_answer': q.get('correct_answer', ''),  # Sent to client
                'explanation': q.get('explanation', '')  # Sent to client
            }
            client_questions.append(client_q)

        total_questions = len(questions)
        SECONDS_PER_QUESTION = 45
        total_exam_duration_seconds = total_questions * SECONDS_PER_QUESTION

        # Generate attempt ID for this exam session
        attempt_id = str(uuid.uuid4())
        session[f'exam_attempt_id_{exam_id}'] = attempt_id

        # NO LONGER STORING IN SERVER CACHE - Client handles everything

        secure_log(f"Exam initialized (client-side) for user {user_id}, attempt {attempt_id}", 'info', user_id=user_id)

        return jsonify({
            'success': True,
            'exam_title': exam_details.get('exam_title', 'Exam'),
            'exam_description': exam_details.get('exam_description', ''),
            'total_questions': total_questions,
            'total_exam_duration_seconds': total_exam_duration_seconds,
            'questions': client_questions,  # Full questions with answers sent to client
            'exam_details': dict(exam_details),
            'attempt_id': attempt_id
        })
    except Exception as e:
        secure_log(f"Exam initialization error: {str(e)}", 'error', user_id=user_id)
        return jsonify({'success': False, 'message': 'Could not initialize exam'})



@user_bp.route('/api/submit_exam/<exam_id>', methods=['POST'])
@login_required
@require_origin_validation
@limiter.limit("8 per minute")
def submit_exam(exam_id):
    """
    Submit exam with all answers.
    NEW: Answers come from client, validated server-side.
    """
    exam_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(exam_id))
    if not exam_id:
        return jsonify({'success': False, 'message': 'Invalid exam ID'})
    
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'User session not found.'})
    
    try:
        data = request.get_json() or {}
        attempt_id = data.get('attempt_id') or session.get(f'exam_attempt_id_{exam_id}')
        if not attempt_id:
            return jsonify({'success': False, 'message': 'Exam attempt not found or already submitted.'})

        # Get answers from client (includes calculated results)
        final_answers = data.get('answers', {})
        time_taken = data.get('time_taken', 0)
        calculated_score = data.get('calculated_score', {})  # Client sends pre-calculated score

        # NEW: Retrieve questions from DATABASE for server-side validation
        # No longer using server cache
        questions_data = execute_query("""
            SELECT questions_json FROM exam.exam_questions
            WHERE unique_exam_number = %s
        """, (exam_id,), fetch_one=True)

        if not questions_data or not questions_data['questions_json']:
            return jsonify({'success': False, 'message': 'Questions not found for validation.'})

        stored_questions = json.loads(questions_data['questions_json'])

        # Server-side validation: Recalculate score independently
        total_marks = len(stored_questions)
        marks_obtained = 0
        review_data = []

        for i, question_obj in enumerate(stored_questions):
            question_num = str(i + 1)
            correct_answer = question_obj.get('correct_answer', '').strip()
            user_answer = final_answers.get(question_num, '').strip()
            is_correct = user_answer.upper() == correct_answer.upper()

            if is_correct:
                marks_obtained += 1

            review_data.append({
                'question_number': i + 1,
                'question': question_obj.get('question', ''),
                'options': question_obj.get('options', {}),
                'user_answer': user_answer,
                'correct_answer': correct_answer,
                'is_correct': is_correct,
                'explanation': question_obj.get('explanation', '')
            })

        # Security Check: Verify client calculation matches server
        if calculated_score.get('marks_obtained') != marks_obtained:
            secure_log(f"Score mismatch detected! Client: {calculated_score.get('marks_obtained')}, Server: {marks_obtained}", 'warning', user_id)
            # Use server-calculated score (trusted)

        # NO LONGER STORING REVIEW IN CACHE - will load from database on demand
        
        # Verify purchase
        purchase = execute_query("""
            SELECT pe.*, le.exam_title
            FROM exam.purchased_exams pe
            JOIN exam.listed_exams le ON pe.unique_exam_number = le.unique_exam_number
            WHERE pe.user_id = %s AND pe.unique_exam_number = %s AND pe.payment_status = 'completed'
        """, (user_id, exam_id), fetch_one=True)
        
        if not purchase:
            return jsonify({'success': False, 'message': 'Purchase verification failed'})
        
        # Check if result already exists
        existing_result = execute_query("""
            SELECT id FROM user_base.user_result
            WHERE user_id = %s AND unique_exam_number = %s
        """, (user_id, exam_id), fetch_one=True)
        
        percentage = round((marks_obtained / total_marks) * 100, 2)

        # Save user answers to database for review
        answers_json = json.dumps(final_answers)
        execute_query("""
            INSERT INTO exam.user_exam_answers
            (user_id, exam_id, answers_json)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
            answers_json = %s,
            updated_at = NOW()
        """, (user_id, exam_id, answers_json, answers_json), commit=True)

        # Save or update result
        if existing_result:
            execute_query("""
                UPDATE user_base.user_result
                SET marks_obtained = %s, total_marks = %s, time_taken = %s,
                completed_at = NOW(), attempt_number = attempt_number + 1,
                certificate_url = NULL
                WHERE user_id = %s AND unique_exam_number = %s
            """, (marks_obtained, total_marks, time_taken, user_id, exam_id), commit=True)
        else:
            execute_query("""
                INSERT INTO user_base.user_result
                (unique_order_number, user_id, channel_id, unique_exam_number,
                payment_date, payment_time, payment_id, amount_paid,
                marks_obtained, total_marks, passing_marks, time_taken, attempt_number)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (purchase['unique_order_number'], user_id, purchase['channel_id'],
                  exam_id, purchase['payment_date'], purchase['payment_time'],
                  purchase['payment_id'], purchase['amount_paid'],
                  marks_obtained, total_marks, PASSING_PERCENTAGE, time_taken, 1), commit=True)
        
        # Clean up session (no cache to delete anymore)
        session.pop(f'exam_attempt_id_{exam_id}', None)
        session[f'review_attempt_id_{exam_id}'] = attempt_id
        
        secure_log("Exam submitted successfully", 'info', user_id)
        
        return jsonify({
            'success': True,
            'marks_obtained': marks_obtained,
            'total_marks': total_marks,
            'percentage': percentage,
            'passed': percentage >= PASSING_PERCENTAGE,
            'certificate_url': None,
            'time_taken': time_taken
        })
    except Exception as e:
        secure_log(f"Submit exam error: {str(e)}", 'error', user_id)
        return jsonify({'success': False, 'message': 'Could not submit exam'})


# ============================================================================
# EXAM RESULTS AND HISTORY ROUTES
# ============================================================================

@user_bp.route('/completed_exams/')
@limiter.limit("20 per minute")
@login_required
def completed_exams():
    secure_log("Completed exams page accessed", 'info', session['user_id'])
    return render_template('completed_exams.html')


@user_bp.route('/api/completed_exams')
@login_required
@require_origin_validation
@limiter.limit("20 per minute")
def get_completed_exams():
    """
    API endpoint to get completed exams.
    Logic matches original: returns list of exams + overall average score.
    """
    try:
        user_id = session['user_id']
        
        # 1. Main Query: Fetches the exact same columns as your original code
        #    Includes 'percentage' and 'performance_grade' calculation in SQL
        completed_exams_data = execute_query("""
            SELECT ur.unique_exam_number, ur.unique_order_number, ur.marks_obtained, ur.total_marks,
            ur.completed_at, ur.attempt_number, ur.certificate_url, ur.amount_paid,
            ur.time_taken, ur.passing_marks,
            le.exam_title, le.channel_name, le.thumbnail_image,
            ROUND((ur.marks_obtained/ur.total_marks)*100, 2) as percentage,
            CASE
            WHEN (ur.marks_obtained/ur.total_marks)*100 >= 90 THEN 'Excellent'
            WHEN (ur.marks_obtained/ur.total_marks)*100 >= 80 THEN 'Good'
            WHEN (ur.marks_obtained/ur.total_marks)*100 >= 60 THEN 'Average'
            ELSE 'Needs Improvement'
            END as performance_grade
            FROM user_base.user_result ur
            JOIN exam.listed_exams le ON ur.unique_exam_number = le.unique_exam_number
            WHERE ur.user_id = %s
            ORDER BY ur.completed_at DESC
        """, (user_id,), fetch_all=True)
        
        # 2. Average Score Query: Calculates the average across all completed exams
        stats = execute_query("""
            SELECT COALESCE(AVG((marks_obtained / NULLIF(total_marks, 0)) * 100), 0) as average_score
            FROM user_base.user_result 
            WHERE user_id = %s
        """, (user_id,), fetch_one=True)
        
        overall_average = float(stats['average_score']) if stats else 0.0
        
        # 3. Process the list (Dates and Floats) exactly as before
        exams_list = []
        if completed_exams_data:
            for exam in completed_exams_data:
                exam_dict = dict(exam)
                
                # Maintain original datetime format
                if exam_dict.get('completed_at'):
                    exam_dict['completed_at'] = exam_dict['completed_at'].strftime('%Y-%m-%d %H:%M:%S')
                
                # Maintain original float format
                if exam_dict.get('amount_paid'):
                    exam_dict['amount_paid'] = float(exam_dict['amount_paid'])
                
                exams_list.append(exam_dict)
        
        # 4. Return combined data with correct keys
        return jsonify({
            'success': True,
            'exams': exams_list,
            'average_score': round(overall_average, 2) # Restored functionality
        })

    except Exception as e:
        secure_log(f"Completed exams API error: {str(e)}", 'error', session['user_id'])
        return jsonify({'success': False, 'message': 'Could not load completed exams'})


@user_bp.route('/api/exam_analysis/<exam_id>')
@login_required
@require_origin_validation
@limiter.limit("15 per minute")
def get_exam_analysis(exam_id):
    exam_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(exam_id))
    if not exam_id:
        return jsonify({'success': False, 'message': 'Invalid exam ID'})
    
    try:
        result = execute_query("""
            SELECT ur.unique_order_number, ur.user_id, ur.channel_id, ur.unique_exam_number,
            ur.payment_date, ur.payment_time, ur.payment_id, ur.amount_paid,
            ur.marks_obtained, ur.total_marks, ur.completed_at, ur.attempt_number,
            ur.passing_marks, ur.time_taken, ur.certificate_url,
            le.exam_title, le.channel_name
            FROM user_base.user_result ur
            JOIN exam.listed_exams le ON ur.unique_exam_number = le.unique_exam_number
            WHERE ur.user_id = %s AND ur.unique_exam_number = %s
            ORDER BY ur.completed_at DESC
            LIMIT 1
        """, (session['user_id'], exam_id), fetch_one=True)
        
        if not result:
            return jsonify({'success': False, 'message': 'Result not found'})
        
        result_dict = dict(result)
        result_dict['amount_paid'] = float(result_dict['amount_paid']) if result_dict.get('amount_paid') else 0.0
        
        marks_obtained = result_dict.get('marks_obtained', 0) or 0
        total_marks = result_dict.get('total_marks', 1) or 1
        percentage = round((marks_obtained / total_marks) * 100, 2)
        result_dict['percentage'] = percentage
        
        if percentage >= 90:
            performance_grade = 'Excellent'
        elif percentage >= 80:
            performance_grade = 'Good'
        elif percentage >= 60:
            performance_grade = 'Average'
        else:
            performance_grade = 'Needs Improvement'
        
        result_dict['performance_grade'] = performance_grade
        
        if result_dict.get('completed_at'):
            result_dict['completed_at'] = result_dict['completed_at'].strftime('%Y-%m-%d %H:%M:%S')
        if result_dict.get('payment_date'):
            result_dict['payment_date'] = result_dict['payment_date'].strftime('%Y-%m-%d')
        if result_dict.get('payment_time'):
            result_dict['payment_time'] = str(result_dict['payment_time'])
        
        return jsonify({
            'success': True,
            'result': result_dict
        })
    except Exception as e:
        secure_log("Analysis API error", 'error', session['user_id'])
        return jsonify({'success': False, 'message': 'Could not load analysis'})


@user_bp.route('/api/exam_review/<exam_id>')
@login_required
@require_origin_validation
@limiter.limit("10 per minute")
def get_exam_review(exam_id):
    """Get exam review data from database."""
    exam_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(exam_id))
    if not exam_id:
        return jsonify({'success': False, 'message': 'Invalid exam ID'})

    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'User session not found.'})

    try:
        # NEW: Always load from database (no cache dependency)
        # Get user's saved answers from database
        user_answers_row = execute_query("""
            SELECT answers_json
            FROM exam.user_exam_answers
            WHERE user_id = %s AND exam_id = %s
        """, (user_id, exam_id), fetch_one=True)

        if not user_answers_row:
            return jsonify({'success': False, 'message': 'No review data found. Please complete an exam attempt.'})

        # Get exam questions from database
        exam_questions_row = execute_query("""
            SELECT questions_json
            FROM exam.exam_questions
            WHERE unique_exam_number = %s
        """, (exam_id,), fetch_one=True)

        if not exam_questions_row:
            return jsonify({'success': False, 'message': 'Exam questions not found.'})

        # Parse JSON data
        user_answers = json.loads(user_answers_row['answers_json'])
        exam_questions = json.loads(exam_questions_row['questions_json'])

        # Reconstruct review data
        exam_report = []
        for i, question_obj in enumerate(exam_questions):
            question_num = str(i + 1)
            correct_answer = question_obj.get('correct_answer', '').strip()
            user_answer = user_answers.get(question_num, '').strip()
            is_correct = user_answer.upper() == correct_answer.upper()

            exam_report.append({
                'id': i + 1,
                'question': question_obj.get('question', ''),
                'options': question_obj.get('options', {}),
                'userAnswer': user_answer,
                'correctAnswer': correct_answer,
                'isCorrect': is_correct,
                'explanation': question_obj.get('explanation', '')
            })

        return jsonify({
            'success': True,
            'examReport': exam_report
        })
    except Exception as e:
        secure_log(f"Review API error: {str(e)}", 'error', user_id=user_id)
        secure_log(f"Traceback: {traceback.format_exc()}", 'error', user_id=user_id)
        return jsonify({'success': False, 'message': 'Could not load review data'})



@user_bp.route('/re_exam/<exam_id>')
@login_required
@limiter.limit("10 per minute")
def re_exam(exam_id):
    exam_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(exam_id))
    if not exam_id:
        flash("Invalid exam ID.", "error")
        return redirect(url_for('user.exams'))
    
    user_id = session.get('user_id')
    if not user_id:
        flash("User session not found.", "error")
        return redirect(url_for('user.oauth_login'))

    try:
        purchase = execute_query("""
            SELECT pe.*, le.exam_title, le.exam_description, le.channel_name
            FROM exam.purchased_exams pe
            JOIN exam.listed_exams le ON pe.unique_exam_number = le.unique_exam_number
            WHERE pe.user_id = %s
            AND pe.unique_exam_number = %s
            AND pe.payment_status = 'completed'
            AND le.is_active = true
        """, (user_id, exam_id), fetch_one=True)
        
        if not purchase:
            flash("You need to purchase this exam first.", "error")
            return redirect(url_for('user.view_exams', exam_id=exam_id))
        
        session.pop(f'exam_attempt_id_{exam_id}', None)
        session.pop(f'review_attempt_id_{exam_id}', None)
        
        secure_log(f"Re-exam initiated for user {user_id}", 'info', user_id=user_id)
        flash("You can now retake the exam. Good luck!", "info")
        return redirect(url_for('user.exam_form', exam_id=exam_id))
    except Exception as e:
        secure_log(f"Re-exam error: {str(e)}", 'error', user_id=user_id)
        flash("Could not start re-exam.", "error")
        return redirect(url_for('user.completed_exams'))


@user_bp.route('/exam_form/<exam_id>')
@login_required
@limiter.limit("20 per minute")
def exam_form(exam_id):
    exam_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(exam_id))
    if not exam_id:
        flash("Invalid exam ID.", "error")
        return redirect(url_for('user.exams'))
    
    try:
        purchase = execute_query("""
            SELECT pe.*, le.exam_title, le.exam_description, le.channel_name
            FROM exam.purchased_exams pe
            JOIN exam.listed_exams le ON pe.unique_exam_number = le.unique_exam_number
            WHERE pe.user_id = %s
            AND pe.unique_exam_number = %s
            AND pe.payment_status = 'completed'
            AND le.is_active = true
        """, (session['user_id'], exam_id), fetch_one=True)
        
        if not purchase:
            flash("You need to purchase this exam first.", "error")
            return redirect(url_for('user.view_exams', exam_id=exam_id))
        
        existing_result = execute_query("""
            SELECT unique_exam_number, marks_obtained, total_marks
            FROM user_base.user_result
            WHERE user_id = %s AND unique_exam_number = %s
            ORDER BY completed_at DESC
            LIMIT 1
        """, (session['user_id'], exam_id), fetch_one=True)
        
        is_retake = bool(existing_result)
        
        return render_template('exam_form.html', exam_id=exam_id, exam=purchase, is_retake=is_retake)
    except Exception as e:
        secure_log("Exam form error", 'error', session['user_id'])
        flash("Could not load exam.", "error")
        return redirect(url_for('user.exams'))


@user_bp.route('/ans_analysis/<exam_id>')
@login_required
@limiter.limit("20 per minute")
def ans_analysis(exam_id):
    exam_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(exam_id))
    if not exam_id:
        flash("Invalid exam ID.", "error")
        return redirect(url_for('user.completed_exams'))
    
    secure_log("Answer analysis accessed", 'info', session['user_id'])
    return render_template('ans_analysis.html', exam_id=exam_id)


@user_bp.route('/review_paper/<exam_id>/')
@login_required
@limiter.limit("20 per minute")
def review_paper(exam_id):
    exam_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(exam_id))
    if not exam_id:
        flash("Invalid exam ID.", "error")
        return redirect(url_for('user.completed_exams'))
    
    secure_log("Review paper accessed", 'info', session['user_id'])
    return render_template('review_paper.html', exam_id=exam_id)


@user_bp.route('/generate_certificate/<exam_id>/')
@limiter.limit("10 per minute")
@login_required
def download_certificate(exam_id):
    """
    Upgraded Certificate System - Force Download
    - Fetches file content from centralized storage (GCS or Local).
    - Serves as an attachment to force browser download.
    - Regenerates automatically if file is missing.
    """
    import io # Required for serving bytes as a file

    user_id = session.get('user_id')
    if not user_id:
        flash("Not logged in.", "error")
        return redirect(url_for('user.oauth_login'))
    
    exam_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(exam_id))
    if not exam_id:
        flash("Invalid exam ID.", "error")
        return redirect(url_for('user.completed_exams'))
    
    try:
        # --- 1. Fetch Data ---
        result = execute_query("""
            SELECT 
                ur.marks_obtained, 
                ur.total_marks, 
                ur.certificate_url, 
                ur.unique_order_number,
                le.exam_title, 
                le.channel_id,
                le.video_id,
                le.playlist_id,
                COALESCE(cr.channel_name, le.channel_name) as channel_name,
                cr.signature_jpg_file AS signature_image_path,
                cr.subscriber_count,
                COALESCE(cv.duration_seconds, cp.duration_seconds) AS duration_seconds,
                u.name AS default_name, 
                u.name_in_certificate
            FROM user_base.user_result ur
            JOIN exam.listed_exams le ON ur.unique_exam_number = le.unique_exam_number
            JOIN user_base.user u ON ur.user_id = u.user_id
            JOIN creator_base.creators cr ON le.channel_id = cr.channel_id
            LEFT JOIN creator_base.videos cv ON le.video_id = cv.video_id
            LEFT JOIN creator_base.playlists cp ON le.playlist_id = cp.playlist_id
            WHERE ur.user_id = %s AND ur.unique_exam_number = %s
        """, (user_id, exam_id), fetch_one=True)
        
        if not result:
            flash("Result not found for this exam.", "error")
            return redirect(url_for('user.completed_exams'))
        
        # --- 2. Check Passing Percentage ---
        marks_obtained = result['marks_obtained']
        total_marks = result['total_marks']
        percentage = (marks_obtained / total_marks) * 100 if total_marks else 0
        
        if percentage < PASSING_PERCENTAGE:
            flash(f"You must score at least {PASSING_PERCENTAGE}% to download the certificate.", "error")
            return redirect(url_for('user.completed_exams'))
        
        # Prepare clean filename for download
        raw_title = result.get('exam_title', 'Certificate')
        safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', raw_title)[:50] # Limit length
        download_filename = f"{safe_title}_Certificate.pdf"

        # --- 3. Try to Retrieve Existing Certificate Content ---
        db_cert_path = result.get('certificate_url')
        file_content = None
        regenerate = False

        if db_cert_path:
            # [FIX] Sanitize path: Remove /static/ or GCS domain to get raw storage path
            # The DB stores the PUBLIC URL, but download_file_content needs the STORAGE PATH.
            storage_path = db_cert_path
            
            # Handle Local Path (strip /static/)
            if storage_path.startswith('/static/'):
                storage_path = storage_path[8:]
            elif storage_path.startswith('static/'):
                storage_path = storage_path[7:]
            
            # Handle GCS URL (strip domain and bucket)
            # Format: https://storage.googleapis.com/BUCKET_NAME/path/to/file
            elif 'storage.googleapis.com' in storage_path:
                 try:
                     storage_path = '/'.join(storage_path.split('/')[4:])
                 except:
                     pass

            # Attempt to download bytes from centralized storage
            file_content = download_file_content(storage_path)
            
            if not file_content:
                # If path exists in DB but file is missing in storage, trigger regeneration
                secure_log(f"Certificate missing in storage: {db_cert_path}. Regenerating...", 'warning', user_id)
                regenerate = True
        else:
            regenerate = True

        # --- 4. Serve Existing File if Found ---
        if file_content and not regenerate:
            secure_log(f"Serving certificate download: {db_cert_path}", 'info', user_id)
            return send_file(
                io.BytesIO(file_content),
                mimetype='application/pdf',
                as_attachment=True,
                download_name=download_filename
            )

        # --- 5. Regeneration Logic (If file missing or not created) ---
        secure_log(f"Generating certificate for user {user_id}, exam {exam_id}", 'info', user_id)
        
        student_name = result.get('name_in_certificate') or result.get('default_name')
        channel_name = result.get('channel_name') or "Unknown Channel"
        
        # Duration Formatting
        duration_str = "the"
        if result.get('duration_seconds'):
            seconds = int(result['duration_seconds'])
            hours = seconds / 3600
            minutes = seconds / 60
            if hours >= 1:
                duration_str = f"{round(hours, 1)} hour"
            elif minutes >= 1:
                duration_str = f"{round(minutes)} min"
            elif seconds > 0:
                duration_str = f"{seconds} sec"
        
        score_str = f"{round(percentage)}%"

        # Clean Title
        exam_title = result.get('exam_title', 'Completed Course')
        exam_title = re.sub(r'#\w+', '', exam_title)
        exam_title = re.sub(r'\s*\([^)]*\d+[^)]*\)\s*$', '', exam_title).strip()
        exam_title = re.sub(r'\s+', ' ', exam_title).strip()
        
        # --- SIGNATURE: Download to Temp ---
        sig_path = result.get('signature_image_path')
        temp_signature_path = ""
        
        if sig_path:
            # We must also clean the signature path just in case
            clean_sig = sig_path
            if clean_sig.startswith('/static/'): clean_sig = clean_sig[8:]
            elif clean_sig.startswith('static/'): clean_sig = clean_sig[7:]
            
            sig_content = download_file_content(clean_sig)
            if sig_content:
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_sig:
                    temp_sig.write(sig_content)
                    temp_signature_path = temp_sig.name
        
        # Prepare Paths and Data
        qr_code_data = f"{user_id}__CERT__{exam_id}"
        
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_pdf:
            temp_pdf_path = temp_pdf.name

        cert_data = {
            'name': student_name,
            'youtube_title': exam_title,
            'course_length': duration_str,
            'score': score_str,
            'channel_name': channel_name,
            'signature_image_path': temp_signature_path,
            'qr_code': qr_code_data,
            'subscriber_count': result.get('subscriber_count', 0)
        }

        # Generate PDF (uses Config.BASE_URL automatically for QR code)
        generated_pdf_path = generate_certificate(
            template_path=os.path.abspath(CERTIFICATE_TEMPLATE_PATH),
            output_path=temp_pdf_path,
            data=cert_data
        )
        
        # Cleanup temp signature
        if temp_signature_path and os.path.exists(temp_signature_path):
            os.remove(temp_signature_path)
        
        if not generated_pdf_path:
            flash("Certificate generation failed.", "error")
            return redirect(url_for('user.completed_exams'))
        
        try:
            # Read the generated content for immediate serving
            with open(generated_pdf_path, 'rb') as f:
                new_file_content = f.read()

            # Save to Centralized Storage (for future access)
            # We use a consistent filename so we don't spam storage if called multiple times
            unique_filename = f"cert_{user_id}_{exam_id}.pdf" 
            storage_path = save_file(io.BytesIO(new_file_content), 'certificates', unique_filename)
            
            # Get the access URL (for DB record)
            public_url = get_file_url(storage_path)
            
            secure_log(f"New certificate saved to: {storage_path}", 'info', user_id)
            
            # Update Database
            execute_query("""
                UPDATE user_base.user_result
                SET certificate_url = %s
                WHERE user_id = %s AND unique_exam_number = %s
            """, (public_url, user_id, exam_id), commit=True)
            
            # Cleanup temp PDF
            if os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)
            
            # Serve the Download
            return send_file(
                io.BytesIO(new_file_content),
                mimetype='application/pdf',
                as_attachment=True,
                download_name=download_filename
            )
            
        except Exception as e:
            secure_log(f"Certificate storage/serve failed: {str(e)}", 'error', user_id)
            flash("Could not generate certificate download.", "error")
            return redirect(url_for('user.completed_exams'))

    except Exception as e:
        secure_log(f"Certificate download error: {str(e)}", 'error', user_id)
        flash(f"An error occurred: {str(e)}", "error")
        return redirect(url_for('user.completed_exams'))



@user_bp.route('/verify_certificate/<path:verification_id>')
@limiter.limit("10 per minute")
def verify_certificate(verification_id):
    """
    Public Verification Route
    Supports both formats: USR_xxx__CERT__exam_id and USR_xxx_CERT_exam_id
    Also fixed to show the correct Channel Name from creators table.
    """
    try:
        # Try double underscore format first (new format)
        if '__CERT__' in verification_id:
            parts = verification_id.split('__CERT__')
        # Fallback to single underscore format (legacy/malformed)
        elif '_CERT_' in verification_id:
            parts = verification_id.split('_CERT_')
        else:
            raise ValueError("Invalid verification ID format - missing CERT separator.")

        if len(parts) != 2:
            raise ValueError("Invalid verification ID format - incorrect number of parts.")

        user_id = parts[0]
        unique_exam_number = parts[1]

        # Basic validation: ensure user_id looks like USR_... and exam id is non-empty
        if not user_id.startswith('USR_') or not unique_exam_number:
             raise ValueError("Invalid ID components - user_id or exam_id missing.")

    except Exception as e:
        secure_log(f"Certificate verification failed: {e} (ID: {verification_id})", 'warning')
        return render_template('verify_certificate.html', error="Invalid or malformed verification link."), 400

    try:
        # UPGRADED QUERY: Fetches live channel name and handles both video/playlist duration
        result = execute_query("""
            SELECT 
                u.name_in_certificate, u.name,
                le.exam_title,
                le.video_id,
                le.playlist_id,
                -- FIX: Get live channel name from creators table
                COALESCE(cr.channel_name, le.channel_name) as channel_name,
                cr.subscriber_count,
                ur.marks_obtained, ur.total_marks, ur.completed_at,
                COALESCE(cv.duration_seconds, cp.duration_seconds) AS duration_seconds
            FROM user_base.user_result ur
            JOIN user_base.user u ON ur.user_id = u.user_id
            JOIN exam.listed_exams le ON ur.unique_exam_number = le.unique_exam_number
            LEFT JOIN creator_base.creators cr ON le.channel_id = cr.channel_id
            LEFT JOIN creator_base.videos cv ON le.video_id = cv.video_id
            LEFT JOIN creator_base.playlists cp ON le.playlist_id = cp.playlist_id
            WHERE ur.user_id = %s AND ur.unique_exam_number = %s
        """, (user_id, unique_exam_number), fetch_one=True)
        
        if not result:
            return render_template('verify_certificate.html', error="No valid certificate found for this ID."), 404
            
        percentage = (result['marks_obtained'] / result['total_marks']) * 100 if result['total_marks'] else 0
        
        # Duration Logic
        duration_str = "N/A"
        if result.get('duration_seconds'):
            seconds = int(result['duration_seconds'])
            hours = seconds / 3600
            if hours >= 1: duration_str = f"{round(hours, 1)} hours"
            elif seconds/60 >= 1: duration_str = f"{round(seconds/60)} min"
            else: duration_str = f"{seconds} sec"
                
        # Subscriber Logic
        subs_str = "N/A"
        if result.get('subscriber_count'):
            subs = result['subscriber_count']
            if subs > 1_000_000: subs_str = f"{round(subs / 1_000_000, 1)}M"
            elif subs > 1_000: subs_str = f"{round(subs / 1_000, 1)}K"
            else: subs_str = f"{subs}"
        
        cert_data = {
            'student_name': result.get('name_in_certificate') or result.get('name'),
            'exam_title': result.get('exam_title'),
            'channel_name': result.get('channel_name') or "Unknown Channel", # Fallback
            'subscriber_count': subs_str,
            'score': f"{round(percentage)}%",
            'course_length': duration_str,
            'completed_at': result.get('completed_at').strftime('%Y-%m-%d')
        }
        
        return render_template('verify_certificate.html', data=cert_data)

    except Exception as e:
        secure_log(f"Certificate verification error: {str(e)}", 'error')
        return render_template('verify_certificate.html', error="An internal error occurred."), 500


# ============================================================================
# PROMOTIONAL EXAMS API
# ============================================================================

@user_bp.route('/api/promotional_exams', methods=['GET'])
@limiter.limit("60 per minute")
def get_promotional_exams():
    """
    API: Get 10 promotional exams for homepage carousel
    Returns: 5 admin-selected featured exams + 5 random popular exams
    Response is cached and updates every hour
    """
    try:
        # Get 5 admin-featured exams
        featured_query = """
            SELECT
                e.id,
                e.unique_exam_number AS exam_number,
                e.exam_title AS title,
                e.exam_price AS price,
                e.thumbnail_image AS thumbnail_url,
                cb.creator_name as creator_name,
                cb.channel_name,
                COALESCE(
                    (SELECT COUNT(*)
                     FROM exam.purchased_exams pe
                     WHERE pe.unique_exam_number = e.unique_exam_number
                       AND pe.payment_status = 'completed'),
                    0
                ) as purchase_count
            FROM admin_base.admin_featured_exams afe
            JOIN exam.listed_exams e ON afe.exam_id = e.id
            JOIN creator_base.creators cb ON e.channel_id = cb.channel_id
            WHERE afe.is_active = TRUE AND e.is_active = TRUE
            ORDER BY afe.display_order ASC
            LIMIT 5
        """
        featured_exams = execute_query(featured_query, fetch_all=True) or []

        # Get IDs of featured exams to exclude from random selection
        featured_ids = [exam['id'] for exam in featured_exams]
        exclude_clause = ""
        exclude_params = []

        if featured_ids:
            placeholders = ','.join(['%s'] * len(featured_ids))
            exclude_clause = f"AND e.id NOT IN ({placeholders})"
            exclude_params = featured_ids

        # Get 5 random popular exams (excluding already featured ones)
        random_query = f"""
            SELECT
                e.id,
                e.unique_exam_number AS exam_number,
                e.exam_title AS title,
                e.exam_price AS price,
                e.thumbnail_image AS thumbnail_url,
                cb.creator_name as creator_name,
                cb.channel_name,
                COALESCE(
                    (SELECT COUNT(*)
                     FROM exam.purchased_exams pe
                     WHERE pe.unique_exam_number = e.unique_exam_number
                       AND pe.payment_status = 'completed'),
                    0
                ) as purchase_count
            FROM exam.listed_exams e
            JOIN creator_base.creators cb ON e.channel_id = cb.channel_id
            WHERE e.is_active = TRUE {exclude_clause}
            ORDER BY RAND()
            LIMIT 5
        """
        random_exams = execute_query(random_query, exclude_params, fetch_all=True) or []

        # Combine both lists
        promotional_exams = featured_exams + random_exams

        # Add source tag, convert thumbnail URLs, and format response
        for i, exam in enumerate(promotional_exams):
            exam['source'] = 'featured' if i < len(featured_exams) else 'random'
            exam['display_order'] = i + 1

            # Convert thumbnail path to proper URL
            if exam.get('thumbnail_url'):
                exam['thumbnail_url'] = get_file_url(exam['thumbnail_url'])

        return jsonify({
            'success': True,
            'count': len(promotional_exams),
            'exams': promotional_exams
        })

    except Exception as e:
        secure_log(f"Error fetching promotional exams: {str(e)}", 'error')
        return jsonify({
            'success': False,
            'message': 'Error loading promotional exams',
            'exams': []
        }), 500


@user_bp.route('/api/exam_list', methods=['GET'])
@limiter.limit("60 per minute")
@login_required
def get_exam_list():
    """
    API: Get paginated list of all exams (YouTube-style with randomization)
    Query params:
        - page: Page number (default 1)
        - limit: Items per page (default 25)
        - seed: Random seed from client (for consistent pagination)
    Returns: List of exams with pagination info (excludes featured exams to avoid duplicates)
    """
    try:
        user_id = session.get('user_id')
        page = request.args.get('page', 1, type=int)
        limit = min(request.args.get('limit', 25, type=int), 50)  # Max 50 per page
        offset = (page - 1) * limit

        # Get random seed from client (stored in sessionStorage)
        # Client generates new seed on page refresh, sends same seed for pagination
        random_seed = request.args.get('seed', type=int)
        if not random_seed or random_seed <= 0:
            random_seed = random.randint(1, 999999)

        # Get featured exam IDs to exclude from main list (to avoid duplicates with carousel)
        featured_query = """
            SELECT exam_id FROM admin_base.admin_featured_exams WHERE is_active = TRUE
        """
        featured_result = execute_query(featured_query, fetch_all=True) or []
        featured_ids = [f['exam_id'] for f in featured_result]

        # Build exclude clause for featured exams
        exclude_clause = ""
        exclude_params = []
        if featured_ids:
            placeholders = ','.join(['%s'] * len(featured_ids))
            exclude_clause = f"AND e.id NOT IN ({placeholders})"
            exclude_params = featured_ids

        # Get total count (excluding featured exams)
        count_query = f"""
            SELECT COUNT(*) as total
            FROM exam.listed_exams e
            WHERE e.is_active = TRUE {exclude_clause}
        """
        count_result = execute_query(count_query, exclude_params, fetch_one=True)
        total_exams = count_result['total'] if count_result else 0

        # Get paginated exams with randomized order (using seed for consistency)
        # Excludes featured exams to avoid duplicates with carousel
        exams_query = f"""
            SELECT
                e.id,
                e.unique_exam_number AS exam_number,
                e.exam_title AS title,
                e.exam_price AS price,
                e.thumbnail_image AS thumbnail_url,
                e.channel_id,
                cb.creator_name,
                cb.channel_name,
                e.created_at,
                COALESCE(
                    (SELECT COUNT(*)
                     FROM exam.purchased_exams pe
                     WHERE pe.unique_exam_number = e.unique_exam_number
                       AND pe.payment_status = 'completed'),
                    0
                ) as purchase_count,
                -- Check if user already purchased
                COALESCE(
                    (SELECT 1
                     FROM exam.purchased_exams pe
                     WHERE pe.user_id = %s
                       AND pe.unique_exam_number = e.unique_exam_number
                       AND pe.payment_status = 'completed'
                     LIMIT 1),
                    0
                ) as is_purchased
            FROM exam.listed_exams e
            JOIN creator_base.creators cb ON e.channel_id = cb.channel_id
            WHERE e.is_active = TRUE {exclude_clause}
            ORDER BY RAND(%s)
            LIMIT %s OFFSET %s
        """
        query_params = [user_id] + exclude_params + [random_seed, limit, offset]
        exams = execute_query(exams_query, query_params, fetch_all=True) or []

        # Convert thumbnail URLs
        for exam in exams:
            if exam.get('thumbnail_url'):
                exam['thumbnail_url'] = get_file_url(exam['thumbnail_url'])

            # Format created_at as relative time
            if exam.get('created_at'):
                exam['created_at'] = exam['created_at'].isoformat() if hasattr(exam['created_at'], 'isoformat') else str(exam['created_at'])

        # Calculate pagination info
        total_pages = (total_exams + limit - 1) // limit  # Ceiling division
        has_more = page < total_pages

        return jsonify({
            'success': True,
            'exams': exams,
            'pagination': {
                'current_page': page,
                'total_pages': total_pages,
                'total_exams': total_exams,
                'per_page': limit,
                'has_more': has_more
            }
        })

    except Exception as e:
        secure_log(f"Error fetching exam list: {str(e)}", 'error')
        return jsonify({
            'success': False,
            'message': 'Error loading exam list',
            'exams': [],
            'pagination': {
                'current_page': 1,
                'total_pages': 0,
                'total_exams': 0,
                'per_page': limit,
                'has_more': False
            }
        }), 500


# ============================================================================
# CHANNEL BROWSING ROUTES (YouTube-style)
# ============================================================================

@user_bp.route('/channels/')
@limiter.limit("30 per minute")
@login_required
def channels():
    """Browse all creator channels"""
    secure_log("Channels browse page accessed", 'info', session['user_id'])
    return render_template('channels.html')


@user_bp.route('/channel/<channel_id>/')
@limiter.limit("30 per minute")
@login_required
def channel_page(channel_id):
    """View a single creator's channel page (YouTube-style)"""
    # Sanitize channel_id
    channel_id = re.sub(r'[^a-zA-Z0-9_\-]', '', str(channel_id))
    if not channel_id:
        flash("Invalid channel ID.", "error")
        return redirect(url_for('user.index'))

    try:
        creator = execute_query("""
            SELECT
                c.channel_id, c.creator_name, c.channel_name,
                c.subscriber_count, c.youtube_channel_link,
                c.profile_photo_jpg, c.created_at, c.is_active,
                COUNT(DISTINCT le.unique_exam_number) as total_exams
            FROM creator_base.creators c
            LEFT JOIN exam.listed_exams le
                ON c.channel_id = le.channel_id AND le.is_active = TRUE
            WHERE c.channel_id = %s AND c.is_active = TRUE
            GROUP BY c.channel_id
        """, (channel_id,), fetch_one=True)

        if not creator:
            flash("Channel not found or is no longer active.", "error")
            return redirect(url_for('user.index'))

        creator = dict(creator)

        # Process profile photo URL
        if creator.get('profile_photo_jpg') and not str(creator['profile_photo_jpg']).startswith('http'):
            creator['profile_photo_jpg'] = get_file_url(creator['profile_photo_jpg']) or ''

        # Format subscriber count
        subs = creator.get('subscriber_count', 0) or 0
        if subs >= 1_000_000:
            creator['formatted_subscribers'] = f"{subs / 1_000_000:.1f}M"
        elif subs >= 1_000:
            creator['formatted_subscribers'] = f"{subs / 1_000:.1f}K"
        else:
            creator['formatted_subscribers'] = str(subs)

        secure_log(f"Channel page accessed: {channel_id}", 'info', session['user_id'])
        return render_template('channel_page.html', creator=creator)

    except Exception as e:
        secure_log(f"Channel page error: {str(e)}", 'error', session['user_id'])
        flash("Could not load channel. Please try again.", "error")
        return redirect(url_for('user.index'))


@user_bp.route('/api/channels')
@login_required
@require_origin_validation
@limiter.limit("30 per minute")
def get_channels():
    """
    Paginated API to browse all active creator channels.
    Returns creators who have at least one active exam.
    Query params: page, per_page, sort (subscribers|newest|exams)
    """
    try:
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(int(request.args.get('per_page', 12)), 48)
        sort = request.args.get('sort', 'subscribers')
        offset = (page - 1) * per_page

        sort_map = {
            'subscribers': 'c.subscriber_count DESC',
            'newest': 'c.created_at DESC',
            'exams': 'total_exams DESC',
            'name': 'c.channel_name ASC'
        }
        order_clause = sort_map.get(sort, 'c.subscriber_count DESC')

        total_data = execute_query("""
            SELECT COUNT(DISTINCT c.channel_id) as total
            FROM creator_base.creators c
            INNER JOIN exam.listed_exams le ON c.channel_id = le.channel_id AND le.is_active = TRUE
            WHERE c.is_active = TRUE
        """, fetch_one=True)
        total_count = total_data['total'] if total_data else 0

        channels_raw = execute_query(f"""
            SELECT
                c.channel_id, c.creator_name, c.channel_name,
                c.subscriber_count, c.youtube_channel_link,
                c.profile_photo_jpg, c.created_at,
                COUNT(DISTINCT le.unique_exam_number) as total_exams,
                COUNT(DISTINCT pe.user_id) as total_students
            FROM creator_base.creators c
            INNER JOIN exam.listed_exams le ON c.channel_id = le.channel_id AND le.is_active = TRUE
            LEFT JOIN exam.purchased_exams pe
                ON le.unique_exam_number = pe.unique_exam_number AND pe.payment_status = 'completed'
            WHERE c.is_active = TRUE
            GROUP BY c.channel_id
            ORDER BY {order_clause}
            LIMIT %s OFFSET %s
        """, (per_page, offset), fetch_all=True)

        channel_list = []
        for ch in channels_raw or []:
            d = dict(ch)
            # Process profile photo
            if d.get('profile_photo_jpg') and not str(d['profile_photo_jpg']).startswith('http'):
                d['profile_photo_jpg'] = get_file_url(d['profile_photo_jpg']) or ''
            # Format subscribers
            subs = d.get('subscriber_count', 0) or 0
            if subs >= 1_000_000:
                d['formatted_subscribers'] = f"{subs / 1_000_000:.1f}M"
            elif subs >= 1_000:
                d['formatted_subscribers'] = f"{subs / 1_000:.1f}K"
            else:
                d['formatted_subscribers'] = str(subs)
            # Serialize datetime
            if d.get('created_at') and hasattr(d['created_at'], 'isoformat'):
                d['created_at'] = d['created_at'].isoformat()
            channel_list.append(d)

        return jsonify({
            'success': True,
            'channels': channel_list,
            'pagination': {
                'current_page': page,
                'per_page': per_page,
                'total_count': total_count,
                'total_pages': (total_count + per_page - 1) // per_page
            }
        })

    except Exception as e:
        secure_log(f"Channels API error: {str(e)}", 'error', session.get('user_id'))
        return jsonify({'success': False, 'message': 'Could not load channels'}), 500


@user_bp.route('/api/channel/<channel_id>')
@login_required
@require_origin_validation
@limiter.limit("30 per minute")
def get_channel_detail(channel_id):
    """
    Full channel detail API — creator profile + paginated exams.
    Query params: page, per_page, sort (newest|price_asc|price_desc|alpha)
    """
    channel_id = re.sub(r'[^a-zA-Z0-9_\-]', '', str(channel_id))
    if not channel_id:
        return jsonify({'success': False, 'message': 'Invalid channel ID'}), 400

    try:
        user_id = session['user_id']
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(int(request.args.get('per_page', 12)), 48)
        sort = request.args.get('sort', 'newest')
        offset = (page - 1) * per_page

        sort_map = {
            'newest': 'le.created_at DESC',
            'price_asc': 'le.exam_price ASC',
            'price_desc': 'le.exam_price DESC',
            'alpha': 'le.exam_title ASC'
        }
        order_clause = sort_map.get(sort, 'le.created_at DESC')

        # Fetch creator info + aggregate stats
        creator = execute_query("""
            SELECT
                c.channel_id, c.creator_name, c.channel_name,
                c.subscriber_count, c.youtube_channel_link,
                c.profile_photo_jpg, c.created_at, c.is_active,
                COUNT(DISTINCT le.unique_exam_number) as total_exams,
                COUNT(DISTINCT pe.id) as total_purchases,
                COALESCE(AVG(le.exam_price), 0) as avg_price
            FROM creator_base.creators c
            LEFT JOIN exam.listed_exams le
                ON c.channel_id = le.channel_id AND le.is_active = TRUE
            LEFT JOIN exam.purchased_exams pe
                ON le.unique_exam_number = pe.unique_exam_number AND pe.payment_status = 'completed'
            WHERE c.channel_id = %s AND c.is_active = TRUE
            GROUP BY c.channel_id
        """, (channel_id,), fetch_one=True)

        if not creator:
            return jsonify({'success': False, 'message': 'Channel not found'}), 404

        creator = dict(creator)

        # Process profile photo
        if creator.get('profile_photo_jpg') and not str(creator['profile_photo_jpg']).startswith('http'):
            creator['profile_photo_jpg'] = get_file_url(creator['profile_photo_jpg']) or ''

        # Format subscribers
        subs = creator.get('subscriber_count', 0) or 0
        if subs >= 1_000_000:
            creator['formatted_subscribers'] = f"{subs / 1_000_000:.1f}M"
        elif subs >= 1_000:
            creator['formatted_subscribers'] = f"{subs / 1_000:.1f}K"
        else:
            creator['formatted_subscribers'] = str(subs)

        if creator.get('created_at') and hasattr(creator['created_at'], 'isoformat'):
            creator['created_at'] = creator['created_at'].isoformat()

        creator['avg_price'] = float(creator.get('avg_price', 0) or 0)

        # Fetch total exam count for pagination
        total_data = execute_query("""
            SELECT COUNT(*) as total FROM exam.listed_exams
            WHERE channel_id = %s AND is_active = TRUE
        """, (channel_id,), fetch_one=True)
        total_exams = total_data['total'] if total_data else 0

        # Fetch paginated exams with purchase/completion status
        exams_raw = execute_query(f"""
            SELECT
                le.unique_exam_number, le.exam_title, le.exam_description,
                le.exam_price, le.thumbnail_image, le.created_at,
                le.video_id, le.playlist_id,
                (SELECT JSON_LENGTH(eq.questions_json)
                 FROM exam.exam_questions eq
                 WHERE eq.unique_exam_number = le.unique_exam_number) as question_count,
                COALESCE((SELECT 1 FROM exam.purchased_exams pe
                          WHERE pe.unique_exam_number = le.unique_exam_number
                            AND pe.user_id = %s AND pe.payment_status = 'completed'
                          LIMIT 1), 0) as is_purchased,
                COALESCE((SELECT 1 FROM user_base.user_result ur
                          WHERE ur.unique_exam_number = le.unique_exam_number
                            AND ur.user_id = %s
                          LIMIT 1), 0) as is_completed
            FROM exam.listed_exams le
            WHERE le.channel_id = %s AND le.is_active = TRUE
            ORDER BY {order_clause}
            LIMIT %s OFFSET %s
        """, (user_id, user_id, channel_id, per_page, offset), fetch_all=True)

        exam_list = []
        for exam in exams_raw or []:
            d = dict(exam)
            if d.get('thumbnail_image') and not str(d['thumbnail_image']).startswith('http'):
                d['thumbnail_image'] = get_file_url(d['thumbnail_image']) or ''
            d['is_purchased'] = bool(d.get('is_purchased', 0))
            d['is_completed'] = bool(d.get('is_completed', 0))
            d['exam_price'] = float(d.get('exam_price', 0) or 0)
            d['question_count'] = d.get('question_count') or 0
            if d.get('created_at') and hasattr(d['created_at'], 'isoformat'):
                d['created_at'] = d['created_at'].isoformat()
            exam_list.append(d)

        secure_log(f"Channel detail API: {channel_id}", 'info', user_id)
        return jsonify({
            'success': True,
            'creator': creator,
            'exams': exam_list,
            'pagination': {
                'current_page': page,
                'per_page': per_page,
                'total_exams': total_exams,
                'total_pages': (total_exams + per_page - 1) // per_page if total_exams else 0
            }
        })

    except Exception as e:
        secure_log(f"Channel detail API error: {str(e)}", 'error', session.get('user_id'))
        return jsonify({'success': False, 'message': 'Could not load channel details'}), 500


@user_bp.route('/api/search')
@login_required
@require_origin_validation
@limiter.limit("30 per minute")
def search():
    """
    Unified search API — returns both matching exams AND matching channels.
    Supersedes /api/search_exams (which remains for backward compatibility).
    Query params: q (min 2 chars)
    Returns: { exams: [...], channels: [...] }
    """
    query = request.args.get('q', '').strip()

    if not query or len(query) < 2:
        return jsonify({'success': False, 'message': 'Search query must be at least 2 characters'})

    query = re.sub(r'[^a-zA-Z0-9\s\-_]', '', query)
    if not query:
        return jsonify({'success': False, 'message': 'Invalid search query'})

    try:
        user_id = session.get('user_id')
        search_pattern = f"%{query}%"

        # --- Search Exams ---
        exams_raw = execute_query("""
            SELECT le.unique_exam_number, le.exam_title, le.exam_description,
                   le.channel_name, le.channel_id, le.exam_price, le.thumbnail_image,
                   COALESCE((SELECT 1 FROM exam.purchased_exams pe
                             WHERE pe.unique_exam_number = le.unique_exam_number
                               AND pe.user_id = %s AND pe.payment_status = 'completed'
                             LIMIT 1), 0) as is_purchased,
                   COALESCE((SELECT 1 FROM user_base.user_result ur
                             WHERE ur.unique_exam_number = le.unique_exam_number
                               AND ur.user_id = %s
                             LIMIT 1), 0) as is_completed
            FROM exam.listed_exams le
            WHERE (le.exam_title LIKE %s OR le.exam_description LIKE %s OR le.channel_name LIKE %s)
              AND le.is_active = TRUE
            ORDER BY le.exam_title
            LIMIT 8
        """, (user_id, user_id, search_pattern, search_pattern, search_pattern), fetch_all=True)

        exam_list = []
        for exam in exams_raw or []:
            d = dict(exam)
            if d.get('thumbnail_image') and not str(d['thumbnail_image']).startswith('http'):
                d['thumbnail_image'] = get_file_url(d['thumbnail_image']) or ''
            d['is_purchased'] = bool(d.get('is_purchased', 0))
            d['is_completed'] = bool(d.get('is_completed', 0))
            d['exam_price'] = float(d.get('exam_price', 0) or 0)
            exam_list.append(d)

        # --- Search Channels ---
        channels_raw = execute_query("""
            SELECT
                c.channel_id, c.creator_name, c.channel_name,
                c.subscriber_count, c.profile_photo_jpg,
                COUNT(DISTINCT le.unique_exam_number) as total_exams
            FROM creator_base.creators c
            LEFT JOIN exam.listed_exams le ON c.channel_id = le.channel_id AND le.is_active = TRUE
            WHERE (c.channel_name LIKE %s OR c.creator_name LIKE %s)
              AND c.is_active = TRUE
            GROUP BY c.channel_id
            ORDER BY c.subscriber_count DESC
            LIMIT 5
        """, (search_pattern, search_pattern), fetch_all=True)

        channel_list = []
        for ch in channels_raw or []:
            d = dict(ch)
            if d.get('profile_photo_jpg') and not str(d['profile_photo_jpg']).startswith('http'):
                d['profile_photo_jpg'] = get_file_url(d['profile_photo_jpg']) or ''
            subs = d.get('subscriber_count', 0) or 0
            if subs >= 1_000_000:
                d['formatted_subscribers'] = f"{subs / 1_000_000:.1f}M subscribers"
            elif subs >= 1_000:
                d['formatted_subscribers'] = f"{subs / 1_000:.1f}K subscribers"
            else:
                d['formatted_subscribers'] = f"{subs} subscribers" if subs else ''
            channel_list.append(d)

        secure_log(f"Unified search '{query}': {len(exam_list)} exams, {len(channel_list)} channels", 'info', user_id)
        return jsonify({
            'success': True,
            'exams': exam_list,
            'channels': channel_list
        })

    except Exception as e:
        secure_log(f"Unified search API error: {str(e)}", 'error', session.get('user_id'))
        return jsonify({'success': False, 'message': 'Search failed'}), 500


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@user_bp.errorhandler(404)
def not_found_error(error):
    secure_log("404 error occurred", 'warning', session.get('user_id'))
    return render_template('error_404.html'), 404


@user_bp.errorhandler(500)
def internal_error(error):
    secure_log("500 error occurred", 'error', session.get('user_id'))
    return render_template('error_500.html'), 500


@user_bp.errorhandler(403)
def forbidden_error(error):
    secure_log("403 error occurred", 'warning', session.get('user_id'))
    return render_template('error_403.html'), 403


@user_bp.errorhandler(429)
def ratelimit_handler(e):
    secure_log("Rate limit exceeded", 'warning', session.get('user_id'))
    return jsonify({'success': False, 'message': 'Rate limit exceeded. Please try again later.'}), 429



