from fastapi import APIRouter, Request, HTTPException
from app.cloudstack.client import cs_request
from app.utils.response_builder import create_response
import json
import uuid

router = APIRouter()

# In-memory store for tags (since CloudStack tags work differently)
vm_tags = [ {
    "parent" : {
      "href" : "/ovirt-engine/api/tags/veeam-manual",
      "id" : "veeam-manual"
    },
    "name" : "veeam-manual",
    "description" : "tag for manual veeam backup",
    "href" : "/ovirt-engine/api/tags/veeam-manual",
    "id" : "veeam-manual"
  }, {
    "parent" : {
      "href" : "/ovirt-engine/api/tags/veeam-auto",
      "id" : "veeam-auto"
    },
    "name" : "veeam-auto",
    "description" : "tag for automatic veeam backup",
    "href" : "/ovirt-engine/api/tags/veeam-auto",
    "id" : "veeam-auto"
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
        # Fetch all CloudStack resource tags with key=veeam_tag for UserVm resources
        tags_data = await cs_request(request, "listTags", {"key": "veeam_tag", "resourcetype": "UserVm"})
        cs_tags = tags_data.get("listtagsresponse", {}).get("tag", [])

        # Merge cs_tags with the static vm_tags list to create a unified tag list
        all_tags = []
        # Add static tags not in cs_tags first
        for vm_tag in vm_tags:
            all_tags.append(vm_tag)
        for cs_tag in cs_tags:
            tag_name = cs_tag.get("value")
            matched_tag = next((t for t in vm_tags if t.get("name") == tag_name), None)
            if not matched_tag:
                all_tags.append({
                    "id": tag_name,
                    "name": tag_name,
                    "href": f"/ovirt-engine/api/tags/{tag_name}",
                })


        payload = {"tag": all_tags}
        return create_response(request, "tags", payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list tags: {str(e)}")


@router.post("/vms/{vm_id}/tags")
async def assign_tag_to_vm(vm_id: str, request: Request):
    """
    Assigns a tag to a VM.
    
    In CloudStack, this involves creating a resource tag with key=veeam_tag
    and the tag name as value.
    """
    try:
        # Parse request body to get the tag name
        body_bytes = await request.body()
        body_str = body_bytes.decode("utf-8")
        body = json.loads(body_str) if body_str else {}
        tag_name = body.get("name")

        if not tag_name:
            raise HTTPException(status_code=400, detail="Tag name is required in the request body")

        # Get VM details to confirm it exists
        vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
        vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])

        if not vms:
            raise HTTPException(status_code=404, detail="VM not found")

        # Create the tag in CloudStack with key=veeam_tag and value=tag_name
        await cs_request(request, "createTags", {
            "resourceids": vm_id,
            "resourcetype": "UserVm",
            "tags[0].key": "veeam_tag",
            "tags[0].value": tag_name
        }, method="POST")

        # Find the matching tag definition from the static vm_tags list
        matched_tag = next((t for t in vm_tags if t.get("name") == tag_name), None)
        if matched_tag:
            payload = {**matched_tag, "vm": {"id": vm_id}}
        else:
            payload = {
                "id": tag_name,
                "name": tag_name,
                "href": f"/ovirt-engine/api/tags/{tag_name}",
                "vm": {"id": vm_id}
            }

        return create_response(request, "tag", payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to assign tag to VM: {str(e)}")