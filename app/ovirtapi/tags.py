from fastapi import APIRouter, Request, HTTPException
from app.cloudstack.client import cs_request
from app.utils.xml_builder import xml_response
import uuid

router = APIRouter()

# In-memory store for tags (since CloudStack tags work differently)
vm_tags = {}

def cs_tag_to_ovirt(tag: dict) -> dict:
    """
    Convert a CloudStack Tag to an oVirt-compatible Tag payload.
    """
    return {
        "id": tag.get("id", str(uuid.uuid4())),
        "name": tag.get("key", tag.get("tag", "untitled")),
        "description": tag.get("value", ""),
    }

@router.get("/tags")
async def list_tags(request: Request):
    """
    Lists all tags in the system.
    
    In CloudStack, tags are associated with resources. This implementation
    aggregates tags from various resources.
    """
    try:
        # In a real implementation, this would aggregate tags from various resources
        # For now, we'll return a simulated list of tags
        all_tags = []
        
        # Get all VM tags
        for vm_id, tags in vm_tags.items():
            for tag in tags:
                if tag not in all_tags:
                    all_tags.append({
                        "id": str(uuid.uuid4()),
                        "name": tag,
                        "description": f"Tag for VM {vm_id}"
                    })
        
        return xml_response("tags", all_tags)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list tags: {str(e)}")


@router.post("/vms/{vm_id}/tags")
async def assign_tag_to_vm(vm_id: str, request: Request):
    """
    Assigns a tag to a VM.
    
    In CloudStack, this would involve creating resource tags.
    """
    try:
        # Get VM details to confirm it exists
        vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
        vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])
        
        if not vms:
            raise HTTPException(status_code=404, detail="VM not found")
        
        # For this implementation, we'll simulate adding a tag
        # In a real implementation, we would parse the request body to get the tag name
        # and call CloudStack's createTags API
        
        # Initialize tags for this VM if not present
        if vm_id not in vm_tags:
            vm_tags[vm_id] = []
        
        # For simulation purposes, let's say we're adding a "backup" tag
        new_tag = "backup"  # This would come from request body in a real implementation
        if new_tag not in vm_tags[vm_id]:
            vm_tags[vm_id].append(new_tag)
        
        # Return the assigned tag
        payload = {
            "id": str(uuid.uuid4()),
            "name": new_tag,
            "description": f"Tag '{new_tag}' assigned to VM {vm_id}",
            "vm": {"id": vm_id}
        }
        
        return xml_response("tag", payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to assign tag to VM: {str(e)}")