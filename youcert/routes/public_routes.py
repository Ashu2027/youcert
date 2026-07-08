"""
PUBLIC ROUTES - UPGRADED VERSION

UPGRADES:
- Centralized logging via secure_log() from youcert
- Centralized database operations (execute_query, execute_many)
- User-isolated caching (IP-based for public routes)
- Rate limiting optimized for 12K req/sec
- All existing functionality preserved
- All routes unchanged
- All error handling preserved

Public routes for landing pages, contact-us, join-as-creator.
NO authentication required.
"""

from flask import Blueprint, render_template, request, jsonify, send_from_directory
import uuid
from datetime import datetime
from youcert import limiter, csrf, secure_log, execute_query, get_user_cache, set_user_cache

# ============================================================================
# CONFIGURATION
# ============================================================================

public_bp = Blueprint('public', __name__)

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================


def get_visitor_identifier():
    """Get unique identifier for rate limiting (IP address for all visitors)"""
    # PROXY FIX: Trust X-Forwarded-For first (real client IP behind load balancer)
    forwarded_for = request.headers.getlist("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs, take the first (original client)
        return forwarded_for[0].split(',')[0].strip()
    # Fallback to remote_addr (only used in local dev)
    return request.remote_addr or '0.0.0.0'


def get_remaining_quota(visitor_ip):
    """
    Check remaining contact queries quota for the day with IP-based caching
    Returns: (can_submit: bool, remaining: int, message: str)
    """
    try:
        # Check cache first (1 minute TTL) - IP-based caching
        cache_key = f"quota_check:{visitor_ip}"
        cached_quota = get_user_cache(cache_key, user_id=visitor_ip)
        if cached_quota:
            return cached_quota
        
        # Check quota for this IP
        quota_record = execute_query(
            """SELECT * FROM query_base.contact_daily_quota 
               WHERE visitor_ip = %s AND quota_date = CURDATE()""",
            (visitor_ip,),
            fetch_one=True
        )
        
        if not quota_record:
            # Create new quota record for today
            execute_query(
                """INSERT INTO query_base.contact_daily_quota 
                   (visitor_ip, quota_date, queries_today, max_queries_per_day)
                   VALUES (%s, CURDATE(), 0, 10)""",
                (visitor_ip,),
                commit=True
            )
            result = (True, 10, "Daily quota available")
            set_user_cache(cache_key, result, user_id=visitor_ip, timeout=60)
            return result
        
        queries_today = quota_record['queries_today']
        max_queries = quota_record['max_queries_per_day']
        remaining = max(0, max_queries - queries_today)
        
        can_submit = remaining > 0
        message = f"{remaining} queries remaining today"
        
        result = (can_submit, remaining, message)
        # Cache for 1 minute (IP-isolated)
        set_user_cache(cache_key, result, user_id=visitor_ip, timeout=60)
        
        return result
        
    except Exception as e:
        secure_log(f"Error checking quota: {str(e)}", 'error')
        # Default: allow submission on error (fail open)
        return (True, 10, "Quota check unavailable")


# ============================================================================
# UPGRADED UTILITY FUNCTIONS (DB Index Optimized)
# ============================================================================

def generate_query_id():
    """
    Generate unique query ID.
    OPTIMIZATION: Timestamp first ensures sequential DB inserts (better performance).
    Format: QUERY_<TIMESTAMP>_<RANDOM_HEX>
    """
    timestamp = int(datetime.now().timestamp())
    random_part = uuid.uuid4().hex[:8].upper()
    return f"QUERY_{timestamp}_{random_part}"

def generate_creator_request_id():
    """
    Generate unique creator request ID.
    OPTIMIZATION: Timestamp first ensures sequential DB inserts.
    Format: REQ_CREATOR_<TIMESTAMP>_<RANDOM_HEX>
    """
    timestamp = int(datetime.now().timestamp())
    random_part = uuid.uuid4().hex[:6].upper()
    return f"REQ_CREATOR_{timestamp}_{random_part}"

# ============================================================================
# PUBLIC ROUTES
# ============================================================================

@public_bp.route("/")
@limiter.limit("10 per minute")
def user_base():
    """Landing page for the learning platform"""
    secure_log("Landing page accessed")
    return render_template("base.html")


@public_bp.route("/terms-and-conditions/")
@limiter.limit("10 per minute")
def terms_and_condition():
    secure_log("T&C page accessed")
    return render_template("terms_and_condition.html")


@public_bp.route("/privacy-policy/")
@limiter.limit("10 per minute")
def privacy_policy():
    secure_log("Privacy policy page accessed")
    return render_template("privacy_policy.html")


@public_bp.route("/cancellation-and-refund/")
@limiter.limit("10 per minute")
def cancellation_and_refund():
    secure_log("Cancellation and refund page accessed")
    return render_template("cancellation_and_refund.html")


@public_bp.route("/how-it-works/")
@limiter.limit("10 per minute")
def how_it_works():
    secure_log("How it works page accessed")
    return render_template("how_it_works.html")


@public_bp.route("/cookie-policy/")
@limiter.limit("10 per minute")
def cookie_policy():
    secure_log("Cookie policy page accessed")
    return render_template("cookie_policy.html")


@public_bp.route("/help-center/")
@limiter.limit("10 per minute")
def help_center():
    secure_log("Help center page accessed")
    return render_template("help_center.html")


@public_bp.route("/contact-us/")
@limiter.limit("10 per minute")
def contact_us():
    """Contact us page - renders form only"""
    secure_log("Contact us page accessed")
    return render_template("contact_us.html")


@public_bp.route('/creator/')
@limiter.limit("10 per minute")
def creator_base():
    return render_template('creator_base_page.html')


@public_bp.route('/admin_certificate/')
@limiter.limit("10 per minute")
def admin_base():
    return render_template('admin_certificate_designer.html')


# ============================================================================
# CONTACT-US API ENDPOINTS
# ============================================================================

@public_bp.route("/api/contact-us/check-quota", methods=['GET'])
@limiter.limit("5 per minute")
def check_contact_quota():
    """
    GET /api/contact-us/check-quota
    Check if visitor has remaining quota for today
    
    Response:
    {
        "success": true,
        "can_submit": true,
        "remaining_queries": 9,
        "message": "9 queries remaining today"
    }
    """
    try:
        visitor_ip = get_visitor_identifier()
        can_submit, remaining, message = get_remaining_quota(visitor_ip)
        
        return jsonify({
            'success': True,
            'can_submit': can_submit,
            'remaining_queries': remaining,
            'message': message
        }), 200
        
    except Exception as e:
        secure_log(f"Error checking quota: {str(e)}", 'error')
        return jsonify({
            'success': False,
            'error': 'Error checking quota'
        }), 500


@public_bp.route("/api/contact-us/submit", methods=['POST'])
@limiter.limit("3 per minute")
def submit_contact_query():
    """
    POST /api/contact-us/submit
    Submit a contact-us query with Transaction Fail-Safe
    """
    try:
        # Get form data (matching existing HTML table names)
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()
        
        # Get visitor IP for quota tracking
        visitor_ip = get_visitor_identifier()
        
        # =====================================================================
        # VALIDATION
        # =====================================================================
        
        if not name:
            return jsonify({'success': False, 'error': 'Name is required'}), 400
        
        if not email:
            return jsonify({'success': False, 'error': 'Email is required'}), 400
        
        if '@' not in email or '.' not in email:
            return jsonify({'success': False, 'error': 'Invalid email address'}), 400
        
        if not subject:
            return jsonify({'success': False, 'error': 'Subject is required'}), 400
        
        if not message:
            return jsonify({'success': False, 'error': 'Message is required'}), 400
        
        # =====================================================================
        # QUOTA CHECK
        # =====================================================================
        
        can_submit, remaining, quota_message = get_remaining_quota(visitor_ip)
        
        if not can_submit:
            return jsonify({
                'success': False,
                'error': 'Daily limit reached',
                'message': quota_message,
                'remaining_queries': remaining
            }), 429
        
        # =====================================================================
        # SAVE QUERY TO DATABASE
        # =====================================================================
        
        query_id = generate_query_id()
        
        try:
            # 1. CRITICAL: Save the Message First
            execute_query("""
                INSERT INTO query_base.contact_us_queries 
                (query_id, name, email, phone, subject, message, visitor_ip, submitted_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            """, (
                query_id, name, email, phone, subject, message, visitor_ip
            ), commit=True)
            
            secure_log(f"Contact query submitted successfully: {query_id}")
            
            # 2. NON-CRITICAL: Update Quota (Fail-Open Safety)
            # If this fails, we log it but do NOT crash the user response.
            try:
                execute_query("""
                    INSERT INTO query_base.contact_daily_quota 
                    (visitor_ip, quota_date, queries_today, max_queries_per_day)
                    VALUES (%s, CURDATE(), 1, 10)
                    ON DUPLICATE KEY UPDATE queries_today = queries_today + 1
                """, (visitor_ip,), commit=True)
            except Exception as quota_error:
                # Log error but proceed. Better to give a free query than lose a customer message.
                secure_log(f"Quota update failed for {query_id}: {str(quota_error)}", 'warning')
            
            # Get updated remaining quota (safe calculation)
            new_remaining = max(0, remaining - 1)
            
            return jsonify({
                'success': True,
                'query_id': query_id,
                'message': 'Query submitted successfully. We will respond within 24 hours.',
                'remaining_queries': new_remaining
            }), 201
            
        except Exception as db_error:
            secure_log(f"Database error saving contact query: {str(db_error)}", 'error')
            return jsonify({
                'success': False,
                'error': 'Error saving query. Please try again.'
            }), 500
            
    except Exception as e:
        secure_log(f"Error submitting contact query: {str(e)}", 'error')
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred'
        }), 500
    

@public_bp.route("/join-as-creator/")
@limiter.limit("10 per minute")
def join_as_creator():
    """Render the Creator Join Request form"""
    secure_log("Creator join page accessed")
    return render_template("creator_join.html")


@public_bp.route("/api/creator/join-request/submit", methods=['POST'])
@limiter.limit("8 per hour")
def submit_creator_join_request():
    """
    POST /api/creator/join-request/submit
    Submit a YouTuber's request to join the platform
    """
    try:
        # Get form data
        name = request.form.get('name', '').strip()
        channel_name = request.form.get('channel_name', '').strip()
        channel_link = request.form.get('channel_link', '').strip()
        content_type = request.form.get('content_type', '').strip()
        contact_number = request.form.get('contact_number', '').strip()
        email = request.form.get('email', '').lower().strip()
        subscriber_count_raw = request.form.get('subscriber_count', '0').strip()
        
        # Get visitor IP
        visitor_ip = get_visitor_identifier()
        
        # =====================================================================
        # VALIDATION
        # =====================================================================
        
        if not all([name, channel_name, channel_link, content_type, contact_number, email]):
            return jsonify({
                'success': False,
                'error': 'All text fields are required'
            }), 400
            
        if '@' not in email or '.' not in email:
            return jsonify({
                'success': False,
                'error': 'Invalid email address'
            }), 400

        try:
            # Handle common formats like "1.5k" or "1M" nicely before failing?
            # For now, strict integer check is safer for DB security.
            subscriber_count = int(float(subscriber_count_raw.replace(',', '')))
        except ValueError:
            return jsonify({
                'success': False,
                'error': 'Subscriber count must be a valid number'
            }), 400
            
        # =====================================================================
        # DUPLICATE CHECK
        # =====================================================================
        try:
            result = execute_query(
                "SELECT request_id FROM query_base.creator_join_requests WHERE email = %s AND status = 'pending'",
                (email,),
                fetch_one=True
            )
            if result:
                return jsonify({
                    'success': False,
                    'error': 'A pending request for this email already exists.'
                }), 409
        except Exception as e:
            secure_log(f"Duplicate check failed (non-critical): {e}", 'warning')
            
        # =====================================================================
        # SAVE REQUEST
        # =====================================================================
        
        request_id = generate_creator_request_id()
        
        try:
            execute_query("""
                INSERT INTO query_base.creator_join_requests 
                (request_id, name, channel_name, channel_link, content_type, 
                 subscriber_count, email, contact_number, visitor_ip, submitted_at, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), 'pending')
            """, (
                request_id, name, channel_name, channel_link, content_type,
                subscriber_count, email, contact_number, visitor_ip
            ), commit=True)
            
            secure_log(f"Creator join request submitted: {request_id} by {email}")
            
            return jsonify({
                'success': True,
                'request_id': request_id,
                'message': 'Request submitted successfully. Our team will review your channel and contact you.'
            }), 201
            
        except Exception as db_error:
            secure_log(f"Database error during creator request: {str(db_error)}", 'error')
            return jsonify({
                'success': False,
                'error': 'Error saving request. Please try again.'
            }), 500
            
    except Exception as e:
        secure_log(f"Error submitting creator join request: {str(e)}", 'error')
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred'
        }), 500


# ============================================================================
# SHAREABLE EXAM LINK (PUBLIC ACCESS)
# ============================================================================

@public_bp.route('/exam/<exam_id>/')
@limiter.limit("30 per minute")
def view_public_exam(exam_id):
    """
    Public shareable exam page.
    Shows exam details with options to view on YouTube or enroll.

    Args:
        exam_id: The unique_exam_number of the exam
    """
    try:
        # Fetch exam details with creator info
        exam = execute_query("""
            SELECT
                le.unique_exam_number,
                le.exam_title,
                le.exam_description,
                le.thumbnail_image,
                le.exam_price,
                le.video_id,
                le.playlist_id,
                le.channel_id,
                le.channel_name,
                le.number_of_subscribers,
                le.is_active,
                le.created_at,
                c.profile_photo_jpg as creator_photo,
                c.youtube_channel_link,
                (SELECT COUNT(*) FROM exam.exam_questions eq
                 WHERE eq.unique_exam_number = le.unique_exam_number) as has_questions,
                (SELECT JSON_LENGTH(questions_json) FROM exam.exam_questions eq
                 WHERE eq.unique_exam_number = le.unique_exam_number) as question_count
            FROM exam.listed_exams le
            LEFT JOIN creator_base.creators c ON le.channel_id = c.channel_id
            WHERE le.unique_exam_number = %s
        """, (exam_id,), fetch_one=True)

        if not exam:
            secure_log(f"Public exam not found: {exam_id}", 'warning')
            return render_template('public_exam_not_found.html'), 404

        if not exam.get('is_active'):
            secure_log(f"Inactive exam accessed: {exam_id}", 'warning')
            return render_template('public_exam_not_found.html',
                                   message="This exam is no longer available."), 404

        # Generate YouTube URL
        if exam.get('video_id'):
            youtube_url = f"https://www.youtube.com/watch?v={exam['video_id']}"
            content_type = 'video'
        elif exam.get('playlist_id'):
            youtube_url = f"https://www.youtube.com/playlist?list={exam['playlist_id']}"
            content_type = 'playlist'
        else:
            youtube_url = exam.get('youtube_channel_link', '#')
            content_type = 'channel'

        # Process thumbnail URL (handle GCS signed URLs)
        thumbnail_url = exam.get('thumbnail_image', '')
        if thumbnail_url and not thumbnail_url.startswith('http'):
            # It's an R2 path, need to get public URL
            from youcert import get_file_url
            thumbnail_url = get_file_url(thumbnail_url) or '/static/images/default-exam-thumbnail.png'

        # Process creator photo URL
        creator_photo = exam.get('creator_photo', '')
        if creator_photo and not creator_photo.startswith('http'):
            from youcert import get_file_url
            creator_photo = get_file_url(creator_photo) or '/static/images/default-avatar.png'

        # Format subscriber count
        subscriber_count = exam.get('number_of_subscribers', 0)
        if subscriber_count >= 1000000:
            formatted_subscribers = f"{subscriber_count / 1000000:.1f}M"
        elif subscriber_count >= 1000:
            formatted_subscribers = f"{subscriber_count / 1000:.1f}K"
        else:
            formatted_subscribers = str(subscriber_count)

        # Get question count
        question_count = exam.get('question_count', 0)
        if question_count is None:
            question_count = 0

        secure_log(f"Public exam page accessed: {exam_id}", 'info')

        return render_template('public_exam_view.html',
            exam=exam,
            youtube_url=youtube_url,
            content_type=content_type,
            thumbnail_url=thumbnail_url,
            creator_photo=creator_photo,
            formatted_subscribers=formatted_subscribers,
            question_count=question_count
        )

    except Exception as e:
        secure_log(f"Error loading public exam page: {str(e)}", 'error')
        return render_template('public_exam_not_found.html',
                               message="An error occurred while loading this exam."), 500


@public_bp.route('/api/public/search-exams', methods=['GET'])
@limiter.limit("30 per minute")
def public_search_exams():
    """
    Public API to search for exams (no login required).
    Used by the exam not found page to help users find exams.

    Query params:
        q: Search query (minimum 3 characters)

    Returns:
        JSON with list of matching exams
    """
    try:
        query = request.args.get('q', '').strip()

        # Validate query length
        if len(query) < 3:
            return jsonify({
                'success': False,
                'error': 'Search query must be at least 3 characters'
            }), 400

        # Search for active exams only
        search_pattern = f"%{query}%"

        exams = execute_query("""
            SELECT
                le.unique_exam_number,
                le.exam_title,
                le.exam_description,
                le.thumbnail_image,
                le.exam_price,
                le.channel_name,
                (SELECT JSON_LENGTH(questions_json) FROM exam.exam_questions eq
                 WHERE eq.unique_exam_number = le.unique_exam_number) as question_count
            FROM exam.listed_exams le
            WHERE le.is_active = TRUE
              AND (le.exam_title LIKE %s OR le.exam_description LIKE %s OR le.channel_name LIKE %s)
            ORDER BY le.created_at DESC
            LIMIT 10
        """, (search_pattern, search_pattern, search_pattern), fetch_all=True)

        # Process thumbnails
        results = []
        for exam in exams or []:
            exam_dict = dict(exam)

            # Generate signed URL for thumbnail
            thumbnail_url = exam_dict.get('thumbnail_image', '')
            if thumbnail_url and not thumbnail_url.startswith('http'):
                from youcert import get_file_url
                thumbnail_url = get_file_url(thumbnail_url) or ''
            exam_dict['thumbnail_url'] = thumbnail_url

            # Ensure question_count is a number
            exam_dict['question_count'] = exam_dict.get('question_count') or 0

            # Ensure exam_price is a float (Decimal doesn't serialize well)
            exam_dict['exam_price'] = float(exam_dict.get('exam_price', 0) or 0)

            results.append(exam_dict)

        secure_log(f"Public exam search: '{query}' returned {len(results)} results", 'info')

        return jsonify({
            'success': True,
            'exams': results,
            'count': len(results)
        })

    except Exception as e:
        secure_log(f"Public search error: {str(e)}", 'error')
        return jsonify({
            'success': False,
            'error': 'Search failed. Please try again.'
        }), 500


@public_bp.route('/health', methods=['GET'])
@public_bp.route('/healthz', methods=['GET'])
def health_check():
    """
    Health check endpoint for container health probes and monitoring.
    Returns basic service status without database check.

    Returns:
        200: Service is healthy
    """
    # Simple health check without database query
    # Database connectivity is verified by actual application routes
    return jsonify({
        'status': 'healthy',
        'service': 'youcert',
        'timestamp': datetime.now().isoformat()
    }), 200


@public_bp.route('/.well-known/appspecific/com.chrome.devtools.json')
def chrome_devtools():
    """Handle Chrome DevTools request to suppress 404 errors"""
    return jsonify({}), 200


@public_bp.route("/api/contact-us/query/<query_id>", methods=['GET'])
@limiter.limit("5 per minute")
def get_query_status(query_id):
    """
    GET /api/contact-us/query/<query_id>
    Get status of a specific query
    
    Response:
    {
        "success": true,
        "query": {
            "query_id": "QUERY_A1B2C3D4_1699123456",
            "name": "John Doe",
            "email": "john@example.com",
            "subject": "Issue with payment",
            "submitted_at": "2024-01-15 10:30:00"
        }
    }
    """
    try:
        
        query = execute_query("""
            SELECT 
                query_id, name, email, phone, subject, message,
                visitor_ip, submitted_at
            FROM query_base.contact_us_queries
            WHERE query_id = %s
        """, (query_id,), fetch_one=True)
        
        if not query:
            return jsonify({
                'success': False,
                'error': 'Query not found'
            }), 404
        
        # Convert datetime objects to strings
        if query.get('submitted_at'):
            query['submitted_at'] = query['submitted_at'].strftime('%Y-%m-%d %H:%M:%S')
            
        return jsonify({
            'success': True,
            'query': query
        }), 200
            
    except Exception as e:
        secure_log(f"Error fetching query status: {str(e)}", 'error')
        return jsonify({
            'success': False,
            'error': 'Error fetching query details'
        }), 500


# ============================================================================
# STATIC FILES
# ============================================================================

@public_bp.route('/favicon.ico')
def favicon():
    """Serve favicon.ico from project root directory"""
    import os
    from flask import current_app

    # Get the project root directory (parent of youcert directory)
    # current_app.root_path points to the 'youcert' directory
    project_root = os.path.dirname(current_app.root_path)

    return send_from_directory(
        project_root,
        'favicon.ico',
        mimetype='image/vnd.microsoft.icon'
    )


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@public_bp.errorhandler(429)
def ratelimit_handler(e):
    """Handle rate limit exceeded"""
    return jsonify({
        'success': False,
        'error': 'Rate limit exceeded. Please try again later.'
    }), 429


@public_bp.errorhandler(405)
def method_not_allowed(e):
    """Handle method not allowed"""
    return jsonify({
        'success': False,
        'error': 'Method not allowed'
    }), 405


