from fastapi import APIRouter, Request, HTTPException, Response
from app.cloudstack.client import cs_request
from app.utils.response_builder import create_response
from app.utils.logging_config import logger
import uuid
import time
import json
import httpx

from app.config import SERVER, IMAGEIO
from app.security.certs import get_default_ip
from app.config import config
from app.ovirtapi.backup_state import get_backup

INTERNAL_TOKEN = IMAGEIO.get( "internal_token", fallback="")

router = APIRouter()

# In-memory store for image transfers
image_transfers = {}

bind_ip = get_default_ip()

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
    backup_id = imagetransfer_params.get("backup", {}).get("id")        # Used for backup
    direction = imagetransfer_params.get("direction", "upload")

    vm_id = None

    # Get volume information from CloudStack
    if not volume_id:
        raise HTTPException(status_code=400, detail="Volume ID is required")

    try:
        volume_data = await cs_request(request, "listVolumes", {"id": volume_id})
        volumes = volume_data["listvolumesresponse"].get("volume", [])
        if volumes:
            volume_info = volumes[0]
            # Extract relevant information from CloudStack volume
            volume_path = f"/mnt/{volume_info.get('storageid')}/{volume_info.get('path')}"
            volume_format = "qcow2"  # Default format, could be determined from volume
            volume_size = volume_info.get("size")
            vm_id = volume_info.get("virtualmachineid")
        else:
            raise HTTPException(status_code=400, detail="Volume is not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail="Cannot get volume information")

    # Get VM information if provided
    target_host_ip = None
    if vm_id:
        vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
        vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])
        if vms:
            vm_info = vms[0]
            if vm_info.get("state") == "Running":
                # If VM is running, use its host
                target_host_id = vm_info.get("hostid")
                if target_host_id:
                    host_data = await cs_request(request, "listHosts", {"id": target_host_id})
                    hosts = host_data["listhostsresponse"].get("host", [])
                    if hosts:
                        target_host = hosts[0]
                        target_host_ip = target_host.get("ipaddress")

    backup = None
    if backup_id:
        backup = get_backup(backup_id)
        if not backup:
            raise HTTPException(status_code=400, detail="Backup is not found")
        target_host_ip = backup["target_host_ip"]

    if not target_host_ip:
        # If VM is not running, get a random host
        # TODO: This should be changed to get the host that should access the volume
        hosts_data = await cs_request(request, "listHosts", {"type": "Routing"})
        hosts = hosts_data["listhostsresponse"].get("host", [])
        if hosts:
            import random
            target_host = random.choice(hosts)
            target_host_ip = target_host.get("ipaddress")

    if not target_host_ip:
        raise HTTPException(status_code=400, detail="Cannot get host information")

    # Prepare payload for imageio service based on direction
    if direction == "download":
        # For download, we need to provide the path to the disk
        payload = {
            "id": volume_id,
            "path": volume_path,  # Use path from CloudStack
            "format": volume_format  # Use format from CloudStack
        }
        if backup:
            payload["backup_id"] = backup_id   # Used for backup
            payload["vm_name"] = backup["vm_name"]
        # Call imageio service to create download transfer
        async with httpx.AsyncClient(verify=False) as client:
            headers = {"Authorization": INTERNAL_TOKEN}
            response = await client.post(
                f"https://{target_host_ip}:54322/images/internal/download",
                json=payload,
                headers=headers
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
            headers = {"Authorization": INTERNAL_TOKEN}
            response = await client.post(
                f"https://{target_host_ip}:54322/images/internal/upload",
                json=payload,
                headers=headers
            )
            if response.status_code == 200:
                imageio_response = response.json()
            else:
                raise HTTPException(status_code=400, detail="Cannot get URLs for upload")

    # Extract transfer ID from imageio response
    transfer_id = imageio_response.get("id")
    transfer_host_ip = imageio_response.get("transfer_host_ip")
    transfer_url = imageio_response.get("transfer_url")

    # Create a new image transfer record
    transfer_data = {
        "id": transfer_id,
        "created_at": time.time(),
        "expires_at": time.time() + 3600,  # Expires in 1 hour
        "phase": "transferring",
        "transfer_url": transfer_url,
        "proxy_url": f"https://{bind_ip}:54323/images/{transfer_id}",
        "direction": direction
    }

    # Store the transfer
    image_transfers[transfer_id] = transfer_data

    # Tells the ImageIO Proxy to store the transfer host IP
    try:
        async with httpx.AsyncClient(verify=False) as client:
            headers = {"Authorization": INTERNAL_TOKEN, "transfer_id": transfer_id, "transfer_host_ip": transfer_host_ip}
            response = await client.post(
                f"https://{bind_ip}:54323/images/internal/store_transfer",
                headers=headers
            )
            if not response.status_code == 200:
                raise HTTPException(status_code=400, detail="Cannot update transfer host in ImageIO proxy")
    except Exception as e:
        logger.error(f"Error updating transfer host in ImageIO proxy: {e}")
        pass

    # Return the transfer information
    payload = {
        "id": transfer_id,
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
            transfer["phase"] = "failed"

    # Prepare the list of transfers
    transfers_list = []
    for transfer_id, transfer in image_transfers.items():
        transfer_info = {
            "id": transfer["id"],
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
        transfer["phase"] = "failed"
    
    payload = {
        "id": transfer["id"],
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
    
    # do not remove image transfer from memory
    # image_transfers.pop(transfer_id)  
    
    # Update transfer status to finalized
    transfer["phase"] = "finished_success"
    transfer["finalized_at"] = time.time()
    
    # Return success response
    payload = {
        "active": False,
        "direction": transfer["direction"],
        "format": "cow",
        "id": transfer["id"],
        "phase": transfer["phase"],
        "proxy_url": transfer["proxy_url"],
        "shallow": True,
        "transfer_url": transfer["transfer_url"],
        "transferred": 10000000
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
    transfer["phase"] = "aborted"
    transfer["cancelled_at"] = time.time()
    
    # Return success response
    payload = {
        "id": transfer["id"],
        "phase": transfer["phase"]
    }
    
    return create_response(request, "image_transfer", payload)