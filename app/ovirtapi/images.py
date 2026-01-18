from fastapi import APIRouter, Request, HTTPException, Response
from app.cloudstack.client import cs_request
from app.utils.xml_builder import xml_response
import uuid

router = APIRouter()

@router.get("/images/{image_id}/extents")
async def get_image_extents(image_id: str, request: Request):
    """
    Gets the extents of an image.
    
    In a real implementation, this would return information about the
    specific blocks or extents that make up a disk image, which is important
    for incremental backup operations.
    """
    # Simulate image extents for backup purposes
    extents = [
        {
            "id": str(uuid.uuid4()),
            "start_offset": 0,
            "length": 1048576,  # 1MB extent
            "dirty": False
        },
        {
            "id": str(uuid.uuid4()),
            "start_offset": 1048576,
            "length": 1048576,  # 1MB extent
            "dirty": True  # Marked as dirty for incremental backup
        }
    ]
    
    payload = {
        "extents": extents
    }
    
    return xml_response("extents", payload)


@router.get("/images/{image_id}")
async def get_image(image_id: str, request: Request):
    """
    Gets information about an image.
    
    This would typically return metadata about a disk image.
    """
    # For now, simulate getting image information from CloudStack
    # In a real implementation, this would map to CloudStack volume information
    try:
        # Attempt to get volume information if image_id corresponds to a volume
        data = await cs_request(request, "listVolumes", {"id": image_id})
        volumes = data["listvolumesresponse"].get("volume", [])
        
        if volumes:
            volume = volumes[0]
            payload = {
                "id": volume["id"],
                "name": volume["name"],
                "status": "ok" if volume.get("state") == "Ready" else "locked",
                "actual_size": volume.get("size", 0),
                "provisioned_size": volume.get("size", 0),
                "sparse": volume.get("issparse", True),
            }
        else:
            # If not found as a volume, return a simulated image
            payload = {
                "id": image_id,
                "name": f"image-{image_id}",
                "status": "ok",
                "actual_size": 1073741824,  # 1GB default
                "provisioned_size": 1073741824,  # 1GB default
                "sparse": True,
            }
        
        return xml_response("image", payload)
    
    except Exception:
        # If CS request fails, return simulated image
        payload = {
            "id": image_id,
            "name": f"image-{image_id}",
            "status": "ok",
            "actual_size": 1073741824,  # 1GB default
            "provisioned_size": 1073741824,  # 1GB default
            "sparse": True,
        }
        
        return xml_response("image", payload)