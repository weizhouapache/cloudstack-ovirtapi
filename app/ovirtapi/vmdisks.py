from fastapi import APIRouter, Request, HTTPException, Query
from app.cloudstack.client import cs_request
from app.utils.response_builder import create_response
from app.utils.async_job import wait_for_job, get_job_id

import json

router = APIRouter()


@router.get("/vms/{vm_id}/diskattachments")
async def get_vm_disk_attachment(vm_id: str, request: Request):
    """
    Gets the disk attachments for a specific VM.
    """
    # First, get the VM to confirm it exists
    data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
    vms = data["listvirtualmachinesresponse"].get("virtualmachine", [])

    if not vms:
        raise HTTPException(status_code=404, detail="VM not found")

    # Get volumes attached to this VM
    volumes_data = await cs_request(request, "listVolumes", {"virtualmachineid": vm_id})
    volumes = volumes_data["listvolumesresponse"].get("volume", [])

    # Convert volumes to disk attachment format
    disk_attachments = []
    for i, volume in enumerate(volumes):
        volume_id = volume.get("id", f"disk-attachment-{i}")
        # Create a disk attachment entry for each volume
        disk_attachment = {
            "id": volume_id,
            "href": f"/ovirt-engine/api/vms/{vm_id}/diskattachments/{volume_id}",
            "active": "true",
            "bootable": str(volume.get("isbootable", False)).lower(),
            "interface": "virtio",  # Default interface
            "pass_discard": "false",
            "read_only": "false",
            "uses_scsi_reservation": "false",
            "vm": {
                "id": vm_id,
                "href": f"/ovirt-engine/api/vms/{vm_id}"
            },
            "disk": {
                "id": volume.get("id", f"disk-{i}"),
                "href": f"/ovirt-engine/api/disks/{volume_id}",
                "name": volume.get("name", volume_id),
                "actual_size": int(volume.get("size", 0)),
                "provisioned_size": int(volume.get("size", 0)),
                "status": "ok" if volume.get("state") == "Ready" else "locked",
                "sparse": str(volume.get("issparse", True)).lower(),
                "bootable": str(volume.get("isbootable", False)).lower(),
                "propagate_errors": "false",
                "qcow_version": "qcow2_v3",
                "wipe_after_delete": "false",
                "content_type": "data",
                "format": "cow",
                "storage_type": "image"
            }
        }
        disk_attachments.append(disk_attachment)

    # Return the disk attachments as a collection
    payload = {"disk_attachment": disk_attachments}
    return create_response(request, "disk_attachment", payload)


@router.post("/vms/{vm_id}/diskattachments")
async def attach_disk(vm_id: str, request: Request):
    """
    Attaches a disk to a VM.
    
    Note: This would call CloudStack's attachVolume API in a real implementation.
    """
    try:
        # Get VM details to confirm it exists
        vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id, "listall": True, "details": "min"})
        vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])
        
        if not vms:
            raise HTTPException(status_code=404, detail="VM not found")
        

        # Get volume from request
        body_bytes = await request.body()
        body_str = body_bytes.decode("utf-8")
        diskattachment_params = json.loads(body_str) if body_str else {}
        disk_id = diskattachment_params.get("disk").get("id")

        cs_params = {
            "id": disk_id,
            "virtualmachineid": vm_id,
        }

        # Get all volumes and filter by VM ID
        volumes_data = await cs_request(request, "listVolumes", {"virtualmachineid": vm_id})
        volumes = volumes_data["listvolumesresponse"].get("volume", [])
        if not volumes or len(volumes) == 0:
            cs_params["deviceid"] = 0
        else:
            cs_params["deviceid"] = len(volumes)

        # Assign the volume to the owner of virtual machine if the volume is not already assigned to an account
        vm = vms[0]
        volumes_data = await cs_request(request, "listVolumes", {"id": disk_id})
        volume = volumes_data["listvolumesresponse"].get("volume", [])[0]
        if volume.get("domainid") != vm.get("domainid") or volume.get("account") != vm.get("account"):
            assignvolume_params = {
                "volumeid": volume.get("id")
            }
            if vm.get("projectid"):
                assignvolume_params["projectid"] = vm.get("projectid")
            else:
                # list accounts to find the account id of the owner of virtual machine
                listaccount_params = {
                    "domainid": vm.get("domainid"),
                    "name": vm.get("account")
                }
                accounts_data = await cs_request(request, "listAccounts", listaccount_params)
                accounts = accounts_data["listaccountsresponse"].get("account", [])
                if not accounts or len(accounts) == 0:
                    raise HTTPException(status_code=404, detail="Account not found for the VM owner")
                account = accounts[0]
                assignvolume_params["accountid"] = account.get("id")

            # Assign the volume to the account of the owner of virtual machine
            await cs_request(request, "assignVolume", assignvolume_params)

        # Call CloudStack API to attach the volume to the VM
        data = await cs_request(request, "attachVolume", cs_params)

        # Check for job response (async)
        job_id = get_job_id(data)
        if job_id:
            # Wait for async job to complete
            job_result = await wait_for_job(request, job_id)
            volume = job_result.get("volume", {})
        else:
            raise HTTPException(status_code=500, detail="Failed to attach Volume - job failed")

        # Return a response
        payload = {
            "disk": {"id": disk_id},
            "active": True,
            "interface": "virtio",
            "bootable": False
        }

        return create_response(request, "disk_attachment", payload)
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
        
        return create_response(request, "disk_attachment", payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to detach disk: {str(e)}")