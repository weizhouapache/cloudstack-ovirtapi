from fastapi import APIRouter, Request, HTTPException, Query
from app.cloudstack.client import cs_request
from app.utils.xml_builder import xml_response

router = APIRouter()

def cs_volume_attachment_to_ovirt(volume: dict, vm_id: str) -> dict:
    """
    Convert a CloudStack Volume attachment to an oVirt-compatible DiskAttachment payload.
    """
    return {
        "id": f"{vm_id}-{volume['id']}",  # Composite ID for the attachment
        "vm": {"id": vm_id},
        "disk": {
            "id": volume["id"],
            "name": volume.get("name", volume["id"]),
            "status": "ok" if volume.get("state") == "Ready" else "locked",
        },
        "active": True,
        "interface": "virtio",  # Default interface type
        "logical_name": "",  # CloudStack doesn't expose this directly
        "pass_discard": False,
        "read_only": False,
        "uses_scsi_reservation": False,
        "bootable": volume.get("isbootable", False)
    }

@router.get("/vms/{vm_id}/diskattachments")
async def list_disk_attachments(vm_id: str, request: Request):
    """
    Lists all disk attachments for a VM.
    """
    try:
        # Get VM details to confirm it exists
        vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
        vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])
        
        if not vms:
            raise HTTPException(status_code=404, detail="VM not found")
        
        # Get all volumes and filter by VM ID
        volumes_data = await cs_request(request, "listVolumes", {"virtualmachineid": vm_id})
        volumes = volumes_data["listvolumesresponse"].get("volume", [])
        
        # Convert volumes to disk attachments
        attachments = [cs_volume_attachment_to_ovirt(vol, vm_id) for vol in volumes]
        
        return xml_response("disk_attachments", attachments)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list disk attachments: {str(e)}")


@router.post("/vms/{vm_id}/diskattachments")
async def attach_disk(vm_id: str, request: Request):
    """
    Attaches a disk to a VM.
    
    Note: This would call CloudStack's attachVolume API in a real implementation.
    """
    try:
        # Get VM details to confirm it exists
        vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
        vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])
        
        if not vms:
            raise HTTPException(status_code=404, detail="VM not found")
        
        # In a real implementation, we would expect request body with disk ID
        # For now, we'll simulate the attachment process
        # This would typically involve calling attachVolume API with vm_id and volume_id
        
        # Return a simulated response
        payload = {
            "id": f"{vm_id}-new-attachment",
            "vm": {"id": vm_id},
            "disk": {"id": "simulated-new-disk-id"},
            "active": True,
            "interface": "virtio",
            "bootable": False
        }
        
        return xml_response("disk_attachment", payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to attach disk: {str(e)}")


@router.delete("/vms/{vm_id}/diskattachments/{disk_attachment_id}")
async def detach_disk(vm_id: str, disk_attachment_id: str, request: Request, detach_only: bool = Query(False)):
    """
    Detaches a disk from a VM.
    
    Query Parameter:
        detach_only: If true, only detach without deleting the disk
    """
    try:
        # Get VM details to confirm it exists
        vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
        vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])
        
        if not vms:
            raise HTTPException(status_code=404, detail="VM not found")
        
        # Extract disk ID from the attachment ID (format: vm_id-disk_id)
        # In a real implementation, we would look up the actual disk ID
        disk_id = disk_attachment_id.split('-')[-1] if '-' in disk_attachment_id else disk_attachment_id
        
        # In a real implementation, this would call CloudStack's detachVolume API
        # For now, we'll simulate the detachment
        # If detach_only is false, we might also delete the volume
        
        # Return success response
        payload = {
            "id": disk_attachment_id,
            "vm": {"id": vm_id},
            "disk": {"id": disk_id},
            "active": False
        }
        
        return xml_response("disk_attachment", payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to detach disk: {str(e)}")