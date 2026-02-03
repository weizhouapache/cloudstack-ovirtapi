import os
import uuid
import subprocess
import configparser
from typing import Dict, List, Tuple
from fastapi import FastAPI, APIRouter, Request, Response, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn
import threading
from imageio.logging_imageio import setup_logging
from app.security.certs import ensure_certificates
from app.security.certs import get_default_ip
from imageio.config import IMAGEIO, SSL, LOGGING
from imageio.backup_service import backup_router, get_extents_with_context, get_extents_via_nbd, download_range, get_virtual_size, CHUNK_SIZE, finalize_backup_vm
from imageio.utils import check_internal_auth
from app.utils.response_builder import create_response
from app.utils.request_logging import RequestLoggingMiddleware


# Setup logging similar to main.py
logger = setup_logging()
logger.info("Starting oVirt ImageIO Server")


# Ensure certificates exist
cert_file, key_file, ca_cert_file = ensure_certificates()
logger.info(f"Using certificates: {cert_file}, {key_file}, CA: {ca_cert_file}")

# Get bind IP
bind_ip = IMAGEIO.get("host", "0.0.0.0")
public_ip = IMAGEIO.get("public_ip", "").strip()
if public_ip:
    bind_ip = public_ip
elif bind_ip == "0.0.0.0":
    bind_ip = get_default_ip()

INTERNAL_TOKEN = IMAGEIO.get("internal_token", None)

# =========================
# Shared in-memory registry
# =========================

transfers: Dict[str, dict] = {}

# Example transfer entry:
# transfers[transfer_id] = {
#     "file_path": "/data/disk1.qcow2",
#     "format": "qcow2" | "raw",
#     "mode": "download" | "upload",
# }

# =========================
# ImageIO Service (54322)
# =========================

api_prefix = IMAGEIO.get("path", "/images")

imageio_app = FastAPI(title="oVirt ImageIO Server")

imageio_app.add_middleware(RequestLoggingMiddleware)

imageio_router = APIRouter()

# ---- Create download transfer ----

@imageio_router.post("/internal/download")
def create_download_transfer(payload: dict, request: Request):
    """
    payload example:
    {
        "id": "disk-1",
        "path": "/data/disk1.qcow2",
        "format": "qcow2",
        "vm_name": "vm-1",
        "backup_id": "backup-1"
    }
    """

    # Check internal authentication for download
    if not check_internal_auth(request, INTERNAL_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid internal token")

    file_path = payload["path"]
    fmt = payload.get("format", "raw")
    volume_id = payload.get("id", None)
    backup_id = payload.get("backup_id", None)
    vm_name = payload.get("vm_name", None)

    if not os.path.exists(file_path):
        raise HTTPException(404, "Disk not found")

    transfer_id = str(uuid.uuid4())

    transfers[transfer_id] = {
        "file_path": file_path,
        "format": fmt,
        "vm_name": vm_name,
        "volume_id": volume_id,
        "backup_id": backup_id,     # For backups only
        "mode": "download"
    }

    return {
        "id": transfer_id,
        "transfer_host_ip": bind_ip,
        "transfer_url": f"https://{bind_ip}:54322/images/{transfer_id}",
        "extents_url": f"https://{bind_ip}:54322/images/{transfer_id}/extents"
    }

# ---- Create upload transfer ----

@imageio_router.post("/internal/upload")
def create_upload_transfer(payload: dict, request: Request):
    """
    payload example:
    {
        "path": "/data/restore.qcow2",
        "format": "qcow2",
        "size": 10737418240
    }
    """
    # Check internal authentication for upload
    if not check_internal_auth(request, INTERNAL_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid internal token")

    file_path = payload["path"]
    fmt = payload.get("format", "raw")

    transfer_id = str(uuid.uuid4())

    # Pre-create file
    size = payload.get("size")
    if size and fmt == "raw":
        with open(file_path, "wb") as f:
            f.truncate(size)
    elif fmt == "qcow2":
        with open(file_path, "wb") as f:
            f.truncate(0)

    transfers[transfer_id] = {
        "file_path": file_path,
        "format": fmt,
        "mode": "upload"
    }

    return {
        "id": transfer_id,
        "transfer_host_ip": bind_ip,
        "transfer_url": f"https://{bind_ip}:54322/images/{transfer_id}",
    }

# ---- Finalize backup ----

@imageio_router.post("/internal/backup/{vm}/finalize")
def finalize_backup(vm: str, request: Request):
    # Check internal authentication
    if not check_internal_auth(request, INTERNAL_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid internal token")

    return finalize_backup_vm(vm)

# ---- EXTENTS endpoint ----

@imageio_router.get("/{transfer_id}/extents")
def get_extents(transfer_id: str, request: Request, context: str = "zero"):
    t = transfers.get(transfer_id)
    if not t or t["mode"] != "download":
        raise HTTPException(404)

    vm_name = t.get("vm_name")
    volume_id = t.get("volume_id")
    backup_id = t.get("backup_id")

    if not backup_id and t["format"] == "raw":
        # full backup of volume for raw
        size = os.path.getsize(t["file_path"])
        # default to zero context
        extents_response = {
            "extents": [
                {"start": 0, "length": size, "zero": False, "hole": False}
            ]
        }
        return create_response(request, "extents", extents_response)

    if not backup_id and t["format"] == "qcow2":
        # full backup of volume for qcow2
        extents = get_extents_via_nbd(t["file_path"], context)
        extents_response = {"extents": extents}
        return create_response(request, "extents", extents_response)

    # the rest is for backups
    return get_extents_with_context(vm_name, t["file_path"], request, context)


# ---- DOWNLOAD with Range support ----

@imageio_router.get("/{transfer_id}")
def download_transfer(transfer_id: str, request: Request):
    t = transfers.get(transfer_id)
    if not t or t["mode"] != "download":
        raise HTTPException(404)

    vm_name = t.get("vm_name")
    file_path = t["file_path"]
    #file_size = os.path.getsize(file_path)
    file_size = get_virtual_size(file_path)

    return download_range(vm_name, file_path, request)

# ---- UPLOAD / RESTORE (PUT with Range) ----

@imageio_router.put("/{transfer_id}")
async def upload_transfer(transfer_id: str, request: Request):
    t = transfers.get(transfer_id)
    if not t or t["mode"] != "upload":
        raise HTTPException(404)

    file_path = t["file_path"]
    logger.info(f"Uploading to file {file_path}")

    range_header = request.headers.get("content-range")
    if not range_header:
        with open(file_path, "r+b") as f:
            async for chunk in request.stream():
                if not chunk:
                    continue
                f.write(chunk)

    else:
        # Example: bytes 2097152-2162687/3758096384
        _, range_part = range_header.split(" ")
        range_and_size = range_part.split("/")
        range_only = range_and_size[0]  # This will be "2097152-2162687"
        start_s, end_s = range_only.split("-")
        start = int(start_s)
        end = int(end_s)

        with open(file_path, "r+b") as f:
            f.seek(start)
            async for chunk in request.stream():
                if not chunk:
                    continue
                f.write(chunk)

    return Response(status_code=204)

# ---- OPTIONS ----

@imageio_router.options("/{transfer_id}")
async def options_imageio(transfer_id: str, request: Request):
    """
    OPTIONS method for individual imagetransfer endpoint.
    Returns capabilities information for ovirt-imageio-client compatibility.
    """
    capabilities = {
        "unix_socket": "\u0000/org/ovirt/imageio",
        "features": ["extents", "zero", "flush"],
        "max_readers": 8,
        "max_writers": 8
    }
    return JSONResponse(content=capabilities, status_code=200)

@imageio_router.patch("/{transfer_id}")
async def patch_imageio(transfer_id: str, request: Request):
    # get data from request
    data = await request.json()
    logger.info(f"Patching tranfer {transfer_id} with data: {data}")

    return Response(status_code=200)


# =========================
# Run ImageIO Service
# =========================

imageio_app.include_router(imageio_router, prefix=api_prefix)
imageio_app.include_router(backup_router, prefix=api_prefix)

for route in imageio_app.routes:
    logger.info(f"{route.path}  ->  {route.methods}")

if __name__ == "__main__":
    uvicorn.run(
        "imageio.service:imageio_app",
        host=IMAGEIO.get("listen_host"),
        port=int(IMAGEIO.get("listen_port")),
        ssl_keyfile=key_file,
        ssl_certfile=cert_file,
        log_level="info",
        reload=True
    )
