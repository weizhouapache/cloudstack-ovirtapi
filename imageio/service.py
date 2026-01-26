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
from imageio.config import IMAGEIO, SSL, LOGGING

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

# Import the internal token
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
# Utilities
# =========================

def parse_single_range(range_header: str, file_size: int) -> Tuple[int, int]:
    unit, rng = range_header.split("=")
    start_s, end_s = rng.split("-")
    start = int(start_s)
    end = int(end_s) if end_s else file_size - 1
    if start >= file_size:
        raise HTTPException(status_code=416, detail="Range Not Satisfiable")
    end = min(end, file_size - 1)
    return start, end

def parse_multi_range(range_header: str) -> List[Tuple[int, int]]:
    unit, ranges = range_header.split("=")
    result = []
    for part in ranges.split(","):
        s, e = part.split("-")
        result.append((int(s), int(e)))
    return result

def iter_file(f, length, chunk_size=1024 * 1024):
    remaining = length
    while remaining > 0:
        size = min(chunk_size, remaining)
        data = f.read(size)
        if not data:
            break
        remaining -= len(data)
        yield data

# =========================
# Authentication middleware
# =========================

def check_internal_auth(request: Request) -> bool:
    """
    Check if the request contains the correct internal token in the Authorization header
    """
    if not INTERNAL_TOKEN:
        # If no internal token is configured, skip authentication
        return True

    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return False

    # Check if the header matches the internal token
    return auth_header.strip() == INTERNAL_TOKEN

# =========================
# EXTENTS (qcow2 incremental)
# =========================

def get_qcow2_extents(file_path: str):
    """
    Uses: qemu-img map --output=json
    Returns list of (start, length) for allocated clusters.
    """
    cmd = ["qemu-img", "map", "--output=json", file_path]
    out = subprocess.check_output(cmd)
    import json
    data = json.loads(out)

    extents = []
    for e in data:
        if e.get("data", False):  # allocated
            extents.append({
                "start": e["start"],
                "length": e["length"]
            })
    return extents

# =========================
# ImageIO Service (54322)
# =========================

api_prefix = IMAGEIO.get("path", "/images")

imageio_app = FastAPI(title="oVirt ImageIO Server")

imageio_router = APIRouter()

# ---- Create download transfer ----

@imageio_router.post("/download")
def create_download_transfer(payload: dict, request: Request):
    """
    payload example:
    {
        "id": "disk-1",
        "path": "/data/disk1.qcow2",
        "format": "qcow2"
    }
    """

    # Check internal authentication for download
    if not check_internal_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid internal token")

    file_path = payload["path"]
    fmt = payload.get("format", "raw")

    if not os.path.exists(file_path):
        raise HTTPException(404, "Disk not found")

    transfer_id = str(uuid.uuid4())

    transfers[transfer_id] = {
        "file_path": file_path,
        "format": fmt,
        "mode": "download"
    }

    return {
        "id": transfer_id,
        "transfer_url": f"https://{bind_ip}:54322/images/{transfer_id}",
        "proxy_url": f"https://{bind_ip}:54323/images/{transfer_id}",
        "extents_url": f"https://{bind_ip}:54322/images/{transfer_id}/extents"
    }

# ---- Create upload transfer ----

@imageio_router.post("/upload")
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
    if not check_internal_auth(request):
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
        "transfer_url": f"https://{bind_ip}:54322/images/{transfer_id}",
        "proxy_url": f"https://{bind_ip}:54323/images/{transfer_id}"
    }

# ---- EXTENTS endpoint ----

@imageio_router.get("/{transfer_id}/extents")
def get_extents(transfer_id: str, request: Request):
    t = transfers.get(transfer_id)
    if not t:
        raise HTTPException(404)

    if t["format"] != "qcow2":
        # Raw -> full backup: single extent
        size = os.path.getsize(t["file_path"])
        return {
            "extents": [
                {"start": 0, "length": size}
            ]
        }

    extents = get_qcow2_extents(t["file_path"])
    return {"extents": extents}

# ---- DOWNLOAD with Range support ----

@imageio_router.get("/{transfer_id}")
def download_transfer(transfer_id: str, request: Request):
    t = transfers.get(transfer_id)
    if not t or t["mode"] != "download":
        raise HTTPException(404)

    file_path = t["file_path"]
    file_size = os.path.getsize(file_path)

    range_header = request.headers.get("range")

    # Full download
    if not range_header:
        f = open(file_path, "rb")
        return StreamingResponse(f, media_type="application/octet-stream")

    # Multi-range
    if "," in range_header:
        ranges = parse_multi_range(range_header)
        boundary = uuid.uuid4().hex
        body = b""

        with open(file_path, "rb") as f:
            for start, end in ranges:
                length = end - start + 1
                f.seek(start)
                chunk = f.read(length)

                part = (
                    f"--{boundary}\r\n"
                    f"Content-Type: application/octet-stream\r\n"
                    f"Content-Range: bytes {start}-{end}/{file_size}\r\n"
                    f"\r\n"
                ).encode() + chunk + b"\r\n"

                body += part

        body += f"--{boundary}--\r\n".encode()

        headers = {
            "Content-Type": f"multipart/byteranges; boundary={boundary}",
            "Content-Length": str(len(body)),
            "Accept-Ranges": "bytes",
        }

        return Response(content=body, status_code=206, headers=headers)

    # Single range
    start, end = parse_single_range(range_header, file_size)
    length = end - start + 1

    f = open(file_path, "rb")
    f.seek(start)

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
    }

    return StreamingResponse(
        iter_file(f, length),
        status_code=206,
        headers=headers,
        media_type="application/octet-stream",
    )

# ---- UPLOAD / RESTORE (PUT with Range) ----

@imageio_router.put("/{transfer_id}")
async def upload_transfer(transfer_id: str, request: Request):
    t = transfers.get(transfer_id)
    if not t or t["mode"] != "upload":
        raise HTTPException(404)

    file_path = t["file_path"]
    logger.debug(f"uploading to file {file_path}")

    range_header = request.headers.get("content-range")
    if not range_header:
        with open(file_path, "r+b") as f:
            async for chunk in request.stream():
                if not chunk:
                    continue
                f.write(chunk)

    else:
        # Example: bytes 2097152-2162687
        _, range_part = range_header.split(" ")
        start_s, end_s = range_part.split("-")
        start = int(start_s)
        end = int(end_s)

        with open(file_path, "r+b") as f:
            f.seek(start)
            async for chunk in request.stream():
                if not chunk:
                    continue
                f.write(chunk)

    return Response(status_code=204)


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

# =========================
# Run ImageIO Service
# =========================

imageio_app.include_router(imageio_router, prefix=api_prefix)

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
