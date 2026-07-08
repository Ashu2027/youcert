"""
task_manager.py - Cloudflare Queues Integration for YOUCERT

Dual-Mode Task Manager:
- LOCAL DEVELOPMENT: Executes tasks synchronously (no queue needed)
- CLOUDFLARE CONTAINERS: Dispatches tasks to Cloudflare Queues via REST API

The Cloudflare Queue consumer (a separate Worker script) receives messages and
POSTs them to the /internal/worker/* endpoints on this container.

Usage:
    from youcert.logic.task_manager import TaskManager

    TaskManager.queue_task(
        task_type='video_processing',
        payload={'video_id': 'abc123', 'channel_id': 'UC...'}
    )
"""

import json
import base64
import requests
from datetime import datetime
from typing import Dict, Any, Optional
from functools import wraps
from config import Config

# ============================================================================
# CENTRALIZED IMPORTS FROM YOUCERT
# ============================================================================

try:
    from youcert import secure_log
except ImportError:
    import logging
    def secure_log(message, level='info', **kwargs):
        logger = logging.getLogger(__name__)
        log_func = getattr(logger, level, logger.info)
        log_func(f"[TaskManager] {message}")


# ============================================================================
# ENVIRONMENT DETECTION
# ============================================================================

def is_cloudflare() -> bool:
    """Check if running in Cloudflare Containers (production)."""
    return Config.IS_CLOUDFLARE

# Backward compatibility alias
def is_cloud_run() -> bool:
    """Alias for is_cloudflare() — kept for backward compatibility."""
    return is_cloudflare()

def is_production() -> bool:
    """Check if running in production mode."""
    return is_cloudflare() or Config.FLASK_ENV == 'production'


# ============================================================================
# TASK CONFIGURATION
# ============================================================================

class TaskConfig:
    """
    Configuration for Cloudflare Queues and worker endpoint routing.

    Worker endpoints are internal HTTP endpoints in the same container:
    - /internal/worker/video_processing
    - /internal/worker/chunk_generation
    """

    # Cloudflare Queue IDs (set as env var via Cloudflare dashboard)
    QUEUES = {
        'video_processing': Config.VIDEO_PROCESSING_QUEUE_ID,
        'chunk_generation': Config.CHUNK_GENERATION_QUEUE_ID,
    }

    # Internal Worker Endpoints (protected, only called by CF Queues consumer)
    WORKER_ENDPOINTS = {
        'video_processing': '/internal/worker/video_processing',
        'chunk_generation': '/internal/worker/chunk_generation',
    }

    # Task Timeouts in seconds (informational — CF Queues has its own ack timeout)
    TIMEOUTS = {
        'video_processing': 1800,  # 30 minutes
        'chunk_generation': 1800,  # 30 minutes
    }

    @classmethod
    def get_queue_id(cls, task_type: str) -> str:
        """Get Cloudflare Queue ID for a given task type."""
        return cls.QUEUES.get(task_type, '')

    @classmethod
    def get_service_url(cls) -> str:
        """Get service base URL for internal task routing."""
        return Config.SERVICE_URL or ''


# ============================================================================
# TASK MANAGER CLASS
# ============================================================================

class TaskManager:
    """
    Unified Task Manager for local development and Cloudflare Containers.

    Local Development:
        Tasks execute synchronously in the same process — no queue needed.

    Cloudflare Containers (Production):
        Tasks are dispatched to Cloudflare Queues via REST API.
        A CF Worker consumer reads the queue and POSTs to /internal/worker/*.

    Uses centralized secure_log() for all logging.
    """

    # Registry of task handlers (populated by @task_handler decorator)
    _handlers: Dict[str, callable] = {}

    @classmethod
    def register_handler(cls, task_type: str, handler: callable):
        """Register a task handler function."""
        cls._handlers[task_type] = handler
        secure_log(f"Task handler registered: {task_type}", 'info')

    @classmethod
    def queue_task(
        cls,
        task_type: str,
        payload: Dict[str, Any],
        delay_seconds: int = 0,
        task_id: Optional[str] = None,
        channel_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Queue a task for execution.

        In production: dispatches to Cloudflare Queues via REST API.
        In development: executes the task synchronously in the same process.
        """
        try:
            if task_type not in TaskConfig.WORKER_ENDPOINTS:
                secure_log(f"Unknown task type requested: {task_type}", 'warning', channel_id=channel_id)
                return {'success': False, 'message': f"Unknown task type: {task_type}"}

            # Attach metadata to the payload
            payload['_task_type'] = task_type
            payload['_queued_at'] = datetime.utcnow().isoformat()
            payload['_environment'] = 'cloudflare' if is_cloudflare() else 'local'

            if is_cloudflare():
                return cls._queue_cloudflare_task(task_type, payload, delay_seconds, task_id, channel_id)
            else:
                return cls._execute_local_task(task_type, payload, channel_id)

        except Exception as e:
            secure_log(f"Error queuing task {task_type}: {e}", 'error', channel_id=channel_id)
            return {'success': False, 'message': f"Failed to queue task: {str(e)}"}

    @classmethod
    def _queue_cloudflare_task(
        cls,
        task_type: str,
        payload: Dict[str, Any],
        delay_seconds: int,
        task_id: Optional[str],
        channel_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Dispatch a task to Cloudflare Queues via REST API.

        CF Queues API endpoint:
            POST /accounts/{account_id}/queues/{queue_id}/messages
            Authorization: Bearer {api_token}

        Messages must be base64-encoded JSON per CF API spec.
        The CF Worker consumer decodes and POSTs to /internal/worker/<task_type>.
        """
        try:
            queue_id = TaskConfig.get_queue_id(task_type)
            account_id = Config.CLOUDFLARE_ACCOUNT_ID
            api_token = Config.CLOUDFLARE_API_TOKEN

            if not queue_id:
                secure_log(
                    f"No Cloudflare Queue ID configured for task type '{task_type}'. "
                    "Set VIDEO_PROCESSING_QUEUE_ID or CHUNK_GENERATION_QUEUE_ID.",
                    'warning', channel_id=channel_id
                )
                return cls._execute_local_task(task_type, payload, channel_id)

            if not account_id or not api_token:
                secure_log(
                    "Cloudflare credentials missing (CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN). "
                    "Falling back to local execution.",
                    'warning', channel_id=channel_id
                )
                return cls._execute_local_task(task_type, payload, channel_id)

            # Encode payload as base64 per CF Queues API requirement
            payload_json = json.dumps(payload)
            payload_b64 = base64.b64encode(payload_json.encode('utf-8')).decode('utf-8')

            api_url = (
                f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
                f"/queues/{queue_id}/messages"
            )

            response = requests.post(
                api_url,
                headers={
                    'Authorization': f'Bearer {api_token}',
                    'Content-Type': 'application/json',
                },
                json={
                    'messages': [
                        {
                            'body': payload_b64,
                            'delay_seconds': delay_seconds if delay_seconds > 0 else 0,
                        }
                    ]
                },
                timeout=10
            )
            response.raise_for_status()

            result = response.json()
            successful = result.get('result', {}).get('successful', 0)

            secure_log(
                f"Cloudflare Queue task enqueued: {task_type}",
                'info',
                channel_id=channel_id,
                context={'queue_id': queue_id, 'success_count': successful}
            )

            return {
                'success': True,
                'message': 'Task queued to Cloudflare Queues',
                'queue_id': queue_id,
                'execution_mode': 'cloudflare_queues'
            }

        except requests.exceptions.HTTPError as e:
            secure_log(
                f"Cloudflare Queues API HTTP error for {task_type}: {e.response.status_code} {e.response.text}",
                'error', channel_id=channel_id
            )
            secure_log("Falling back to local execution", 'warning', channel_id=channel_id)
            return cls._execute_local_task(task_type, payload, channel_id)

        except requests.exceptions.Timeout:
            secure_log(f"Cloudflare Queues API timeout for {task_type}", 'error', channel_id=channel_id)
            secure_log("Falling back to local execution", 'warning', channel_id=channel_id)
            return cls._execute_local_task(task_type, payload, channel_id)

        except Exception as e:
            secure_log(f"Unexpected error enqueuing to Cloudflare Queues ({task_type}): {e}", 'error', channel_id=channel_id)
            secure_log("Falling back to local execution", 'warning', channel_id=channel_id)
            return cls._execute_local_task(task_type, payload, channel_id)

    @classmethod
    def _execute_local_task(
        cls,
        task_type: str,
        payload: Dict[str, Any],
        channel_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute task locally (synchronous — for development only)."""
        try:
            handler = cls._handlers.get(task_type)
            if not handler:
                secure_log(f"No handler registered for task type: {task_type}", 'error', channel_id=channel_id)
                return {'success': False, 'message': f"No handler for task type: {task_type}"}

            secure_log(f"Executing task locally: {task_type}", 'info', channel_id=channel_id)
            result = handler(payload)
            secure_log(f"Local task completed: {task_type}", 'info', channel_id=channel_id)

            return {
                'success': True,
                'message': 'Task executed locally',
                'result': result,
                'execution_mode': 'local_sync'
            }

        except Exception as e:
            secure_log(f"Local task execution error ({task_type}): {e}", 'error', channel_id=channel_id)
            return {
                'success': False,
                'message': f"Task execution failed: {str(e)}",
                'execution_mode': 'local_sync'
            }


# ============================================================================
# DECORATOR FOR TASK HANDLERS
# ============================================================================

def task_handler(task_type: str):
    """Decorator to register a function as a task handler."""
    def decorator(func):
        @wraps(func)
        def wrapper(payload):
            channel_id = payload.get('channel_id')
            secure_log(f"Task handler starting: {task_type}", 'info', channel_id=channel_id)
            try:
                result = func(payload)
                secure_log(f"Task handler completed: {task_type}", 'info', channel_id=channel_id)
                return result
            except Exception as e:
                secure_log(f"Task handler failed ({task_type}): {e}", 'error', channel_id=channel_id)
                raise

        TaskManager.register_handler(task_type, wrapper)
        return wrapper

    return decorator


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def queue_video_processing(
    video_id: str,
    channel_id: str,
    url: str,
    credentials_json: str,
    openai_api_key: str
) -> Dict[str, Any]:
    """Queue a video processing task."""
    return TaskManager.queue_task(
        task_type='video_processing',
        payload={
            'video_id': video_id,
            'channel_id': channel_id,
            'url': url,
            'credentials_json': credentials_json,
            'openai_api_key': openai_api_key,
        },
        channel_id=channel_id
    )


def queue_chunk_generation(
    content_id: str,
    content_type: str,
    channel_id: str,
    text_path: str
) -> Dict[str, Any]:
    """Queue a text chunking task."""
    return TaskManager.queue_task(
        task_type='chunk_generation',
        payload={
            'content_id': content_id,
            'content_type': content_type,
            'channel_id': channel_id,
            'text_path': text_path,
        },
        channel_id=channel_id
    )
