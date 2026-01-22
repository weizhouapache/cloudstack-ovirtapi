from fastapi import APIRouter, Request, HTTPException, Response
from app.cloudstack.client import cs_request
from app.utils.response_builder import create_response
import uuid
import time
import json

from app.config import SERVER
from app.security.certs import get_default_ip

router = APIRouter()

# In-memory store for image transfers
image_transfers = {}

def cs_volume_to_ovirt(volume: dict) -> dict:
    """
    Convert a CloudStack Volume dict to an oVirt-compatible Disk payload.
    """
    return {
        "id": volume["id"],
        "name": volume["name"],
        "status": "ok" if volume.get("state") == "Ready" else "locked",
        "actual_size": volume.get("size", 0),
        "provisioned_size": volume.get("size", 0),
        "sparse": volume.get("issparse", True),
    }

@router.post("/imagetransfers")
async def create_image_transfer(request: Request):
    """
    Creates a new image transfer.
    
    This simulates the process of transferring a disk image, which is important
    for backup and restore operations in Veeam integration.
    """

    # Get bind IP
    bind_ip = SERVER.get("host", "0.0.0.0")
    public_ip = SERVER.get("public_ip", "").strip()
    if public_ip:
        bind_ip = public_ip
    elif bind_ip == "0.0.0.0":
        bind_ip = get_default_ip()

    # Get the request body to extract disk parameters
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8")
    imagetransfer_params = json.loads(body_str) if body_str else {}
    volume_id = imagetransfer_params.get("disk", {}).get("id")
    direction = imagetransfer_params.get("direction", "upload")

    # Generate a unique transfer ID
    #transfer_id = str(uuid.uuid4())
    transfer_id = "d953b972-9abe-415a-808a-b20046510b38"
    
    # Create a new image transfer record
    transfer_data = {
        "id": transfer_id,
        "status": "initializing",
        "created_at": time.time(),
        "expires_at": time.time() + 3600,  # Expires in 1 hour
        "phase": "transferring",
        "transfer_url": f"https://{bind_ip}:54322/images/{transfer_id}",
        "proxy_url": f"https://{bind_ip}:54323/images/{transfer_id}"
    }
    
    # Store the transfer
    image_transfers[transfer_id] = transfer_data
    
    # Return the transfer information
    payload = {
        "id": transfer_id,
        "status": transfer_data["status"],
        "phase": transfer_data["phase"],
        "transfer_url": transfer_data["transfer_url"],
        "proxy_url": transfer_data["proxy_url"]
    }
    
    return create_response(request, "image_transfer", payload)


@router.get("/imagetransfers/{transfer_id}")
async def get_image_transfer(transfer_id: str, request: Request):
    """
    Gets the status of an image transfer.
    """
    if transfer_id not in image_transfers:
        raise HTTPException(status_code=404, detail="Image transfer not found")
    
    transfer = image_transfers[transfer_id]
    
    # Update status based on time elapsed (for simulation purposes)
    current_time = time.time()
    if current_time > transfer["expires_at"]:
        transfer["status"] = "expired"
        transfer["phase"] = "failed"
    
    payload = {
        "id": transfer["id"],
        "status": transfer["status"],
        "phase": transfer["phase"],
        "transfer_url": transfer["transfer_url"],
        "proxy_url": transfer["proxy_url"]
    }
    
    return create_response(request, "image_transfer", payload)


@router.post("/imagetransfers/{transfer_id}/finalize")
async def finalize_image_transfer(transfer_id: str, request: Request):
    """
    Finalizes an image transfer.
    """
    if transfer_id not in image_transfers:
        raise HTTPException(status_code=404, detail="Image transfer not found")
    
    transfer = image_transfers[transfer_id]
    
    # Update transfer status to finalized
    transfer["status"] = "completed"
    transfer["phase"] = "finished"
    transfer["finalized_at"] = time.time()
    
    # Return success response
    payload = {
        "id": transfer["id"],
        "status": transfer["status"],
        "phase": transfer["phase"]
    }
    
    return create_response(request, "image_transfer", payload)


@router.post("/imagetransfers/{transfer_id}/cancel")
async def cancel_image_transfer(transfer_id: str, request: Request):
    """
    Cancels an image transfer.
    """
    if transfer_id not in image_transfers:
        raise HTTPException(status_code=404, detail="Image transfer not found")
    
    transfer = image_transfers[transfer_id]
    
    # Update transfer status to cancelled
    transfer["status"] = "cancelled"
    transfer["phase"] = "aborted"
    transfer["cancelled_at"] = time.time()
    
    # Return success response
    payload = {
        "id": transfer["id"],
        "status": transfer["status"],
        "phase": transfer["phase"]
    }
    
    return create_response(request, "image_transfer", payload)