
    # Register both User and Creator Service routes
from .user_routes import user_bp
from .creator_routes import creator_bp
from .admin_routes import admin_bp
from .public_routes import public_bp
from .worker_routes import worker_bp  # for Cloudflare Queues worker endpoints

__all__ = ['creator_bp', 'user_bp', 'admin_bp', 'public_bp', 'worker_bp']

