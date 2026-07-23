import logging
import re
from time import perf_counter
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.settings import Settings


logger = logging.getLogger("app.http")
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class PrivacySafeRequestMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        supplied_request_id = request.headers.get("x-request-id", "")
        request_id = (
            supplied_request_id
            if SAFE_REQUEST_ID.fullmatch(supplied_request_id)
            else uuid4().hex
        )
        request.state.request_id = request_id
        started = perf_counter()
        log_fields = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
        }
        try:
            response = await call_next(request)
        except Exception:
            logger.error(
                "http.request.failed",
                extra={
                    **log_fields,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                    "status_code": 500,
                },
                exc_info=True,
            )
            raise
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith(("/api/", "/webhooks/")):
            response.headers["Cache-Control"] = "no-store"
            if not request.url.path.startswith("/api/docs"):
                response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if self._settings.app_env in {"staging", "production"}:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        level = logging.DEBUG if request.url.path == "/api/v1/health/live" else logging.INFO
        logger.log(
            level,
            "http.request.completed",
            extra={
                **log_fields,
                "duration_ms": round((perf_counter() - started) * 1000, 2),
                "status_code": response.status_code,
            },
        )
        return response
