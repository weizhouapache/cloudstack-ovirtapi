from fastapi import FastAPI
from app.ovirtapi.router import router as ovirtapi_router
from app.security.certs import ensure_certificates
from app.security.auth_middleware import oVirtAPIAuthMiddleware
from app.config import SERVER

import uvicorn

PREFIX=SERVER.get("path", "/ovirt-engine/api")

cert_file, key_file = ensure_certificates()

app = FastAPI(
    title="CloudStack oVirtAPI Server",
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

app.add_middleware(oVirtAPIAuthMiddleware)

app.include_router(ovirtapi_router, prefix=PREFIX)

if __name__ == "__main__":
    host = SERVER.get("host", "0.0.0.0")
    port = int(SERVER.get("port", 8443))

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        ssl_certfile=cert_file,
        ssl_keyfile=key_file,
        log_level="info",
        reload=True
    )
