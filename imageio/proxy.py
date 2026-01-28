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
import httpx
from imageio.utils import check_internal_auth

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
# Shared in-memory registry for tracking transfer types and IPs
# =========================

transfer_types: Dict[str, str] = {}  # Maps transfer_id to "imageio" or "backup"
transfer_host_ips: Dict[str, str] = {}  # Maps transfer_id to target IP


# =========================
# Proxy Service (54323)
# =========================

proxy_app = FastAPI(title="oVirt ImageIO Proxy")

proxy_router = APIRouter()


def determine_target_host(transfer_id: str) -> Tuple[str, str]:
    """
    Determine which service should handle the request based on transfer_id or path.
    Returns tuple of (base_url, service_type)
    """
    # Check if we already know the service type for this transfer_id
    if transfer_id in transfer_host_ips:
        target_ip = transfer_host_ips.get(transfer_id, "localhost")
        return target_ip
    else:
        raise HTTPException(404, "Transfer ID not found")

@proxy_router.get("/{transfer_id}")
async def proxy_get(transfer_id: str, request: Request):
    """
    Proxy GET requests to appropriate service based on transfer_id
    """

    # Determine target host by transfer_id
    target_host_ip = determine_target_host(transfer_id)
    # get the path from request
    path = request.url.path.split("/images/", 1)[-1].split("/", 1)[0] if "/images/" in request.url.path else ""
    # replace path with actual target host
    new_url = f"https://{target_host_ip}:54322/images/{path}"
    
    headers = dict(request.headers)

    # Forward to target host
    async with httpx.AsyncClient(verify=False) as client:
        headers = headers
        response = await client.get(
            url=new_url,
            headers=headers
        )
        if response.status_code == 200:
            return response
        else:
            raise HTTPException(status_code=400, detail="Cannot get data")

@proxy_router.get("/{transfer_id}/extents")
async def proxy_get_extents(transfer_id: str, request: Request):
    """
    Proxy extents requests to appropriate service based on transfer_id
    """
   
    # Determine target host by transfer_id
    target_host_ip = determine_target_host(transfer_id)
    # get the path from request
    path = request.url.path.split("/images/", 1)[-1].split("/", 1)[0] if "/images/" in request.url.path else ""
    # replace path with actual target host
    new_url = f"https://{target_host_ip}:54322/images/{path}"
    
    headers = dict(request.headers)

    # Forward to target host
    async with httpx.AsyncClient(verify=False) as client:
        headers = headers
        response = await client.get(
            url=new_url,
            headers=headers
        )
        if response.status_code == 200:
            return response
        else:
            raise HTTPException(status_code=400, detail="Cannot get extents")
@proxy_router.put("/{transfer_id}")
async def proxy_put(transfer_id: str, request: Request):
    """
    Proxy PUT requests to appropriate service based on transfer_id
    """
    # Determine target host by transfer_id
    target_host_ip = determine_target_host(transfer_id)
    # get the path from request
    path = request.url.path.split("/images/", 1)[-1].split("/", 1)[0] if "/images/" in request.url.path else ""
    # replace path with actual target host
    new_url = f"https://{target_host_ip}:54322/images/{path}"
    
    headers = dict(request.headers)

    # Forward to target host
    async with httpx.AsyncClient(verify=False) as client:
        headers = headers
        response = await client.put(
            url=new_url,
            stream=request.stream(),
            headers=headers
        )
        if response.status_code == 200:
            return response
        else:
            raise HTTPException(status_code=400, detail="Cannot put data")

@proxy_router.options("/{transfer_id}")
async def proxy_options(transfer_id: str, request: Request):
    """
    Proxy OPTIONS requests to appropriate service based on transfer_id
    """
    # Determine target host by transfer_id
    target_host_ip = determine_target_host(transfer_id)
    # get the path from request
    path = request.url.path.split("/images/", 1)[-1].split("/", 1)[0] if "/images/" in request.url.path else ""
    # replace path with actual target host
    new_url = f"https://{target_host_ip}:54322/images/{path}"
    
    headers = dict(request.headers)

    # Forward to target host
    async with httpx.AsyncClient(verify=False) as client:
        headers = headers
        response = await client.options(
            url=new_url,
            headers=headers
        )
        if response.status_code == 200:
            return response
        else:
            raise HTTPException(status_code=400, detail="Cannot get options")

@proxy_router.post("/internal/store_transfer")
def store_transfer(request: Request):

    # Check internal authentication for store transfer
    if not check_internal_auth(request, INTERNAL_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid internal token")

    # Get 
    transfer_id = request.headers.get("transfer_id")
    transfer_host_ip = request.headers.get("transfer_host_ip")
    transfer_host_ips.update({transfer_id: transfer_host_ip})

    return Response(status_code=200)

# =========================
# Run ImageIO Proxy
# =========================

proxy_app.include_router(proxy_router, prefix="/images")

for route in proxy_app.routes:
    logger.info(f"{route.path}  ->  {route.methods}")

if __name__ == "__main__":
    uvicorn.run(
        "imageio.proxy:proxy_app",
        host=bind_ip,
        port=int(bind_port),
        ssl_keyfile=key_file,
        ssl_certfile=cert_file,
        log_level="info",
        reload=True
    )
