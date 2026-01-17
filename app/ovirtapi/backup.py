from fastapi import APIRouter, Response, Request, HTTPException
from app.cloudstack.client import cs_request
from app.ovirtapi.backup_state import create_backup, get_backup
from app.xml.builder import xml_response

router = APIRouter()

@router.post("/vms/{vm_id}/backups")
async def create_backup_endpoint(vm_id: str, request: Request):
    # 1. List VM volumes
    volumes = await cs_request(request,
        "listVolumes",
        {"virtualmachineid": vm_id}
    )["listvolumesresponse"]["volume"]

    checkpoint_ids = []

    # 2. Snapshot each disk
    for vol in volumes:
        snap = await cs_request(request,
            "createSnapshot",
            {"volumeid": vol["id"]}
        )
        snapshot_id = snap["createsnapshotresponse"]["snapshot"]["id"]
        checkpoint_ids.append(snapshot_id)

    # 3. Create logical backup
    backup_id = create_backup(vm_id, checkpoint_ids)

    # 4. oVirt-compatible response
    payload = {
        "id": backup_id,
        "state": "ready",
    }

    return xml_response("backup", payload)

@router.get("/vms/{vm_id}/backups/{backup_id}")
async def get_backup_status(vm_id: str, backup_id: str, request: Request):
    backup = get_backup(backup_id)
    if not backup:
        return Response(status_code=404)

    checkpoints = [{"id": cid} for cid in backup["checkpoint_ids"]]

    payload = {
        "id": backup_id,
        "state": backup["state"],
        "checkpoints": checkpoints,
    }

    return xml_response("backup", payload)

@router.post("/vms/{vm_id}/backups/{backup_id}/finalize")
async def finalize_backup(vm_id: str, backup_id: str, request: Request):
    return Response(status_code=200)

