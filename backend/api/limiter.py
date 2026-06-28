"""
limiter.py
==========
Singleton Flask-Limiter instance.

Defined here (not in main.py) to avoid circular imports — auth.py needs
the limiter for rate-limit decorators, and main.py imports auth.py, so
having limiter in main.py creates a circular dependency under Gunicorn.

Set TESTING=true in the environment to disable rate limiting (e.g. local dev).

Usage
-----
    # in main.py
    from api.limiter import limiter
    limiter.init_app(app)

    # in auth.py
    from api.limiter import limiter
    @limiter.limit("5 per hour")
"""

import os

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],        # no global limit — applied per endpoint only
    storage_uri="memory://",  # single-process; swap to Redis for multi-worker
    enabled=os.environ.get("TESTING") != "true",
)