from fastapi import APIRouter, Request, HTTPException, Response
from app.cloudstack.client import cs_request
from app.utils.response_builder import create_response
import uuid
import time
from app.utils.async_job import wait_for_job, get_job_id
from app.utils.logging_config import logger
import re

router = APIRouter()

DUMMY_VM_SNAPSHOT_ID = "00000000-0000-0000-0000-000000000000"

def cs_vmsnapshot_to_ovirt(vmsnapshot: dict) -> dict:
    """
    Convert a CloudStack VM Snapshot to an oVirt-compatible Snapshot payload.
    """
    # Map CloudStack VM snapshot state to oVirt snapshot state
    state_map = {
        "Ready": "ok",
        "Creating": "locked",
        "Expunging": "locked",
        "Error": "locked",
        "Notuploaded": "locked",
        "Uploaded": "ok",
        "Destroy": "locked"
    }

    cs_state = vmsnapshot.get("state", "Ready")
    ovirt_state = state_map.get(cs_state, "ok")
    
    # Extract memory state based on CloudStack VM snapshot properties
    memory = vmsnapshot.get("type", "DiskAndMemory") == "DiskAndMemory"

    return {
        "id": vmsnapshot["id"],
        "description": vmsnapshot.get("name"),
        "snapshot_status": ovirt_state,
        "snapshot_type": "regular",
        "date": int(time.mktime(time.strptime(re.sub(r'(\d{2})(\d{2})$', r'\1:\2', vmsnapshot.get("created")), "%Y-%m-%dT%H:%M:%S%z"))) if vmsnapshot.get("created") else 0,
        "persist_memorystate": memory,  # True if memory was included in snapshot
        "vm": {"id": vmsnapshot.get("virtualmachineid")}
    }

@router.post("/vms/{vm_id}/snapshots")
async def create_vm_snapshot(vm_id: str, request: Request):
    """
    Creates a snapshot of a VM including memory state.
    
    In CloudStack, this uses createVMSnapshot API to create a complete VM snapshot with memory.
    """
    try:
        # Get VM details to confirm it exists
        vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
        vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])

        if not vms:
            raise HTTPException(status_code=404, detail="VM not found")

        vm = vms[0]

        # Create VM snapshot with memory using CloudStack createVMSnapshot API
        snapshot_params = {
            "virtualmachineid": vm_id,
            "name": f"Snapshot-{int(time.time())}",  # Generate unique name
            "description": f"VM Snapshot of {vm.get('name', vm_id)}",
            "snapshotmemory": True,  # Include memory state in the snapshot
            "quiescevm": False  # Attempt to quiesce filesystem for consistency
        }

        try:
            data = await cs_request(request, "createVMSnapshot", snapshot_params)

            # Check for job response (async)
            job_id = get_job_id(data)
            if job_id:
                # Wait for async job to complete
                job_result = await wait_for_job(request, job_id)
                vmsnapshot = job_result.get("vmsnapshot", {})
                logger.info(f"VM Snapshot created: {vmsnapshot}")
        except Exception as error:
            # Log error but continue to return successful response since snapshot will be gone anyway
            logger.error(f"Error creating VM snapshot: {str(error)}")
            # List all vm snapshots in Error state
            list_result = await cs_request(request, "listVMSnapshot", {
                "virtualmachineid": vm_id,
                "state": "Error"
            })
            # Delete all Error snapshots
            for vmsnapshot in list_result["listvmsnapshotresponse"].get("vmSnapshot", []):
                delete_result = await cs_request(request, "deleteVMSnapshot", {"vmsnapshotid": vmsnapshot["id"]})
                job_id = get_job_id(delete_result)
                job_result = await wait_for_job(request, job_id)

            dummy_vm_snapshot = {
                "id": DUMMY_VM_SNAPSHOT_ID,
                "description": "Dummy Snapshot",
                "snapshot_status": "ok",
                "snapshot_type": "regular",
                "date": int(time.time()),
                "persist_memorystate": True,
                "vm": {"id": vm_id}
            }
            return create_response(request, "snapshot", dummy_vm_snapshot)

        # Convert to oVirt format
        ovirt_snapshot = cs_vmsnapshot_to_ovirt(vmsnapshot)

        return create_response(request, "snapshot", ovirt_snapshot)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create VM snapshot: {str(e)}")

@router.delete("/vms/{vm_id}/snapshots/{snapshot_id}")
async def delete_vm_snapshot(vm_id: str, snapshot_id: str, request: Request):
    """
    Deletes a VM snapshot.
    
    In CloudStack, this corresponds to deleting a VM snapshot using deleteVMSnapshot API.
    """

    if snapshot_id == DUMMY_VM_SNAPSHOT_ID:
        # Return success response if snapshot_id is DUMMY_VM_SNAPSHOT_ID
        job = {
            "id": DUMMY_VM_SNAPSHOT_ID,
            "href": f"/ovirt-engine/api/jobs/{DUMMY_VM_SNAPSHOT_ID}"
        }
        payload = {
            "job": job,
        }
        return create_response(request, "job", payload)

    try:
        # Get VM details to confirm it exists
        vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
        vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])
        
        if not vms:
            raise HTTPException(status_code=404, detail="VM not found")

        # Check if the VM snapshot exists before attempting deletion
        list_result = await cs_request(request, "listVMSnapshot", {
            "virtualmachineid": vm_id,
            "vmsnapshotid": snapshot_id
        })
        snapshots = list_result["listvmsnapshotresponse"].get("vmSnapshot", [])

        if not snapshots:
            raise HTTPException(status_code=404, detail="VM snapshot not found")

        # Call CloudStack API to delete the VM snapshot
        delete_result = await cs_request(request, "deleteVMSnapshot", {
            "vmsnapshotid": snapshot_id
        })
        job_id = get_job_id(restore_result)
        job_result = await wait_for_job(request, job_id)

        job = {
            "id": job_id,
            "href": f"/ovirt-engine/api/jobs/{job_id}"
        }
        # Return a response indicating the deleting operation status
        payload = {
            "job": job,
        }
        
        return create_response(request, "job", payload)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete VM snapshot: {str(e)}")

@router.get("/vms/{vm_id}/snapshots")
async def list_vm_snapshots(vm_id: str, request: Request):
    """
    Lists all VM snapshots for a VM.
    
    In CloudStack, these are represented as VM snapshots (not individual volume snapshots).
    """
    try:
        # Get VM details to confirm it exists
        vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
        vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])
        
        if not vms:
            raise HTTPException(status_code=404, detail="VM not found")
        
        # Get all VM snapshots for this VM
        snapshot_data = await cs_request(request, "listVMSnapshot", {"virtualmachineid": vm_id})
        vmsnapshots = snapshot_data["listvmsnapshotresponse"].get("vmSnapshot", [])

        all_snapshots = []
        for vmsnapshot in vmsnapshots:
            ovirt_snapshot = cs_vmsnapshot_to_ovirt(vmsnapshot)
            all_snapshots.append(ovirt_snapshot)

        if not all_snapshots:
            dummy_vm_snapshot = {
                "id": DUMMY_VM_SNAPSHOT_ID,
                "description": "Dummy Snapshot",
                "snapshot_status": "ok",
                "snapshot_type": "regular",
                "date": int(time.time()),
                "persist_memorystate": True,
                "vm": {"id": vm_id}
            }
            return create_response(request, "snapshots", [dummy_vm_snapshot])

        return create_response(request, "snapshots", all_snapshots)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list VM snapshots: {str(e)}")

@router.get("/vms/{vm_id}/snapshots/{snapshot_id}")
async def get_vm_snapshot(vm_id: str, snapshot_id: str, request: Request):
    """
    Gets information about a specific VM snapshot.
    """

    if snapshot_id == DUMMY_VM_SNAPSHOT_ID:
        # Return dummy vm snapshot response if snapshot_id is DUMMY_VM_SNAPSHOT_ID
        dummy_vm_snapshot = {
            "id": DUMMY_VM_SNAPSHOT_ID,
            "description": "Dummy Snapshot",
            "snapshot_status": "ok",
            "snapshot_type": "regular",
            "date": int(time.time()),
            "persist_memorystate": True,
            "vm": {"id": vm_id}
        }
        logger.info(f"Dummy VM snapshot response: {dummy_vm_snapshot}")
        return create_response(request, "snapshot", dummy_vm_snapshot)

    try:
        # Get VM details to confirm it exists
        vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
        vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])
        
        if not vms:
            raise HTTPException(status_code=404, detail="VM not found")

        # Look for the specific VM snapshot
        snapshot_data = await cs_request(request, "listVMSnapshot", {
            "virtualmachineid": vm_id,
            "vmsnapshotid": snapshot_id
        })
        vmsnapshots = snapshot_data["listvmsnapshotresponse"].get("vmSnapshot", [])

        if not vmsnapshots:
            raise HTTPException(status_code=404, detail="VM snapshot not found")

        target_snapshot = cs_vmsnapshot_to_ovirt(vmsnapshots[0])
        
        return create_response(request, "snapshot", target_snapshot)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get VM snapshot: {str(e)}")

@router.post("/vms/{vm_id}/snapshots/{snapshot_id}/restore")
async def restore_vm_from_snapshot(vm_id: str, snapshot_id: str, request: Request):
    """
    Restores a VM from a VM snapshot.
    
    In CloudStack, this involves reverting the VM to its state at the time of the snapshot.
    """
    try:
        # Get VM details to confirm it exists
        vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
        vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])
        
        if not vms:
            raise HTTPException(status_code=404, detail="VM not found")
        
        # Verify the snapshot exists
        snapshot_data = await cs_request(request, "listVMSnapshot", {
            "virtualmachineid": vm_id,
            "vmsnapshotid": snapshot_id
        })
        vmsnapshots = snapshot_data["listvmsnapshotresponse"].get("vmSnapshot", [])

        if not vmsnapshots:
            raise HTTPException(status_code=404, detail="VM snapshot not found")

        # Execute the restore operation using revertToVMSnapshot API
        restore_result = await cs_request(request, "revertToVMSnapshot", {
            "vmsnapshotid": snapshot_id
        })
        
        job_id = get_job_id(restore_result)
        if job_id:
            # Wait for async job to complete
            job_result = await wait_for_job(request, job_id)
        else:
            raise HTTPException(status_code=400, detail="Failed to restore VM snapshot")

        job = {
            "id": job_id,
            "href": f"/ovirt-engine/api/jobs/{job_id}"
        }
        # Return a response indicating the restore operation status
        payload = {
            "job": job,
            "vm": {"id": vm_id},
            "status": "restoring",  # Will change to ok when completed
        }
        
        return create_response(request, "job", payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restore VM from snapshot: {str(e)}")

# Keep the old endpoints for volume-based snapshots if needed elsewhere
@router.get("/vms/{vm_id}/checkpoints")
async def list_vm_checkpoints(vm_id: str, request: Request):
    """
    Lists all checkpoints for a VM.
    
    In CloudStack, these are represented as snapshots of the VM's volumes.
    """
    try:
        # Get VM details to confirm it exists
        vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
        vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])
        
        if not vms:
            raise HTTPException(status_code=404, detail="VM not found")
        
        # Get all snapshots for volumes attached to this VM
        volumes_data = await cs_request(request, "listVolumes", {"virtualmachineid": vm_id})
        volumes = volumes_data["listvolumesresponse"].get("volume", [])
        
        all_snapshots = []
        for volume in volumes:
            # Get snapshots for this volume
            snapshot_data = await cs_request(request, "listSnapshots", {"volumeid": volume["id"]})
            snapshots = snapshot_data["listsnapshotsresponse"].get("snapshot", [])

            # Convert each snapshot to oVirt format
            for snapshot in snapshots:
                # Using original conversion function for volume snapshots
                ovirt_snapshot = {
                    "id": snapshot["id"],
                    "description": snapshot.get("name", f"Snapshot of {snapshot.get('volumename', 'volume')}"),
                    "status": map_cs_state_to_ovirt(snapshot.get("state", "Created")),
                    "date": snapshot.get("created", ""),
                    "persist_memorystate": False,  # Volume snapshots don't capture memory state
                }
                ovirt_snapshot["vm"] = {"id": vm_id}  # Add VM reference
                all_snapshots.append(ovirt_snapshot)

        return create_response(request, "checkpoints", all_snapshots)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list VM checkpoints: {str(e)}")

def map_cs_state_to_ovirt(cs_state: str) -> str:
    """Helper function to map CloudStack states to oVirt states"""
    state_map = {
        "Allocated": "locked",
        "Creating": "locked",
        "Created": "ok",
        "Destroyed": "locked",
        "Expunging": "locked",
        "Error": "locked"
    }
    return state_map.get(cs_state, "ok")