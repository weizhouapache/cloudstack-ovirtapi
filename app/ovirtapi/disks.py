from fastapi import APIRouter, Request, HTTPException
from app.cloudstack.client import cs_request
from app.utils.xml_builder import xml_response

router = APIRouter()

def cs_volume_to_ovirt(volume: dict) -> dict:
    """
    Convert a CloudStack Volume dict to an oVirt-compatible Disk payload.
    """
    return {
        "id": volume["id"],
        "name": volume.get("name", volume["id"]),
        "status": "ok" if volume.get("state") == "Ready" else "locked",
        "actual_size": volume.get("size", 0),
        "provisioned_size": volume.get("size", 0),
        "sparse": volume.get("issparse", True),
        "bootable": volume.get("isbootable", False),
        "active": True,  # Assuming active for simplicity
        "wipe_after_delete": False,  # Default value
        "propagate_errors": False,   # Default value
    }

@router.get("/disks")
async def list_disks(request: Request):
    """
    Lists all disks (volumes) in the system.
    """
    try:
        data = await cs_request(request, "listVolumes", {})
        volumes = data["listvolumesresponse"].get("volume", [])
        
        payload = [cs_volume_to_ovirt(volume) for volume in volumes]
        
        return xml_response("disks", payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list disks: {str(e)}")


@router.get("/disks/{disk_id}")
async def get_disk(disk_id: str, request: Request):
    """
    Gets information about a specific disk.
    """
    try:
        data = await cs_request(request, "listVolumes", {"id": disk_id})
        volumes = data["listvolumesresponse"].get("volume", [])
        
        if not volumes:
            raise HTTPException(status_code=404, detail="Disk not found")
        
        volume = volumes[0]
        payload = cs_volume_to_ovirt(volume)
        
        return xml_response("disk", payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get disk: {str(e)}")


@router.put("/disks/{disk_id}")
async def update_disk(disk_id: str, request: Request):
    """
    Updates a disk configuration.
    
    Note: In CloudStack, disk updates are limited. This is a simplified implementation.
    """
    try:
        # In a real implementation, this would update disk properties
        # For now, just return the current disk info to simulate update
        data = await cs_request(request, "listVolumes", {"id": disk_id})
        volumes = data["listvolumesresponse"].get("volume", [])
        
        if not volumes:
            raise HTTPException(status_code=404, detail="Disk not found")
        
        volume = volumes[0]
        payload = cs_volume_to_ovirt(volume)
        
        return xml_response("disk", payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update disk: {str(e)}")


@router.delete("/disks/{disk_id}")
async def delete_disk(disk_id: str, request: Request):
    """
    Deletes a disk.
    
    Note: This would call CloudStack's deleteVolume API in a real implementation.
    """
    try:
        # In a real implementation, this would call CloudStack's deleteVolume API
        # For now, we'll just simulate the deletion
        data = await cs_request(request, "listVolumes", {"id": disk_id})
        volumes = data["listvolumesresponse"].get("volume", [])
        
        if not volumes:
            raise HTTPException(status_code=404, detail="Disk not found")
        
        # In a real implementation, we would call:
        # await cs_request(request, "deleteVolume", {"id": disk_id})
        
        # Return success response
        return xml_response("disk", {"id": disk_id})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete disk: {str(e)}")


@router.post("/disks/{disk_id}/copy")
async def copy_disk(disk_id: str, request: Request):
    """
    Copies a disk.
    
    This simulates creating a copy of a disk, which is important for backup operations.
    """
    try:
        # Get the original disk
        data = await cs_request(request, "listVolumes", {"id": disk_id})
        volumes = data["listvolumesresponse"].get("volume", [])
        
        if not volumes:
            raise HTTPException(status_code=404, detail="Source disk not found")
        
        original_volume = volumes[0]
        
        # In a real implementation, this would create a volume snapshot or clone
        # For now, we'll simulate the creation of a new volume based on the original
        # This would typically involve createVolumeFromSnapshot or similar
        
        # Return a simulated response indicating the copy operation started
        payload = {
            "id": disk_id,
            "status": "copying",
            "source_disk": {"id": disk_id}
        }
        
        return xml_response("disk", payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to copy disk: {str(e)}")


@router.post("/disks/{disk_id}/reduce")
async def reduce_disk(disk_id: str, request: Request):
    """
    Reduces the size of a disk.
    
    Note: CloudStack doesn't typically support live disk reduction.
    This is a simplified implementation for API compatibility.
    """
    try:
        # Get the original disk
        data = await cs_request(request, "listVolumes", {"id": disk_id})
        volumes = data["listvolumesresponse"].get("volume", [])
        
        if not volumes:
            raise HTTPException(status_code=404, detail="Disk not found")
        
        original_volume = volumes[0]
        
        # In a real implementation, this would involve complex operations
        # For now, return a simulated response
        payload = {
            "id": disk_id,
            "status": "reducing",
            "original_size": original_volume.get("size", 0)
        }
        
        return xml_response("disk", payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reduce disk: {str(e)}")