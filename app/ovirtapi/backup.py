from fastapi import APIRouter, Response, Request, HTTPException
from app.cloudstack.client import cs_request
from app.ovirtapi.backup_state import create_backup, get_backup, get_vm_backups, remove_backup, update_backup
from app.utils.response_builder import create_response
import httpx
from app.config import IMAGEIO
import json
import time
import uuid
from app.ovirtapi.vmsnapshots import DUMMY_VM_SNAPSHOT_ID

INTERNAL_TOKEN = IMAGEIO.get("internal_token", "")

router = APIRouter()

@router.post("/vms/{vm_id}/backups")
async def create_backup_endpoint(vm_id: str, request: Request):
    # Parse the JSON request body
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8")
    backup_params = json.loads(body_str) if body_str else {}

    # 1. Get CloudStack VM
    vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
    vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])
    if not vms:
        raise HTTPException(status_code=404, detail="VM not found")
    
    vm = vms[0]
    vm_name = vm["instancename"]

    # 2. Get Host of running VM, or a random host if VM is not running
    if vm.get("state") == "Running":
        # If VM is running, use its host
        target_host_id = vm.get("hostid")
        if target_host_id:
            host_data = await cs_request(request, "listHosts", {"id": target_host_id})
            hosts = host_data["listhostsresponse"].get("host", [])
            if hosts:
                target_host = hosts[0]
    else:
        # If VM is not running, get a random host
        # TODO: This should be changed to get the host that should access the volume
        hosts_data = await cs_request(request, "listHosts", {"type": "Routing"})
        hosts = hosts_data["listhostsresponse"].get("host", [])
        if hosts:
            import random
            target_host = random.choice(hosts)

    if not target_host:
        raise HTTPException(status_code=400, detail="Cannot get host information")

    target_host_ip = target_host.get("ipaddress")

    # 3. Get CloudStack checkpoints via POST request to https://<hostip>/images/internal/backup/{vm}
    # Please note that the Authorization header must be set to the internal token
    backup_url = f"https://{target_host_ip}:54322/images/internal/backup/{vm_name}"
    
    checkpoint_id = backup_params.get("checkpoint_id", "")
    async with httpx.AsyncClient(verify=False) as client:
        headers = {
            "Authorization": INTERNAL_TOKEN,
            "checkpoint-id": checkpoint_id
        }
        response = await client.post(
            backup_url,
            headers=headers
        )
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=f"Failed to create backup: {response.text}")

        backup_result = response.json()

    # 4. create oVirt-compatible response
    backup_id = str(uuid.uuid4())
    new_checkpoint_id = backup_result.get("new_checkpoint_id", "")

    # save backup info
    create_backup(vm_id, vm_name, backup_id, new_checkpoint_id, target_host_ip)
    
    payload = {
        "id": backup_id,
        "to_checkpoint_id": new_checkpoint_id,
        "phase": "starting",
        "creation_date": int(time.time()),
        "modification_date": int(time.time()),
        "vm": {"id": vm_id},
        "snapshot": {"id": DUMMY_VM_SNAPSHOT_ID},
    }

    if checkpoint_id:
        payload["from_checkpoint_id"] = checkpoint_id

    return create_response(request, "backup", payload)

@router.get("/vms/{vm_id}/backups")
async def list_backups(vm_id: str, request: Request):
    backups = get_vm_backups(vm_id)
    return create_response(request, "backups", backups)

@router.get("/vms/{vm_id}/backups/{backup_id}")
async def get_backup_status(vm_id: str, backup_id: str, request: Request):
    backup = get_backup(backup_id)
    if not backup:
        return Response(status_code=404)

    payload = {
        "id": backup_id,
        "phase": backup["phase"],
        "to_checkpoint_id": backup["to_checkpoint_id"],
    }

    return create_response(request, "backup", payload)

@router.post("/vms/{vm_id}/backups/{backup_id}/finalize")
async def finalize_backup(vm_id: str, backup_id: str, request: Request):
    backup = get_backup(backup_id)
    if not backup:
        return Response(status_code=404)

    # update backup from memory
    new_backup = {
        "vm_id": backup["vm_id"],
        "vm_name": backup["vm_name"],
        "to_checkpoint_id": backup["to_checkpoint_id"],
        "target_host_ip": backup["target_host_ip"],
        "phase": "succeeded",
        "created": backup["created"],
    }
    update_backup(backup_id, new_backup)

    payload = {
        "status": "complete",
    }
    return create_response(request, "finalize_backup", payload)


# Keep the old endpoints for volume-based snapshots if needed elsewhere
@router.get("/vms/{vm_id}/checkpoints")
async def list_vm_checkpoints(vm_id: str, request: Request):
    """
    Lists all checkpoints for a VM.
    
    """

    # TODO: get checkpoints from a target host
    return create_response(request, "checkpoints", {})


@router.delete("/vms/{vm_id}/checkpoints/{checkpoint_id}")
async def delete_vm_checkpoint(vm_id: str, checkpoint_id: str, request: Request):
    """
    Deletes a VM checkpoint.

    In CloudStack, this corresponds to deleting a VM snapshot using deleteVMSnapshot API.
    """

    # TODO: delete a checkpoint on a target host

    # Return success response with status "complete"
    payload = {
        "status": "complete"
    }

    return create_response(request, "delete_checkpoint", payload)
