import logging
import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from app.utils.logging_config import logger

import json

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

        # Log incoming request with troubleshooting details
        log_msg = f"{method} {path}"
        if query_string:
            log_msg += f"?{query_string}"
        log_msg += f" - IP: {client_ip}"
        if request.headers.get("user-agent"):
            log_msg += f" - UA: {request.headers.get('user-agent')[:50]}"

        logger.info(log_msg)

        # Troubleshooting: Log all request headers
        logger.debug(f"Request headers: {dict(request.headers)}")

        # Troubleshooting: Log POST data or other request parameters
        if method.upper() == "POST":
            # For POST requests, read the body now before it gets consumed
            try:
                body = await request.body()
                if body:
                    logger.debug(f"POST data: {body.decode('utf-8')}")
                else:
                    logger.debug("POST data: (empty)")

                # To allow downstream handlers to read the body again, we need to recreate the request
                # with the same body content. This is a bit complex but necessary for proper middleware behavior.
                from starlette.datastructures import UploadFile
                import io

                # Store the body for potential reuse if needed by downstream handlers
                request._body = body
            except:
                logger.debug("POST data: (could not read)")
        else:
            # For other methods, log query parameters immediately
            if query_string:
                logger.debug(f"Query parameters: {query_string}")
            else:
                logger.debug("Query parameters: (none)")

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

        # Get content length from response
        content_length = response.headers.get("content-length")
        if content_length is None:
            # For regular responses, try to get body length
            try:
                if hasattr(response, 'body') and response.body:
                    if isinstance(response.body, bytes):
                        content_length = len(response.body)
                    elif isinstance(response.body, str):
                        content_length = len(response.body.encode('utf-8'))
                    else:
                        content_length = len(str(response.body).encode('utf-8'))
                else:
                    content_length = 0
            except:
                content_length = "unknown"

        # Log response
        logger.info(
            f"{method} {path} - "
            f"Status: {response.status_code} - "
            f"Content-Length: {content_length} - "
            f"Duration: {process_time:.3f}s"
        )

        return response

