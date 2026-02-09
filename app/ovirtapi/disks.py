from fastapi import APIRouter, Request, HTTPException, Response
from app.cloudstack.client import cs_request
from app.utils.response_builder import create_response
from app.utils.async_job import wait_for_job, get_job_id

import json

router = APIRouter()

def cs_volume_to_ovirt(volume: dict) -> dict:
    """
    Convert a CloudStack Volume dict to an oVirt-compatible Disk payload.
    """
    volume_id = volume["id"]
    storage_id = volume.get("storageid", "default-storage-domain")
    zone_id = volume.get("zoneid", "default-zone")

    return {
        "actual_size": str(volume.get("size", 0)),
        "alias": volume.get("name", volume_id),
        "backup": "none",
        "content_type": "data",
        "format": "cow" if volume.get("format", "qcow2") == "qcow2" else "raw",
        "image_id": volume_id,
        "propagate_errors": "false",
        "provisioned_size": str(volume.get("size", 0)),
        "shareable": "false",
        "sparse": str(volume.get("issparse", True)).lower(),
        "status": "ok" if volume.get("state") == "Ready" else "locked",
        "storage_type": "image",
        "wipe_after_delete": "false",
        "disk_profile": {
            "href": f"/ovirt-engine/api/diskprofiles/{volume_id}",
            "id": volume_id
        },
        "quota": {
            "href": f"/ovirt-engine/api/datacenters/{zone_id}/quotas/{zone_id}",
            "id": zone_id
        },
        "storage_domains": {
            "storage_domain": [{
                "href": f"/ovirt-engine/api/storagedomains/{storage_id}",
                "id": storage_id
            }]
        },
        "actions": {
            "link": [
                {
                    "href": f"/ovirt-engine/api/disks/{volume_id}/reduce",
                    "rel": "reduce"
                },
                {
                    "href": f"/ovirt-engine/api/disks/{volume_id}/copy",
                    "rel": "copy"
                },
                {
                    "href": f"/ovirt-engine/api/disks/{volume_id}/export",
                    "rel": "export"
                },
                {
                    "href": f"/ovirt-engine/api/disks/{volume_id}/move",
                    "rel": "move"
                },
                {
                    "href": f"/ovirt-engine/api/disks/{volume_id}/refreshlun",
                    "rel": "refreshlun"
                },
                {
                    "href": f"/ovirt-engine/api/disks/{volume_id}/convert",
                    "rel": "convert"
                },
                {
                    "href": f"/ovirt-engine/api/disks/{volume_id}/sparsify",
                    "rel": "sparsify"
                }
            ]
        },
        "name": volume.get("name", volume_id),
        "description": volume.get("displaytext", ""),
        "link": [
            {
                "href": f"/ovirt-engine/api/disks/{volume_id}/disksnapshots",
                "rel": "disksnapshots"
            },
            {
                "href": f"/ovirt-engine/api/disks/{volume_id}/permissions",
                "rel": "permissions"
            },
            {
                "href": f"/ovirt-engine/api/disks/{volume_id}/statistics",
                "rel": "statistics"
            }
        ],
        "href": f"/ovirt-engine/api/disks/{volume_id}",
        "id": volume_id
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
        
        return create_response(request, "disks", payload)
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
        
        return create_response(request, "disk", payload)
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
        
        return create_response(request, "disk", payload)
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
        # Get volume information
        data = await cs_request(request, "listVolumes", {"id": disk_id})
        volumes = data["listvolumesresponse"].get("volume", [])
    except Exception as e:
        # If volume does not exist, assume it has been removed already
        if e.response.status_code == 431:
            return Response(status_code=200)
        raise
        
    try:
        # Prepare parameters for CloudStack deleteVolume API
        cs_params = {
            "id": disk_id
        }

        # Call CloudStack API to delete the volume
        data = await cs_request(request, "deleteVolume", cs_params)

        # Return success response with status "complete"
        payload = {
            "status": "complete"
        }

        return create_response(request, "delete_volume", payload)

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
        
        return create_response(request, "disk", payload)
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
        
        return create_response(request, "disk", payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reduce disk: {str(e)}")

@router.post("/disks")
async def create_disk(request: Request):
    """
    Creates a new disk.
    
    Expects a JSON payload with disk parameters.
    """
    try:
        # Get the request body to extract disk parameters
        body_bytes = await request.body()
        body_str = body_bytes.decode("utf-8")
        disk_params = json.loads(body_str) if body_str else {}
        
        # Extract parameters from the request
        disk_name = disk_params.get("name", "new-disk")
        disk_size = disk_params.get("provisioned_size", 10737418240)  # 10GB default
        disk_size_GB = int(int(disk_size) / (1024 * 1024 * 1024))
        if disk_size_GB * 1024 * 1024 * 1024 < int(disk_size):
            disk_size_GB += 1
        
        # Prepare parameters for CloudStack createVolume API
        cs_params = {
            "name": disk_name,
            "size": disk_size_GB,  # Convert to string for API call
        }
        
        # Add additional parameters if provided
        if "zoneid" in disk_params:
            cs_params["zoneid"] = disk_params["zoneid"]
        elif "storage_domains" in disk_params:
            storage_domain = disk_params.get("storage_domains", {}).get("storage_domain",[])
            storage_data = await cs_request(request, "listStoragePools", {"id": storage_domain[0].get("id")})
            storage = storage_data["liststoragepoolsresponse"].get("storagepool", [])
            if not storage:
                raise HTTPException(status_code=400, detail="Storage domain is not found")
            cs_params["zoneid"] = storage[0].get("zoneid")
            cs_params["storageid"] = storage[0].get("id")

        if "diskofferingid" in disk_params:
            cs_params["diskofferingid"] = disk_params["diskofferingid"]
        else:
            offerings_data = await cs_request(request, "listDiskOfferings", {"storagetype": "shared", "name": "Custom"})
            offerings = offerings_data["listdiskofferingsresponse"].get("diskoffering", [])
            if not offerings:
                raise HTTPException(status_code=400, detail="Custom disk offering is required")
            cs_params["diskofferingid"] = offerings[0].get("id", "")
        
        # Call CloudStack API to create the volume
        data = await cs_request(request, "createVolume", cs_params)
       
        # Check for job response (async)
        job_id = get_job_id(data)

        # Wait for async job to complete
        job_result = await wait_for_job(request, job_id)

        # Extract the created volume from the response
        volume = job_result.get("volume", {})
        
        # Convert to oVirt format and return
        payload = cs_volume_to_ovirt(volume)
        
        return create_response(request, "disk", payload)
        
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing required parameter: {str(e)}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in request body")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create disk: {str(e)}")

@router.post("/disks/{disk_id}/convert")
async def convert_disk(disk_id: str, request: Request):
    # call convertVolume API in CloudStack to convert the disk format
    try:
        # Get the original disk
        data = await cs_request(request, "listVolumes", {"id": disk_id})
        volumes = data["listvolumesresponse"].get("volume", [])

        if not volumes:
            raise HTTPException(status_code=404, detail="Disk not found")

        # Get the request body to extract convert parameters
        body_bytes = await request.body()
        body_str = body_bytes.decode("utf-8")
        convert_params = json.loads(body_str) if body_str else {}

        format = convert_params.get("disk").get("format")
        sparse = convert_params.get("disk").get("sparse", None)

        if format not in ["raw", "qcow2"]:
            raise HTTPException(status_code=400, detail="Invalid format specified. Supported formats are 'raw' and 'qcow2'.")

        cs_params = {
            "id": disk_id,
            "format": format
        }
        if sparse is not None:
            if not isinstance(sparse, bool):
                raise HTTPException(status_code=400, detail="Invalid value for 'sparse'. It should be a boolean.")
            cs_params["provisioningtype"] = "thin" if sparse else "fat"

        # Call CloudStack API to create the volume
        data = await cs_request(request, "convertVolume", cs_params)

        # Check for job response (async)
        job_id = get_job_id(data)

        # Wait for async job to complete
        job_result = await wait_for_job(request, job_id)

        # Extract the created volume from the response
        volume = job_result.get("volume", {})

        # Convert to oVirt format and return
        payload = cs_volume_to_ovirt(volume)

        return create_response(request, "disk", payload)

    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing required parameter: {str(e)}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in request body")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to convert disk: {str(e)}")