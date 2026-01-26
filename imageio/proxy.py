
import os
import uuid
import subprocess
import logging
import configparser
from typing import Dict, List, Tuple
from fastapi import FastAPI, APIRouter, Request, Response, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn
import threading
from imageio.logging import setup_logging
from app.security.certs import ensure_certificates
from app.security.certs import get_default_ip
from imageio.config import PROXY, SSL, LOGGING


# Setup logging similar to main.py
logger = setup_logging()
logger.info("Starting oVirt ImageIO Proxy")

# Ensure certificates exist
cert_file, key_file, ca_cert_file = ensure_certificates()
logger.info(f"Using certificates: {cert_file}, {key_file}, CA: {ca_cert_file}")

# Get bind IP
bind_ip = PROXY.get("proxy_listen_host", "0.0.0.0")
public_ip = PROXY.get("proxy_public_ip", "").strip()
if public_ip:
    bind_ip = public_ip
elif bind_ip == "0.0.0.0":
    bind_ip = get_default_ip()

bind_port = PROXY.get("proxy_listen_port", 54323)

# Import the internal token
INTERNAL_TOKEN = PROXY.get("proxy_internal_token", None)

# =========================
# Proxy Service (54323)
# =========================

proxy_app = FastAPI(title="oVirt ImageIO Proxy")

@proxy_app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
def proxy(path: str, request: Request):
    """
    Very simple proxy: forwards everything to 54322.
    In real oVirt, this handles host-network isolation.
    """
    import requests

    url = f"https://localhost:54322/{path}"

    headers = dict(request.headers)
    headers.pop("host", None)

    resp = requests.request(
        method=request.method,
        url=url,
        headers=headers,
        data=request.stream(),
        verify=False
    )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=dict(resp.headers),
    )

def run_proxy():
    uvicorn.run(
        proxy_app,
        host=bind_ip,
        port=bind_port,
        ssl_keyfile="server.key",
        ssl_certfile="server.crt",
    )

if __name__ == "__main__":
    t2 = threading.Thread(target=run_proxy)
    t2.start()
    t2.join()
