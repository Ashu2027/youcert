"""
email_service.py - DATABASE OTP VERSION (UPGRADED v14.0)

Features:
- "Black & Gray" Premium Theme (Matches exams.html)
- RANDOM OTP generation (6-digit, 9-minute expiry) - Replaces PyOTP
- DATABASE STORAGE - Multi-instance compatible for containerized environments
- Dynamic User Support (Creator/Admin/User)
- Brand Logo Integration (Requires SERVICE_URL)
- Centralized logging & User-Isolated Caching
- FULL Error Handling Preserved

UPGRADED v14.0:
    - Replaced PyOTP with random library for simpler OTP generation
    - Database-level OTP storage via admin_base.otp_tokens table
    - Multi-instance ready - Works across all container instances
    - Maintains exact API compatibility with previous version
    - All existing functionality preserved
"""

import requests
import json
import random  # UPGRADED: Replaced pyotp with random
from datetime import datetime
from flask import current_app, request

# Import centralized logging and caching from youcert
from youcert import (
    secure_log, 
    set_user_cache, 
    get_user_cache, 
    delete_user_cache,
    # UPGRADED: Import database OTP functions
    save_otp_to_database,
    get_otp_from_database,
    verify_otp_from_database,
    delete_otp_from_database
)


# ============================================================================
# HELPER: PREMIUM EMAIL TEMPLATE GENERATOR (BLACK & GRAY THEME)
# ============================================================================

def _generate_styled_email(title, body_content, recipient_name=None):
    """
    Wraps content in the Youcert 'Black & Gray' Premium Theme.
    """
    try:
        # 1. Get Base URL (Critical for Images in Email)
        # In production, set SERVICE_URL env var to your https://... address
        base_url = current_app.config.get('SERVICE_URL', '').rstrip('/')
        
        # Fallback for local testing (Image won't show in Gmail if localhost, but link generates)
        if not base_url:
            base_url = 'http://127.0.0.1:5000'
        
        logo_url = f"{base_url}/static/icon/logo.png"
    except Exception:
        logo_url = "" 

    greeting = f"Hello {recipient_name}," if recipient_name else "Hello,"

    # THEME CONSTANTS (Black & Gray / Inter)
    BG_COLOR = "#F5F5F7"      # Light Gray Background
    CARD_BG = "#FFFFFF"       # White Card
    TEXT_MAIN = "#1D1D1F"     # Black/Dark Gray Text
    TEXT_MUTED = "#86868b"    # Muted Gray
    BUTTON_COLOR = "#1D1D1F"  # Black Button (Matches exams.html)
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title}</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
            
            body {{ 
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; 
                margin: 0; 
                padding: 0; 
                background-color: {BG_COLOR}; 
                color: {TEXT_MAIN}; 
            }}
            
            .container {{ 
                width: 100%; 
                max-width: 600px; 
                margin: 0 auto; 
                padding: 40px 20px; 
            }}
            
            .card {{ 
                background-color: {CARD_BG}; 
                border-radius: 24px; 
                padding: 40px; 
                box-shadow: 0 10px 40px -10px rgba(0,0,0,0.05); 
                border: 1px solid rgba(0,0,0,0.05);
            }}
            
            .logo {{ 
                text-align: center; 
                margin-bottom: 30px; 
            }}
            
            .logo img {{ 
                height: 40px; 
                width: auto; 
                /* Fail-safe if image breaks */
                font-family: sans-serif;
                font-weight: bold;
                font-size: 20px;
                color: {TEXT_MAIN};
            }}
            
            .header {{ 
                font-size: 24px; 
                font-weight: 700; 
                margin-bottom: 20px; 
                letter-spacing: -0.02em; 
                color: {TEXT_MAIN}; 
            }}
            
            .text {{ 
                font-size: 16px; 
                line-height: 1.6; 
                color: {TEXT_MAIN}; 
                margin-bottom: 20px; 
            }}
            
            .footer {{ 
                text-align: center; 
                margin-top: 30px; 
                font-size: 12px; 
                color: {TEXT_MUTED}; 
            }}
            
            /* Black Button Style */
            .btn {{ 
                display: inline-block; 
                background-color: {BUTTON_COLOR}; 
                color: #FFFFFF !important; 
                padding: 14px 28px; 
                border-radius: 14px; 
                text-decoration: none; 
                font-weight: 600; 
                margin-top: 20px; 
                box-shadow: 0 4px 10px rgba(0,0,0,0.1);
            }}
            
            /* OTP Box Style */
            .otp-box {{ 
                background: #F5F5F7; 
                padding: 20px; 
                border-radius: 16px; 
                text-align: center; 
                font-size: 32px; 
                font-weight: 700; 
                letter-spacing: 6px; 
                color: {TEXT_MAIN}; 
                margin: 30px 0; 
                border: 1px solid rgba(0,0,0,0.1); 
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">
                <img src="{logo_url}" alt="Youcert" width="auto" height="40">
            </div>
            
            <div class="card">
                <div class="header">{title}</div>
                <div class="text">
                    <p><strong>{greeting}</strong></p>
                    {body_content}
                </div>
            </div>
            
            <div class="footer">
                &copy; {datetime.now().year} Youcert. All rights reserved.<br>
                This is an automated message, please do not reply.
            </div>
        </div>
    </body>
    </html>
    """
    return html


# ============================================================================
# ZEPTOMAIL SERVICE CLASS (UPGRADED WITH RANDOM OTP & DATABASE STORAGE)
# ============================================================================

class ZeptoMailService:
    """
    Production-grade email service using RANDOM OTP for secure generation
    and DATABASE storage for multi-instance compatibility.
    
    UPGRADED v14.0:
    - Replaced PyOTP with random library
    - Database storage via admin_base.otp_tokens
    - Maintains exact API compatibility
    """
    
    def __init__(self, from_email_override=None, from_name_override=None):
        """
        Initialize email service settings

        Args:
            from_email_override: Override default from email (e.g., communications@youcert.com)
            from_name_override: Override default from name (e.g., YOUCERT Communications)
        """
        self.api_url = "https://api.zeptomail.in/v1.1/email"
        self.timeout = 10
        # UPGRADED: 9 Minutes = 540 seconds
        self.otp_validity_seconds = 540
        self.max_attempts = 5
        self.cache = None  # Maintained for legacy compatibility
        self.from_email_override = from_email_override
        self.from_name_override = from_name_override
    
    def set_cache(self, cache_obj):
        """
        Legacy compatibility method.
        The actual caching now uses centralized youcert functions.
        """
        self.cache = cache_obj
        secure_log("Cache object set for email service (using centralized caching)", 'info')
    
    def get_config(self):
        """Retrieve ZeptoMail configuration from app config."""
        try:
            token = current_app.config.get("ZEPTOMAIL_TOKEN")

            # Use overrides if provided, otherwise use default config
            from_email = self.from_email_override or current_app.config.get("ZEPTOMAIL_FROM")
            from_name = self.from_name_override or current_app.config.get("ZEPTOMAIL_FROM_NAME", "YOUCERT")

            if not token or not from_email:
                secure_log("ZeptoMail credentials not configured", 'error')
                return None, None, None

            return token, from_email, from_name
        except Exception as e:
            secure_log(f"Error getting ZeptoMail config: {e}", 'error')
            return None, None, None
    
    def send_email(self, to_email: str, subject: str, html_body: str, to_name: str = None) -> bool:
        """
        Send email via ZeptoMail API with full error handling.
        
        Args:
            to_email: Recipient email
            subject: Email subject
            html_body: HTML email body
            to_name: Recipient name (optional)
        
        Returns:
            bool: True if email sent successfully
        """
        token, from_email, from_name = self.get_config()
        if not token:
            return False
        
        try:
            secure_log(f"Sending email to {to_email}", 'info')
            
            payload = {
                "from": {"address": from_email, "name": from_name},
                "to": [{"email_address": {"address": to_email, "name": to_name or to_email}}],
                "subject": subject,
                "htmlbody": html_body
            }
            
            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "authorization": token
            }
            
            response = requests.post(
                self.api_url, 
                json=payload, 
                headers=headers, 
                timeout=self.timeout
            )
            
            if response.status_code in [200, 201]:
                secure_log(f"Email sent successfully to {to_email}", 'info')
                return True
            else:
                secure_log(
                    f"Email send failed: {response.status_code}",
                    'error',
                    status_code=response.status_code,
                    response=response.text[:200]
                )
                return False
                
        except requests.exceptions.Timeout:
            secure_log(f"Email timeout for {to_email}", 'error')
            return False
        except Exception as e:
            secure_log(f"Email send error: {e}", 'error')
            return False
    
    def generate_otp(self, user_type: str, email: str, purpose: str = 'login') -> str:
        """
        Generate random 6-digit OTP and store in database.
        
        UPGRADED v14.0:
        - Uses random.randint instead of PyOTP
        - Stores in database via save_otp_to_database
        
        Args:
            user_type: 'admin', 'creator', or 'user'
            email: User email address
            purpose: Purpose of OTP (login, registration, first_time_setup, etc)
        
        Returns:
            str: 6-digit OTP code or None on failure
        """
        try:
            # Generate 6-digit random OTP
            otp_code = str(random.randint(100000, 999999))
            
            # Get IP address for logging
            try:
                ip_address = request.remote_addr if request else None
            except:
                ip_address = None
            
            # Save to database
            success = save_otp_to_database(
                user_type=user_type,
                email=email,
                otp_code=otp_code,
                purpose=purpose,
                expiry_seconds=self.otp_validity_seconds,
                ip_address=ip_address
            )
            
            if success:
                secure_log(
                    f"Random OTP generated for {user_type}",
                    'info',
                    context={'email': f"{email[:15]}..."}
                )
                return otp_code
            else:
                secure_log(f"Failed to save OTP to database", 'error')
                return None
                
        except Exception as e:
            secure_log(f"Error generating OTP: {e}", 'error')
            return None
    
    def verify_otp(self, user_type: str, email: str, entered_otp: str, purpose: str = 'login') -> dict:
        """
        Verify OTP from database with attempt tracking.
        
        UPGRADED v14.0:
        - Retrieves from database via verify_otp_from_database
        - Maintains exact API compatibility
        
        Args:
            user_type: 'admin', 'creator', or 'user'
            email: User email address
            entered_otp: OTP code entered by user
            purpose: Purpose of OTP
        
        Returns:
            dict: Verification result with status and metadata
        """
        try:
            # Get current attempts from cache (still using cache for attempt tracking)
            cache_key = f"otp_attempts:{user_type}"
            attempts_data = get_user_cache(cache_key, user_id=email)
            attempts = attempts_data if attempts_data else 0
            
            # Check max attempts
            if attempts >= self.max_attempts:
                remaining_attempts = 0
                secure_log(
                    f"Max OTP attempts reached for {user_type}",
                    'warning',
                    context={'email': email}
                )
                return {
                    'verified': False,
                    'message': 'Too many attempts',
                    'attempts_left': remaining_attempts,
                    'time_left': 0
                }
            
            # Verify OTP from database
            verified = verify_otp_from_database(user_type, email, entered_otp, purpose)
            
            if verified:
                # Clear attempts on success
                delete_user_cache(cache_key, user_id=email)
                
                secure_log(
                    f"Random OTP verified successfully for {user_type}",
                    'info',
                    context={'email': email}
                )
                
                return {
                    'verified': True,
                    'message': 'Verification successful',
                    'attempts_left': self.max_attempts,
                    'time_left': 0
                }
            else:
                # Increment attempts
                attempts += 1
                set_user_cache(cache_key, attempts, user_id=email, timeout=self.otp_validity_seconds)
                remaining_attempts = self.max_attempts - attempts
                
                secure_log(
                    f"OTP verification failed for {user_type} (attempt {attempts}/{self.max_attempts})",
                    'warning',
                    context={'email': email}
                )
                
                return {
                    'verified': False,
                    'message': 'Invalid or expired code',
                    'attempts_left': remaining_attempts,
                    'time_left': 0
                }
                
        except Exception as e:
            secure_log(f"Error verifying OTP: {e}", 'error')
            return {
                'verified': False, 
                'message': 'System error', 
                'attempts_left': 0, 
                'time_left': 0
            }
    
    def delete_otp(self, user_type: str, email: str, purpose: str = 'login') -> bool:
        """
        Delete OTP from database.
        
        UPGRADED v14.0:
        - Deletes from database via delete_otp_from_database
        
        Args:
            user_type: 'admin', 'creator', or 'user'
            email: User email address
            purpose: Purpose of OTP
        
        Returns:
            bool: True if successful
        """
        try:
            success = delete_otp_from_database(user_type, email, purpose)
            
            if success:
                secure_log(f"OTP deleted for {user_type}", 'info', context={'email': email})
            
            return success
        except Exception as e:
            secure_log(f"Error deleting OTP: {e}", 'error')
            return False


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

email_service = ZeptoMailService()


# ============================================================================
# HIGH-LEVEL FUNCTIONS - UPGRADED WITH RANDOM OTP & DATABASE STORAGE
# ============================================================================

def send_otp_email(email: str, user_type: str = 'creator', to_name: str = None, purpose: str = 'login') -> str:
    """
    Generate random OTP (9 min expiry) and send via Black/Gray Theme email.
    
    UPGRADED v14.0:
    - Uses random library instead of PyOTP
    - Stores in database instead of filesystem
    - Maintains exact API compatibility
    
    Args:
        email: Recipient email
        user_type: 'creator', 'admin', 'user'
        to_name: Recipient name (optional)
        purpose: Purpose of OTP (login, registration, first_time_setup, etc)
    
    Returns:
        str: OTP code if successful, None on failure
    """
    try:
        # Dynamic user_type generation with database storage
        otp_code = email_service.generate_otp(user_type, email, purpose)
        
        if not otp_code:
            secure_log(f"Failed to generate OTP", 'error', context={'email': email})
            return None
        
        minutes = int(email_service.otp_validity_seconds / 60)
        
        body_content = f"""
            <p>Your verification code for Youcert is below. Please enter this code to complete your verification.</p>
            
            <div class="otp-box">{otp_code}</div>
            
            <p>This code is valid for <b>{minutes} minutes</b> and can only be used once.</p>
            <p style="color: #86868b; font-size: 14px;">If you did not request this code, please ignore this email.</p>
        """
        
        html_content = _generate_styled_email("Verify Your Account", body_content, to_name)
        
        success = email_service.send_email(
            to_email=email,
            subject="Your Verification Code - Youcert",
            html_body=html_content,
            to_name=to_name
        )
        
        if success:
            secure_log(f"OTP email sent for {user_type}", 'info', context={'email': email})
            return otp_code
        else:
            email_service.delete_otp(user_type, email, purpose)
            secure_log("Failed to send OTP email", 'error', context={'email': email})
            return None
            
    except Exception as e:
        secure_log(f"Error in send_otp_email: {e}", 'error')
        return None


def verify_otp_email(email: str, entered_otp: str, user_type: str = 'creator', purpose: str = 'login') -> dict:
    """
    Verify OTP with dynamic user type support.
    
    UPGRADED v14.0:
    - Verifies from database instead of filesystem
    - Maintains exact API compatibility
    
    Args:
        email: User email
        entered_otp: OTP code entered by user
        user_type: 'creator', 'admin', 'user'
        purpose: Purpose of OTP
    
    Returns:
        dict: Verification result
    """
    return email_service.verify_otp(user_type, email, entered_otp, purpose)


def send_password_reset_email(email: str, reset_link: str, to_name: str = None) -> bool:
    """
    Send password reset email with Black/Gray Theme.
    """
    try:
        body_content = f"""
            <p>A request has been made to reset the password for your Youcert account.</p>
            <p>Please click the button below to reset your password:</p>
            
            <div style="text-align: center;">
                <a href="{reset_link}" class="btn">Reset Password</a>
            </div>
            
            <p style="margin-top: 30px;">This link is valid for 10 minutes.</p>
            <p style="color: #86868b; font-size: 14px;">If you didn't request this change, you can safely ignore this email.</p>
        """
        
        html_content = _generate_styled_email("Password Reset Request", body_content, to_name)
        
        return email_service.send_email(
            to_email=email, 
            subject="Reset Your Password - Youcert", 
            html_body=html_content, 
            to_name=to_name
        )
        
    except Exception as e:
        secure_log(f"Error in send_password_reset_email: {e}", 'error')
        return False


def send_admin_welcome_email(email: str, admin_name: str, admin_id: str, temp_password: str, login_url: str) -> bool:
    """
    Send admin welcome email with Black/Gray Theme.
    """
    try:
        body_content = f"""
            <p>Your admin account has been created and approved successfully.</p>
            
            <div style="background: #F5F5F7; padding: 20px; border-radius: 12px; margin: 20px 0; border: 1px solid rgba(0,0,0,0.05);">
                <p style="margin: 5px 0;"><b>Admin ID:</b> {admin_id}</p>
                <p style="margin: 5px 0;"><b>Temporary Password:</b> {temp_password}</p>
            </div>
            
            <div style="text-align: center;">
                <a href="{login_url}" class="btn">Login to Dashboard</a>
            </div>
            
            <p style="margin-top: 30px; font-weight: 600;">IMPORTANT:</p>
            <p>Please change your password immediately after your first login for security purposes.</p>
        """
        
        html_content = _generate_styled_email("Welcome to Youcert Admin", body_content, admin_name)
        
        return email_service.send_email(
            to_email=email, 
            subject="Your Admin Account is Ready", 
            html_body=html_content, 
            to_name=admin_name
        )
        
    except Exception as e:
        secure_log(f"Error in send_admin_welcome_email: {e}", 'error')
        return False


def send_admin_rejection_email(email: str, admin_name: str, rejection_reason: str) -> bool:
    """
    Send admin rejection email with Black/Gray Theme.
    """
    try:
        body_content = f"""
            <p>We have reviewed your request for an admin account.</p>
            <p><b>Status:</b> <span style="color: #EF4444; font-weight: 700;">Rejected</span></p>
            
            <div style="background: #FEE2E2; color: #991B1B; padding: 20px; border-radius: 12px; margin: 20px 0; border: 1px solid #FECACA;">
                <strong>Reason:</strong><br>
                {rejection_reason}
            </div>
            
            <p>If you believe this decision was made in error or if you have any questions, please contact the system administrator.</p>
        """
        
        html_content = _generate_styled_email("Admin Registration Update", body_content, admin_name)
        
        return email_service.send_email(
            to_email=email, 
            subject="Registration Status Update - Youcert", 
            html_body=html_content, 
            to_name=admin_name
        )
        
    except Exception as e:
        secure_log(f"Error in send_admin_rejection_email: {e}", 'error')
        return False


def send_creator_verification_success_email(email: str, creator_name: str) -> bool:
    """
    Send creator success email with Black/Gray Theme.
    """
    try:
        body_content = f"""
            <p>Congratulations! Your email has been successfully verified.</p>
            <p>You can now connect your YouTube channel and start creating exams on the platform.</p>
            
            <div style="text-align: center; margin-top: 30px;">
                <p style="font-weight: 600; color: #1D1D1F;">Welcome to the community!</p>
            </div>
        """
        
        html_content = _generate_styled_email("Email Verified Successfully", body_content, creator_name)
        
        return email_service.send_email(
            to_email=email, 
            subject="Welcome to Youcert!", 
            html_body=html_content, 
            to_name=creator_name
        )
        
    except Exception as e:
        secure_log(f"Error in send_creator_verification_success_email: {e}", 'error')
        return False


# ============================================================================
# END OF UPGRADED EMAIL SERVICE (v14.0)
# ============================================================================