from fastapi import APIRouter, Request, HTTPException, Response
from app.cloudstack.client import cs_request
from app.utils.response_builder import create_response
import uuid
import time
import json
import httpx

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

    # Get the request body to extract disk parameters
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8")
    imagetransfer_params = json.loads(body_str) if body_str else {}
    volume_id = imagetransfer_params.get("disk", {}).get("id")
    direction = imagetransfer_params.get("direction", "upload")

    # Get volume information from CloudStack
    if not volume_id:
        raise HTTPException(status_code=400, detail="Volume ID is required")
        
    try:
        volume_data = await cs_request(request, "listVolumes", {"id": volume_id})
        volumes = volume_data["listvolumesresponse"].get("volume", [])
        if volumes:
            volume_info = volumes[0]
            # Extract relevant information from CloudStack volume
            volume_path = f"/mnt/{volume_info.get('storage')}/{volume_info.get('path')}"
            volume_format = "qcow2"  # Default format, could be determined from volume
            volume_size = volume_info.get("size")
        else:
            raise HTTPException(status_code=400, detail="Volume is not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail="Cannot get volume information")


    # Prepare payload for imageio service based on direction
    if direction == "download":
        # For download, we need to provide the path to the disk
        payload = {
            "id": volume_id,
            "path": volume_path,  # Use path from CloudStack
            "format": volume_format  # Use format from CloudStack
        }
        # Call imageio service to create download transfer
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.post(
                f"https://localhost:54322/images/download",
                json=payload
            )
            if response.status_code == 200:
                imageio_response = response.json()
            else:
                raise HTTPException(status_code=400, detail="Cannot get URLs for download")

    else:  # upload
        # For upload, we need to specify where to store the uploaded data
        payload = {
            "path": volume_path,  # Use path from CloudStack
            "format": volume_format,  # Use format from CloudStack
            "size": volume_size  # Use size from CloudStack
        }
        # Call imageio service to create upload transfer
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.post(
                f"https://localhost:54322/images/upload",
                json=payload
            )
            if response.status_code == 200:
                imageio_response = response.json()
            else:
                raise HTTPException(status_code=400, detail="Cannot get URLs for upload")

    # Extract transfer ID from imageio response
    transfer_id = imageio_response.get("id")
    transfer_url = imageio_response.get("transfer_url")
    proxy_url = imageio_response.get("proxy_url")

    # Create a new image transfer record
    transfer_data = {
        "id": transfer_id,
        "status": "initializing",
        "created_at": time.time(),
        "expires_at": time.time() + 3600,  # Expires in 1 hour
        "phase": "transferring",
        "transfer_url": transfer_url,
        "proxy_url": proxy_url,
        "direction": direction
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


@router.get("/imagetransfers")
async def list_image_transfers(request: Request):
    """
    Lists all image transfers.
    """
    # Update status for all transfers based on time elapsed
    current_time = time.time()
    for transfer_id, transfer in image_transfers.items():
        if current_time > transfer["expires_at"]:
            transfer["status"] = "expired"
            transfer["phase"] = "failed"

    # Prepare the list of transfers
    transfers_list = []
    for transfer_id, transfer in image_transfers.items():
        transfer_info = {
            "id": transfer["id"],
            "status": transfer["status"],
            "phase": transfer["phase"],
            "transfer_url": transfer["transfer_url"],
            "proxy_url": transfer["proxy_url"]
        }
        transfers_list.append(transfer_info)

    payload = transfers_list
    return create_response(request, "image_transfers", payload)


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
    transfer["phase"] = "finished_success"
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