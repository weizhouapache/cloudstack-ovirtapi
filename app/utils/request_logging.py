import logging
import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Get client IP (handles proxies)
        client_ip = request.client.host if request.client else "unknown"
        if x_forwarded_for := request.headers.get("x-forwarded-for"):
            client_ip = x_forwarded_for.split(",")[0].strip()
        
        # Build request details
        method = request.method
        path = request.url.path
        query_string = str(request.url.query) if request.url.query else None
        full_url = str(request.url)
        
        # Log incoming request
        log_msg = f"{method} {path}"
        if query_string:
            log_msg += f"?{query_string}"
        log_msg += f" - IP: {client_ip}"
        if request.headers.get("user-agent"):
            log_msg += f" - UA: {request.headers.get('user-agent')[:50]}"
        
        logger.info(log_msg)
        
        # Measure response time
        start_time = time.time()
        try:
            response = await call_next(request)
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(
                f"{method} {path} - "
                f"Error: {type(e).__name__} - "
                f"Duration: {process_time:.3f}s"
            )
            raise
        
        process_time = time.time() - start_time
        
        # Log response
        logger.info(
            f"{method} {path} - "
            f"Status: {response.status_code} - "
            f"Duration: {process_time:.3f}s"
        )
        
        return response

