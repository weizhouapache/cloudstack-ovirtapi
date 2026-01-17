from fastapi import FastAPI
from app.ovirtapi.router import router as ovirtapi_router
from app.security.certs import ensure_certificates
from app.security.auth_middleware import oVirtAPIAuthMiddleware
from app.utils.request_logging import RequestLoggingMiddleware
from app.config import SERVER
from app.utils.logging_config import setup_logging

import uvicorn
import logging

# Setup logging
logger = setup_logging()
logger.info("Starting CloudStack oVirtAPI Server")

cert_file, key_file = ensure_certificates()
logger.info(f"Using certificates: {cert_file}, {key_file}")

app = FastAPI(
    title="CloudStack oVirtAPI Server",
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

# PKI services don't require authentication - add BEFORE auth middleware
from app.ovirtapi.pki import router as pki_router
from app.ovirtapi.oauth import router as oauth_router

base_path = SERVER.get("path", "/ovirt-engine")

pki_prefix = base_path + "/services"
app.include_router(pki_router, prefix=pki_prefix)
logger.info(f"PKI router included with prefix: {pki_prefix}")

oauth_prefix = base_path + "/sso"
app.include_router(oauth_router, prefix=oauth_prefix)
logger.info(f"OAuth router included with prefix: {oauth_prefix}")

api_prefix = SERVER.get("path", "/ovirt-engine") + "/api"
app.include_router(ovirtapi_router, prefix=api_prefix)
logger.info(f"API Router included with prefix: {api_prefix}")

# Add middlewares for main API
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(oVirtAPIAuthMiddleware)

if __name__ == "__main__":
    host = SERVER.get("host", "0.0.0.0")
    port = int(SERVER.get("port", 443))

    logger.info(f"Starting server on {host}:{port}")

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        ssl_certfile=cert_file,
        ssl_keyfile=key_file,
        log_level="info",
        reload=True
    )
