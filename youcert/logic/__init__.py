# youcert/logic/__init__.py
"""
Logic module for YOUCERT
Contains business logic, helpers, and task handlers

UPGRADED VERSION - Lazy Loading to Avoid Circular Imports:
- All imports are deferred until actually needed
- Prevents circular dependency with youcert/__init__.py
- Uses __getattr__ for transparent lazy loading
- Task handlers registered on first access
"""

# ============================================================================
# LAZY IMPORT FUNCTIONS (Internal - Not Exported)
# ============================================================================

def _lazy_import_video_processor():
    """Lazy import video processor"""
    from .video_processor import YouTubeProcessor, YouTubeTokenExpiredError
    return YouTubeProcessor, YouTubeTokenExpiredError


def _lazy_import_email_service():
    """Lazy import email service"""
    from .email_service import (
        email_service, 
        send_otp_email, 
        verify_otp_email,
        send_password_reset_email,
        send_admin_welcome_email,
        send_admin_rejection_email,
        send_creator_verification_success_email
    )
    return {
        'email_service': email_service,
        'send_otp_email': send_otp_email,
        'verify_otp_email': verify_otp_email,
        'send_password_reset_email': send_password_reset_email,
        'send_admin_welcome_email': send_admin_welcome_email,
        'send_admin_rejection_email': send_admin_rejection_email,
        'send_creator_verification_success_email': send_creator_verification_success_email,
    }


def _lazy_import_creator_earnings():
    """Lazy import creator earnings"""
    from .creator_earnings import CreatorEarningsCalculator
    return CreatorEarningsCalculator


def _lazy_import_chunk_generator():
    """Lazy import chunk generator"""
    from .chunk_generator import TranscriptChunker
    return TranscriptChunker


def _lazy_import_certificate_generator():
    """Lazy import certificate generator"""
    from .certificate_generator import generate_certificate
    return generate_certificate


def _lazy_import_task_manager():
    """Lazy import task manager"""
    from .task_manager import (
        TaskManager,
        task_handler,
        queue_video_processing,
        queue_chunk_generation
    )
    return {
        'TaskManager': TaskManager,
        'task_handler': task_handler,
        'queue_video_processing': queue_video_processing,
        'queue_chunk_generation': queue_chunk_generation,
    }


# ============================================================================
# TASK HANDLERS REGISTRATION (One-Time)
# ============================================================================

_task_handlers_registered = False

def _register_task_handlers():
    """Register task handlers once on first access"""
    global _task_handlers_registered
    if not _task_handlers_registered:
        try:
            from . import task_handlers  # noqa: F401
            _task_handlers_registered = True
        except ImportError:
            pass  # Task handlers optional


# ============================================================================
# LAZY MODULE ATTRIBUTE ACCESS
# ============================================================================

def __getattr__(name):
    """
    Lazy loading of submodules to avoid circular imports.
    
    This magic method is called when an attribute is accessed that doesn't exist.
    We use it to defer imports until they're actually needed.
    """
    
    # Video Processor
    if name == 'YouTubeProcessor':
        YouTubeProcessor, _ = _lazy_import_video_processor()
        globals()[name] = YouTubeProcessor
        return YouTubeProcessor
    
    elif name == 'YouTubeTokenExpiredError':
        _, YouTubeTokenExpiredError = _lazy_import_video_processor()
        globals()[name] = YouTubeTokenExpiredError
        return YouTubeTokenExpiredError
    
    # Email Service
    elif name in ['email_service', 'send_otp_email', 'verify_otp_email',
                  'send_password_reset_email', 'send_admin_welcome_email',
                  'send_admin_rejection_email', 'send_creator_verification_success_email']:
        email_exports = _lazy_import_email_service()
        result = email_exports[name]
        globals()[name] = result
        return result
    
    # Creator Earnings
    elif name == 'CreatorEarningsCalculator':
        CreatorEarningsCalculator = _lazy_import_creator_earnings()
        globals()[name] = CreatorEarningsCalculator
        return CreatorEarningsCalculator
    
    # Chunk Generator
    elif name == 'TranscriptChunker':
        TranscriptChunker = _lazy_import_chunk_generator()
        globals()[name] = TranscriptChunker
        return TranscriptChunker
    
    # Certificate Generator
    elif name == 'generate_certificate':
        generate_certificate = _lazy_import_certificate_generator()
        globals()[name] = generate_certificate
        return generate_certificate
    
    # Task Manager
    elif name in ['TaskManager', 'task_handler', 'queue_video_processing', 'queue_chunk_generation']:
        # Register task handlers on first task manager access
        _register_task_handlers()
        
        task_manager_exports = _lazy_import_task_manager()
        result = task_manager_exports[name]
        globals()[name] = result
        return result
    
    # Attribute not found
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


# ============================================================================
# MODULE EXPORTS
# ============================================================================

__all__ = [
    # Video Processing
    'YouTubeProcessor',
    'YouTubeTokenExpiredError',
    
    # Email Service
    'email_service',
    'send_otp_email',
    'verify_otp_email',
    'send_password_reset_email',
    'send_admin_welcome_email',
    'send_admin_rejection_email',
    'send_creator_verification_success_email',
    
    # Creator Earnings
    'CreatorEarningsCalculator',
    
    # Chunk Generator
    'TranscriptChunker',
    
    # Certificate Generator
    'generate_certificate',
    
    # Task Management
    'TaskManager',
    'task_handler',
    'queue_video_processing',
    'queue_chunk_generation',
]

