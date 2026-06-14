"""Production middleware: rate limiting, request logging, graceful shutdown."""

import asyncio
import json
import logging
import os
import signal
import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("ai_estimator")

# ── Rate Limiter ──────────────────────────────────────────────────────

def get_limiter():
    """Create rate limiter — uses Redis if available, else in-memory."""
    try:
        from slowapi import Limiter
        from slowapi.util import get_remote_address
        redis_url = os.getenv("REDIS_URL", "")
        storage_uri = redis_url if redis_url else "memory://"
        return Limiter(
            key_func=get_remote_address,
            default_limits=["60/minute"],
            storage_uri=storage_uri,
        )
    except ImportError:
        return None

limiter = get_limiter()


# ── Request Logging Middleware ────────────────────────────────────────

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Structured JSON logging for every HTTP request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        start = time.monotonic()
        response = None

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.monotonic() - start) * 1000)
            logger.error(json.dumps({
                "event": "request_error",
                "request_id": request_id,
                "method": request.method,
                "path": str(request.url.path),
                "duration_ms": duration_ms,
                "error": str(exc),
            }))
            raise

        duration_ms = round((time.monotonic() - start) * 1000)

        # Extract user_id from auth state if available
        user_id = getattr(request.state, "user_id", None)

        logger.info(json.dumps({
            "event": "request",
            "request_id": request_id,
            "method": request.method,
            "path": str(request.url.path),
            "status": response.status_code if response else 0,
            "duration_ms": duration_ms,
            "user_id": str(user_id) if user_id else None,
        }))

        if response:
            response.headers["x-request-id"] = request_id

        return response


# ── Graceful Shutdown ─────────────────────────────────────────────────

class GracefulShutdown:
    """Track in-flight requests and drain on SIGTERM."""

    def __init__(self, drain_timeout: float = 30.0):
        self._shutting_down = False
        self._in_flight = 0
        self._zero_event = asyncio.Event()
        self.drain_timeout = drain_timeout

    def install_signal_handlers(self, loop=None):
        loop = loop or asyncio.get_event_loop()

        def _handle_sigterm():
            if self._shutting_down:
                return
            self._shutting_down = True
            logger.info(json.dumps({
                "event": "sigterm_received",
                "in_flight": self._in_flight,
            }))

        try:
            loop.add_signal_handler(signal.SIGTERM, _handle_sigterm)
            loop.add_signal_handler(signal.SIGINT, _handle_sigterm)
        except NotImplementedError:
            # Windows / environments without signal support
            pass

    @property
    def shutting_down(self) -> bool:
        return self._shutting_down

    async def enter(self):
        if self._shutting_down:
            return False
        self._in_flight += 1
        return True

    async def exit(self):
        self._in_flight -= 1
        if self._shutting_down and self._in_flight == 0:
            self._zero_event.set()

    async def drain(self):
        """Wait for in-flight requests to complete or timeout."""
        if self._in_flight == 0:
            return
        logger.info(json.dumps({
            "event": "drain_start",
            "in_flight": self._in_flight,
            "timeout_s": self.drain_timeout,
        }))
        try:
            await asyncio.wait_for(self._zero_event.wait(), timeout=self.drain_timeout)
        except asyncio.TimeoutError:
            logger.warning(json.dumps({
                "event": "drain_timeout",
                "in_flight": self._in_flight,
            }))


shutdown_handler = GracefulShutdown()
