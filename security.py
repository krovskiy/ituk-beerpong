import secrets
import time
from collections import deque
from threading import Lock

from fastapi import Header, HTTPException, Request
from starlette.responses import JSONResponse
from starlette.datastructures import MutableHeaders

import config


attempts = {}
attempts_lock = Lock()


def check_rate_limit(request, category, limit):
    # Use the direct client address. Untrusted forwarding headers are ignored.
    address = request.client.host
    key = (address, category)
    now = time.monotonic()
    cutoff = now - config.RATE_LIMIT_WINDOW
    with attempts_lock:
        expired = []
        for saved_key, timestamps in attempts.items():
            if timestamps[-1] <= cutoff:
                expired.append(saved_key)
        for saved_key in expired:
            del attempts[saved_key]

        if key not in attempts:
            if len(attempts) >= config.RATE_LIMIT_MAX_CLIENTS:
                raise HTTPException(429, "Server is busy. Please try again shortly.")
            attempts[key] = deque()

        timestamps = attempts[key]
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()
        if len(timestamps) >= limit:
            retry_after = max(1, int(timestamps[0] + config.RATE_LIMIT_WINDOW - now) + 1)
            raise HTTPException(429, "Too many attempts. Try again shortly.", headers={"Retry-After": str(retry_after)})
        timestamps.append(now)


def require_organizer(request: Request, x_organizer_key: str = Header(default="")):
    if not config.ORGANIZER_KEY:
        raise HTTPException(503, "Organizer access has not been configured.")
    # Only failed credentials count towards this limit. Normal match updates do not.
    if not secrets.compare_digest(x_organizer_key.encode(), config.ORGANIZER_KEY.encode()):
        check_rate_limit(request, "admin", config.ADMIN_RATE_LIMIT)
        raise HTTPException(403, "The organizer key is incorrect.")


class RequestProtection:
    """Apply small request limits before FastAPI parses uploads or JSON."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        if request.method == "POST" and request.url.path in ["/api/teams", "/api/waitlist"]:
            try:
                check_rate_limit(request, "registration", config.REGISTRATION_RATE_LIMIT)
            except HTTPException as error:
                response = JSONResponse({"detail": error.detail}, status_code=error.status_code, headers=error.headers)
                await response(scope, receive, send)
                return
        if request.method in ["POST", "PUT", "PATCH", "DELETE"]:
            origin = request.headers.get("origin")
            if origin is not None and origin not in config.ALLOWED_ORIGINS:
                response = JSONResponse({"detail": "This origin is not allowed."}, status_code=403)
                await response(scope, receive, send)
                return

            # Count streamed bytes too, so omitting Content-Length cannot bypass the limit.
            length = request.headers.get("content-length")
            if length is not None and (not length.isdecimal() or int(length) > config.REQUEST_MAX_BYTES):
                response = JSONResponse({"detail": "The request is too large."}, status_code=413)
                await response(scope, receive, send)
                return
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > config.REQUEST_MAX_BYTES:
                    response = JSONResponse({"detail": "The request is too large."}, status_code=413)
                    await response(scope, receive, send)
                    return
                if not message.get("more_body", False):
                    break

            body_delivered = False

            async def receive_body():
                nonlocal body_delivered
                if not body_delivered:
                    body_delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            await self.app(scope, receive_body, send)
            return
        await self.app(scope, receive, send)


class SecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                headers["Content-Security-Policy"] = (
                    "default-src 'self'; script-src 'self'; style-src 'self'; "
                    "img-src 'self' blob:; font-src 'self'; connect-src 'self'; "
                    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
                )
                if scope.get("path", "").startswith(("/api/", "/admin")):
                    headers["Cache-Control"] = "no-store"
                if scope.get("path", "").startswith("/admin"):
                    headers["X-Robots-Tag"] = "noindex, nofollow"
            await send(message)

        await self.app(scope, receive, send_with_headers)
