from fastapi import APIRouter, Request, HTTPException
from app.cloudstack.client import cs_request
from app.utils.response_builder import create_response
import uuid

router = APIRouter()

# In-memory store for tags (since CloudStack tags work differently)
vm_tags = [ {
    "parent" : {
      "href" : "/ovirt-engine/api/tags/00000000-0000-0000-0000-000000000000",
      "id" : "00000000-0000-0000-0000-000000000000"
    },
    "name" : "veeam-manual",
    "description" : "tag for manual veeam backup",
    "href" : "/ovirt-engine/api/tags/cfc3cf05-e2e8-4754-8302-0d0c98180e8e",
    "id" : "cfc3cf05-e2e8-4754-8302-0d0c98180e8e"
  }, {
    "parent" : {
      "href" : "/ovirt-engine/api/tags/00000000-0000-0000-0000-000000000000",
      "id" : "00000000-0000-0000-0000-000000000000"
    },
    "name" : "veeam-auto",
    "description" : "tag for automatic veeam backup",
    "href" : "/ovirt-engine/api/tags/4a009dee-3a86-4bc1-81ff-670d64618734",
    "id" : "4a009dee-3a86-4bc1-81ff-670d64618734"
  }, {
    "name" : "root",
    "description" : "root",
    "href" : "/ovirt-engine/api/tags/00000000-0000-0000-0000-000000000000",
    "id" : "00000000-0000-0000-0000-000000000000"
  } ]

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
        return create_response(request, "tags", vm_tags)
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
        
        # For simulation purposes, let's say we're adding a "backup" tag
        new_tag = "backup"  # This would come from request body in a real implementation

        
        # Return the assigned tag
        payload = {
            "id": str(uuid.uuid4()),
            "name": new_tag,
            "description": f"Tag '{new_tag}' assigned to VM {vm_id}",
            "vm": {"id": vm_id}
        }
        
        return create_response(request, "tag", payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to assign tag to VM: {str(e)}")