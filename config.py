# ==============================================================================
# YOUCERT CONFIGURATION FILE
# ==============================================================================
#
# This configuration file works in BOTH environments:
#   - Windows Local Development
#   - Cloudflare Containers Production
#
# ==============================================================================
# QUICK START GUIDE
# ==============================================================================
# ==============================================================================

from dotenv import load_dotenv
import os
import sys
import logging
import base64

# Load .env file for local development
load_dotenv()

logger = logging.getLogger(__name__)


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def get_secret(key, file_path=None, default=None):
    """
    Securely retrieve secrets with priority order:
    1. Read from Secret File (if mounted)
       - Secrets mounted as files in /secrets/ directory
    2. Read from Environment Variable (Local Dev / Fallback)

    Args:
        key: Environment variable name (e.g., 'MYSQL_PASSWORD')
        file_path: Optional file path where secret is mounted (e.g., '/secrets/mysql_password')
        default: Default value if secret not found

    Returns:
        Secret value as string or default value
    """
    # Priority 1: Try reading from mounted file
    if file_path and os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                value = f.read().strip()
                if value:  # Only return non-empty values
                    return value
        except Exception as e:
            # Log but don't fail - will fallback to env var
            logger.warning(f"Failed to read secret from {file_path}: {e}")

    # Priority 2: Fallback to environment variable (local dev)
    return os.environ.get(key, default)


def safe_int(value, default=0):
    """Safely convert value to integer with fallback"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_float(value, default=0.0):
    """Safely convert value to float with fallback"""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_bool(value, default=False):
    """Safely convert value to boolean with fallback"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes', 'on')
    return default


# ==============================================================================
# MAIN CONFIGURATION CLASS
# ==============================================================================

class Config:
    """
    Centralized configuration for YOUCERT application.

    Compatible with:
    - Windows Local Development
    - Cloudflare Containers Production
    """

    # ==========================================================================
    # 1. DEPLOYMENT SETTINGS
    # ==========================================================================
    # Environment Detection - Single Toggle
    # In .env file: set IS_DEVELOPMENT=true as an environment variable
    IS_DEVELOPMENT = os.environ.get('IS_DEVELOPMENT', 'False').lower() == 'true'
    
    # Derived variables
    IS_CLOUDFLARE = not IS_DEVELOPMENT
    IS_CLOUD_RUN = not IS_DEVELOPMENT
    FLASK_ENV = "development" if IS_DEVELOPMENT else "production"
    DEBUG = IS_DEVELOPMENT
    TESTING = False

    # Cloudflare Account Configuration
    CLOUDFLARE_ACCOUNT_ID = os.environ.get('CLOUDFLARE_ACCOUNT_ID', '')
    CLOUDFLARE_API_TOKEN = os.environ.get('CLOUDFLARE_API_TOKEN', '')

    # Google Project ID (retained only for Gemini API error messages / reference)
    GOOGLE_PROJECT_ID = 'youcert-480502'

    # Google Cloud services DISABLED — replaced by Cloudflare equivalents
    USE_GOOGLE_SECRETS = False

    # Application Base URL (for QR codes, email links, etc.)
    # Auto-switches between local and production domain
    # Primary domain is www.youcert.com, youcert.com redirects to it
    BASE_URL = "http://127.0.0.1:5000" if FLASK_ENV == "development" else "https://www.youcert.com"
    BASE_URL_ALT = "http://127.0.0.1:5000" if FLASK_ENV == "development" else "https://youcert.com"




    # ==========================================================================
    # 2. REQUIRED SECRETS (Read from .env file or Cloudflare Workers Secrets)
    # ==========================================================================
    # [IMPORTANT] These MUST be set in your .env file for local development
    # [IMPORTANT] Set these as Workers Secrets on Cloudflare for production
    # ==========================================================================

    # Flask Secret Key (for session signing)
    # [REQUIRED] Generate with: python -c "import secrets; print(secrets.token_hex(32))"
    # Local: SECRET_KEY in .env | Cloud: Workers Secret
    SECRET_KEY = None  # Will be loaded in __init__ section below

    # Encryption Key (Fernet key for local development)
    # [REQUIRED] Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Local: TOKEN_ENCRYPTION_KEY in .env | Cloud: Workers Secret
    TOKEN_ENCRYPTION_KEY = None  # Will be loaded in __init__ section below

    # MySQL Database Credentials
    # [REQUIRED] Set your MySQL connection details
    # Local: Uses underscores | Cloud: Uses hyphens (or Unix socket)
    MYSQL_HOST = None  # Will be loaded below (TCP connection for local dev)
    MYSQL_USER = None  # Will be loaded below
    MYSQL_PASSWORD = None  # Will be loaded below
    MYSQL_PORT = 3306  # Default MySQL port (TiDB uses 4000)
    MYSQL_UNIX_SOCKET = None  # Not used (Cloudflare uses TCP only)

    # Google OAuth Credentials
    # [REQUIRED] Get from Google Cloud Console > APIs & Services > Credentials
    # Local: Uses underscores | Cloud: Uses hyphens
    GOOGLE_CLIENT_ID = None  # Will be loaded below
    GOOGLE_CLIENT_SECRET = None  # Will be loaded below

    # Razorpay Payment Gateway Credentials
    # [REQUIRED] Get from https://dashboard.razorpay.com/
    # Local: Uses underscores | Cloud: Uses hyphens
    RAZORPAY_KEY_ID = None  # Will be loaded below
    RAZORPAY_KEY_SECRET = None  # Will be loaded below

    # ZeptoMail Email Service Credentials
    # [REQUIRED] Get from https://www.zoho.com/zeptomail/
    # Local: Uses underscores | Cloud: Uses hyphens
    ZEPTOMAIL_TOKEN = None  # Will be loaded below


    # ==========================================================================
    # LOAD SECRETS (Automatic - Uses get_config_value helper)
    # ==========================================================================
    # This runs when the Config class is initialized
    # Automatically handles:
    #   - Local: Reads from .env
    #   - Cloud: Reads from Workers Secrets (env vars)
    # ==========================================================================

    @classmethod
    def _load_secrets(cls):
        """
        Load all secrets from environment variables.

        Cloudflare Containers: secrets injected as plain env vars via Workers Secrets.
        Local development: secrets loaded from .env file via python-dotenv.
        Both environments use the same os.environ.get() pattern — no file mounts needed.
        """
        # Flask session signing key
        # IMPORTANT: If SECRET_KEY is missing, Flask will crash on startup.
        # Generate a temporary random key as fallback (sessions won't persist across restarts)
        secret = os.environ.get('SECRET_KEY', '')
        if not secret:
            import secrets as _secrets
            secret = _secrets.token_hex(32)
            logger.warning("SECRET_KEY not set — using random key (sessions will not persist across restarts)")
        cls.SECRET_KEY = secret

        # Fernet encryption key (used for token encryption)
        # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
        cls.TOKEN_ENCRYPTION_KEY = os.environ.get('TOKEN_ENCRYPTION_KEY', None)

        # Database credentials (TCP only — no Unix socket for Cloudflare)
        cls.MYSQL_UNIX_SOCKET = None
        cls.MYSQL_HOST = cls.get_config_value('MYSQL_HOST', default='localhost')
        cls.MYSQL_USER = cls.get_config_value('MYSQL_USER', default='root')
        cls.MYSQL_PASSWORD = cls.get_config_value('MYSQL_PASSWORD', default='')
        # TiDB Cloud uses port 4000; local MySQL uses 3306
        cls.MYSQL_PORT = int(os.environ.get('MYSQL_PORT', '4000' if cls.IS_TIDB else '3306'))

        # Google OAuth (unchanged — OAuth works everywhere via redirect)
        cls.GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
        cls.GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')

        # Razorpay payment gateway
        cls.RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID', '')
        cls.RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET', '')

        # ZeptoMail email service
        cls.ZEPTOMAIL_TOKEN = os.environ.get('ZEPTOMAIL_TOKEN', '')

        # TiDB Cloud SSL — only needed when IS_TIDB=True
        # Local dev with MySQL: keep MYSQL_SSL = None
        if cls.IS_TIDB:
            import platform
            if platform.system() == 'Windows':
                # Windows dev: set TIDB_CA_PATH in .env pointing to your downloaded CA cert
                ca_path = os.environ.get('TIDB_CA_PATH', '')
                cls.MYSQL_SSL = {'ca': ca_path, 'verify_cert': True} if ca_path else {'verify_cert': False}
            else:
                # Linux / Cloudflare Containers: try multiple CA bundle locations
                ca_paths = [
                    '/etc/ssl/certs/ca-certificates.crt',      # Debian/Ubuntu
                    '/etc/pki/tls/certs/ca-bundle.crt',        # RHEL/CentOS
                    '/etc/ssl/cert.pem',                        # Alpine/macOS
                ]
                ca_found = None
                for ca_path in ca_paths:
                    if os.path.exists(ca_path):
                        ca_found = ca_path
                        break
                
                if ca_found:
                    cls.MYSQL_SSL = {'ca': ca_found, 'verify_cert': True}
                    logger.info(f"TiDB SSL: Using CA bundle at {ca_found}")
                else:
                    # No CA bundle found — connect without cert verification
                    # This still uses SSL encryption, just without CA verification
                    cls.MYSQL_SSL = {'verify_cert': False}
                    logger.warning("TiDB SSL: No CA bundle found — using SSL without cert verification")
        else:
            cls.MYSQL_SSL = None


    # ==========================================================================
    # 3. MYSQL DATABASE CONFIGURATION (Hardcoded - Safe to commit)
    # ==========================================================================

    # Note: Database names are hardcoded in SQL schema (creator_base, exam, admin_base)
    # and do not need to be configured here. They are referenced directly in SQL queries.

    # Connection Pool Settings (Budget Config: 1.3 vCPU, 1.3GB RAM)
    # NOTE: Flask-MySQLdb does NOT use connection pooling by default
    # These settings are reference values for understanding capacity
    # Current setup: containerConcurrency=200
    # With gevent: connections are shared across greenlets efficiently
    MYSQL_POOL_SIZE = 90 if IS_CLOUDFLARE else 10  # 90 connections per instance
    MYSQL_POOL_RECYCLE = 300  # 5 minutes (shorter to prevent stale connections)
    MYSQL_CONNECT_TIMEOUT = 8  # Faster timeout
    MYSQL_AUTOCOMMIT = False
    MYSQL_CURSORCLASS = 'DictCursor'
    MYSQL_POOL_OVERFLOW = 10  # Allow 10 additional connections when pool is full (90+10=100 max)
    MYSQL_POOL_TIMEOUT = 10  # Wait 10s for connection from pool

    # ==========================================================================
    # TiDB Cloud Settings
    # ==========================================================================
    # TiDB Cloud Serverless requires SSL/TLS connections.
    # When IS_DEVELOPMENT is false, the app automatically connects to TiDB Port 4000.
    # When IS_DEVELOPMENT is true, the app connects to Local MySQL Port 3306.
    # TiDB Host format: gateway01.us-east-1.prod.aws.tidbcloud.com
    # ==========================================================================
    IS_TIDB = not IS_DEVELOPMENT

    # SSL configuration for TiDB Cloud
    # On Linux (production/Cloudflare): use system CA bundle
    # On Windows (local dev with TiDB): set TIDB_CA_PATH in .env
    # Local MySQL dev: SSL is disabled by default (IS_TIDB=False)
    MYSQL_SSL = None  # Populated in _load_secrets()


    # ==========================================================================
    # 4. SESSION CONFIGURATION (Hardcoded - Safe to commit)
    # ==========================================================================

    # Session Cookie Security (automatically set based on environment)
    SESSION_COOKIE_SECURE = False  # Auto-overridden in __init__.py based on IS_CLOUDFLARE
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 86400  # 24 hours in seconds (increased from 6 hours)

    # CSRF Protection
    WTF_CSRF_TIME_LIMIT = 7920  # 2.2 hours in seconds (increased by 120% from 1 hour)

    # File Upload Limit
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB max file upload


    # ==========================================================================
    # 5. ENCRYPTION CONFIGURATION (Fernet — replaces Cloud KMS)
    # ==========================================================================
    # Cloudflare Containers uses Fernet symmetric encryption.
    # Store TOKEN_ENCRYPTION_KEY as a Cloudflare Workers Secret.
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # ==========================================================================

    # Kept for backward compatibility — KMS is disabled
    KMS_KEY_NAME = None

    @classmethod
    def should_use_kms(cls) -> bool:
        """KMS is disabled — Cloudflare uses Fernet encryption via TOKEN_ENCRYPTION_KEY."""
        return False

    @classmethod
    def kms_encrypt(cls, plaintext: str) -> str:
        """Delegates to Fernet (KMS removed)."""
        return cls._fernet_encrypt(plaintext)

    @classmethod
    def kms_decrypt(cls, ciphertext_b64: str) -> str:
        """Delegates to Fernet (KMS removed)."""
        return cls._fernet_decrypt(ciphertext_b64)

    @classmethod
    def _fernet_encrypt(cls, plaintext: str) -> str:
        """Encrypt data using Fernet symmetric encryption."""
        try:
            from cryptography.fernet import Fernet
            if not cls.TOKEN_ENCRYPTION_KEY:
                raise ValueError("TOKEN_ENCRYPTION_KEY not set for encryption")
            cipher = Fernet(cls.TOKEN_ENCRYPTION_KEY.encode())
            encrypted = cipher.encrypt(plaintext.encode())
            return encrypted.decode('utf-8')
        except Exception as e:
            logger.error(f"Fernet encryption failed: {e}")
            raise

    @classmethod
    def _fernet_decrypt(cls, ciphertext: str) -> str:
        """Decrypt data using Fernet symmetric encryption."""
        try:
            from cryptography.fernet import Fernet
            if not cls.TOKEN_ENCRYPTION_KEY:
                raise ValueError("TOKEN_ENCRYPTION_KEY not set for decryption")
            cipher = Fernet(cls.TOKEN_ENCRYPTION_KEY.encode())
            decrypted = cipher.decrypt(ciphertext.encode())
            return decrypted.decode('utf-8')
        except Exception as e:
            logger.error(f"Fernet decryption failed: {e}")
            raise


    # ==========================================================================
    # 6. CLOUDFLARE SECRETS (replaces Google Cloud Secret Manager)
    # ==========================================================================
    # All secrets are injected as plain environment variables by Cloudflare.
    # In Cloudflare dashboard: Settings > Environment Variables > Add as Secret
    # In local development: add to .env file
    # No GCP SDK, no file mounts, no gRPC — just os.environ.get().
    # ==========================================================================

    @staticmethod
    def get_config_value(env_var_name, secret_name=None, default=None, required=False):
        """
        Get configuration value from environment variables.

        In Cloudflare Containers: secrets are plain environment variables (Workers Secrets).
        In local development: reads from .env file via python-dotenv.
        No GCP SDK, no file mounts, no network calls.
        """
        env_value = os.environ.get(env_var_name)
        if env_value is not None and env_value != '':
            return env_value

        if default is not None:
            return default

        if required:
            raise ValueError(f"Required config '{env_var_name}' not found in environment variables")

        return None


    # ==========================================================================
    # 7. GOOGLE CLOUD STORAGE CONFIGURATION (Hardcoded - Safe to commit)
    # ==========================================================================
    # ==========================================================================

    # Cloudflare R2 Storage (replaces Google Cloud Storage)
    # R2 is S3-compatible with zero egress fees. Create bucket in CF dashboard.
    R2_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME', 'youcert-buc-main')
    R2_ENDPOINT_URL = os.environ.get('R2_ENDPOINT_URL', '')  # https://<account_id>.r2.cloudflarestorage.com
    R2_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID', '')
    R2_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY', '')
    R2_PUBLIC_URL = os.environ.get('R2_PUBLIC_URL', '')  # Optional custom public URL for bucket
    # Backward compatibility aliases — existing code using GCS_BUCKET_NAME still works
    BUCKET_NAME = R2_BUCKET_NAME
    GCS_BUCKET_NAME = R2_BUCKET_NAME


    # ==========================================================================
    # 8. CLOUDFLARE QUEUES CONFIGURATION
    # ==========================================================================
    # ==========================================================================

    # Cloudflare Queues (replaces Google Cloud Tasks)
    # Create queues in Cloudflare dashboard > Workers & Pages > Queues
    VIDEO_PROCESSING_QUEUE_ID = os.environ.get('VIDEO_PROCESSING_QUEUE_ID', '')
    CHUNK_GENERATION_QUEUE_ID = os.environ.get('CHUNK_GENERATION_QUEUE_ID', '')
    # Backward compatibility aliases
    VIDEO_PROCESSING_QUEUE = VIDEO_PROCESSING_QUEUE_ID
    CHUNK_GENERATION_QUEUE = CHUNK_GENERATION_QUEUE_ID
    CLOUD_TASKS_LOCATION = 'cloudflare'  # Kept for code compatibility

    # Service URLs
    SERVICE_URL = "http://127.0.0.1:5000" if FLASK_ENV == "development" else "https://www.youcert.com"
    SERVICE_URL_ALT = "http://127.0.0.1:5000" if FLASK_ENV == "development" else "https://youcert.com"
    # Kept for code compatibility
    CLOUD_RUN_SERVICE_URL = SERVICE_URL


    # ==========================================================================
    # 9. GEMINI AI CONFIGURATION
    # ==========================================================================

    # Gemini AI Configuration (direct REST API with API key — no Vertex AI SDK)
    # Get API key from: https://aistudio.google.com/app/apikey
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
    GEMINI_MODEL = 'gemini-2.5-flash-lite'
    # Backward compatibility aliases
    VERTEX_AI_MODEL = GEMINI_MODEL
    VERTEX_AI_LOCATION = 'us-central1'  # Kept for reference


    # ==========================================================================
    # 10. GOOGLE OAUTH CONFIGURATION
    # ==========================================================================
    # Will automatically use correct URL in production
    # Local: http://localhost:5000/oauth_callback
    # Production: https://www.youcert.com/oauth_callback

    # Note: This will be computed at runtime in __init__.py
    # For OAuth setup, use: Config.BASE_URL + '/oauth_callback'
    OAUTH_REDIRECT_URI = None  # Set dynamically in __init__.py based on BASE_URL


    # ==========================================================================
    # 11. EMAIL CONFIGURATION (Hardcoded - Safe to commit)
    # ==========================================================================

    # ZeptoMail Configuration
    ZEPTOMAIL_FROM = "noreply@youcert.com"
    ZEPTOMAIL_FROM_NAME = 'YOUCERT'

    # Communications Email (for admin mass emails)
    ZEPTOMAIL_COMMUNICATIONS_FROM = "noreply@youcert.com"
    ZEPTOMAIL_COMMUNICATIONS_FROM_NAME = 'YOUCERT'


    # ==========================================================================
    # 12. BUSINESS CONFIGURATION (Hardcoded - Safe to commit)
    # ==========================================================================

    PLATFORM_COMMISSION_PERCENTAGE = 25.0

    # Default exam price (in INR)
    DEFAULT_EXAM_PRICE = 269.00 #  269 default price for all exams 


    # ==========================================================================
    # 13. LOGGING CONFIGURATION (Hardcoded - Safe to commit)
    # ==========================================================================

    LOG_LEVEL = 'INFO'  # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL


    # ==========================================================================
    # 14. VALIDATION METHODS
    # ==========================================================================

    @classmethod
    def validate_required_env_vars(cls):
        """Validate that all required environment variables are set."""
        required = []

        # Flask session key
        if not cls.SECRET_KEY:
            required.append('SECRET_KEY')

        # Database
        if not cls.MYSQL_HOST:
            required.append('MYSQL_HOST')
        if not cls.MYSQL_USER:
            required.append('MYSQL_USER')

        # Fernet encryption (required in Cloudflare — no KMS)
        if not cls.TOKEN_ENCRYPTION_KEY:
            required.append('TOKEN_ENCRYPTION_KEY')

        # Google OAuth
        if not cls.GOOGLE_CLIENT_ID:
            required.append('GOOGLE_CLIENT_ID')
        if not cls.GOOGLE_CLIENT_SECRET:
            required.append('GOOGLE_CLIENT_SECRET')

        # Gemini AI API key
        if not cls.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not set — AI features will be disabled")

        if required:
            raise ValueError(f"Missing required environment variables: {', '.join(required)}")

        logger.info("All required environment variables validated")

    @classmethod
    def validate_configuration(cls):
        """Validate configuration consistency."""
        warnings = []

        # Check R2 Storage configuration
        if cls.R2_BUCKET_NAME and not cls.R2_ACCESS_KEY_ID:
            warnings.append("R2_BUCKET_NAME set but R2_ACCESS_KEY_ID missing")

        # Check Gemini API configuration
        if cls.IS_CLOUDFLARE and not cls.GEMINI_API_KEY:
            warnings.append("Running on Cloudflare but GEMINI_API_KEY not configured")

        # Check MySQL configuration
        if not cls.MYSQL_HOST:
            warnings.append("MYSQL_HOST not configured")

        return len(warnings) == 0, warnings

    @classmethod
    def print_configuration_status(cls):
        """
        Print current configuration status for debugging.

        SECURITY: This method does NOT print any secrets (passwords, tokens, keys).
        Only prints configuration settings and service status.
        """
        print("\n" + "=" * 70)
        print("YOUCERT CONFIGURATION STATUS")
        print("=" * 70)

        # Environment
        print(f"\nEnvironment: {'Cloudflare Containers (Production)' if cls.IS_CLOUDFLARE else 'Local Development'}")
        print(f"Gemini Model: {cls.GEMINI_MODEL}")

        # Cloudflare Services
        print("\nCloudflare Services:")
        print(f"  R2 Storage: {'[ENABLED] bucket=' + cls.R2_BUCKET_NAME if cls.R2_ACCESS_KEY_ID else '[DISABLED] (local storage)'}")
        print(f"  Queues: {'[ENABLED]' if cls.VIDEO_PROCESSING_QUEUE_ID else '[DISABLED] (sync mode)'}")
        print(f"  Secrets: [via env vars]")
        print(f"  Encryption: [Fernet] (KMS removed)")
        print(f"  Gemini AI: {'[ENABLED] model=' + cls.GEMINI_MODEL if cls.GEMINI_API_KEY else '[DISABLED - set GEMINI_API_KEY]'}")

        # Database (masked for security)
        print("\nDatabase:")
        print(f"  Type: MySQL")
        if cls.MYSQL_HOST:
            print(f"  Host: {cls.MYSQL_HOST}")
        if cls.MYSQL_UNIX_SOCKET:
            print(f"  Unix Socket: {cls.MYSQL_UNIX_SOCKET}")
        print(f"  User: {cls.MYSQL_USER}")
        print(f"  Password: {'[SET]' if cls.MYSQL_PASSWORD else '[NOT SET]'}")
        print(f"  Databases: creator_base, exam, admin_base")

        # Secrets Status (not the actual values)
        print("\nSecrets Status:")
        print(f"  SECRET_KEY: {'[SET]' if cls.SECRET_KEY else '[NOT SET]'}")
        print(f"  TOKEN_ENCRYPTION_KEY: {'[SET]' if cls.TOKEN_ENCRYPTION_KEY else '[NOT SET]'}")
        print(f"  GOOGLE_CLIENT_ID: {'[SET]' if cls.GOOGLE_CLIENT_ID else '[NOT SET]'}")
        print(f"  GOOGLE_CLIENT_SECRET: {'[SET]' if cls.GOOGLE_CLIENT_SECRET else '[NOT SET]'}")
        print(f"  RAZORPAY_KEY_ID: {'[SET]' if cls.RAZORPAY_KEY_ID else '[NOT SET]'}")
        print(f"  RAZORPAY_KEY_SECRET: {'[SET]' if cls.RAZORPAY_KEY_SECRET else '[NOT SET]'}")
        print(f"  ZEPTOMAIL_TOKEN: {'[SET]' if cls.ZEPTOMAIL_TOKEN else '[NOT SET]'}")

        # Session
        print("\nSession:")
        print(f"  Type: Client-side signed cookies")
        print(f"  Lifetime: {cls.PERMANENT_SESSION_LIFETIME // 3600} hours")
        print(f"  Secure: {cls.SESSION_COOKIE_SECURE}")
        print(f"  SameSite: {cls.SESSION_COOKIE_SAMESITE}")

        print("=" * 70 + "\n")


# ==============================================================================
# ENVIRONMENT-SPECIFIC CONFIGURATIONS
# ==============================================================================

class DevelopmentConfig(Config):
    """Development environment configuration (Windows/Mac/Linux)"""
    DEBUG = True
    FLASK_ENV = 'development'
    SESSION_COOKIE_SECURE = False  # HTTP allowed for localhost


class ProductionConfig(Config):
    """Production environment configuration (Cloudflare Containers)"""
    DEBUG = False
    FLASK_ENV = 'production'
    SESSION_COOKIE_SECURE = True  # HTTPS only
    SESSION_COOKIE_SAMESITE = 'Strict'  # Maximum CSRF protection


# Configuration selector
config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
}


def get_config(env_name='production'):
    """Get configuration object for environment"""
    return config_by_name.get(env_name, ProductionConfig)


# ==============================================================================
# INITIALIZATION & VALIDATION ON IMPORT
# ==============================================================================

# Load all secrets first (automatically handles underscore vs hyphen)
Config._load_secrets()

try:
    Config.validate_required_env_vars()

    is_valid, warnings = Config.validate_configuration()
    if warnings:
        print("\n" + "=" * 70)
        print("WARNING: CONFIGURATION WARNINGS:")
        print("=" * 70)
        for warning in warnings:
            print(f"   • {warning}")
        print("=" * 70 + "\n")
except ValueError as e:
    print(f"\nERROR: Configuration Error: {e}\n")
    print("Please check your .env file or environment variables.")
    print("See config.py comments for required variables.\n")
    # Only exit in production to avoid blocking development
    # Removed sys.exit(1) — we want the app to stay alive to serve /health and 503s
    # rather than crashing the entire container.
    pass


# ==============================================================================
# MODULE EXPORTS
# ==============================================================================

__all__ = [
    'Config',
    'DevelopmentConfig',
    'ProductionConfig',
    'get_config',
]
