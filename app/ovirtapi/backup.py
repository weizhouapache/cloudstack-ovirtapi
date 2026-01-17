from fastapi import APIRouter, Response
from app.cloudstack.client import cs_request
from app.ovirtapi.backup_state import create_backup
from lxml import etree

router = APIRouter()

@router.post("/vms/{vm_id}/backups")
async def create_backup_endpoint(vm_id: str, request):
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
    root = etree.Element("backup")
    etree.SubElement(root, "id").text = backup_id
    etree.SubElement(root, "state").text = "ready"

    return Response(
        content=etree.tostring(root, pretty_print=True),
        media_type="application/xml"
    )

@router.get("/vms/{vm_id}/backups/{backup_id}")
async def get_backup_status(vm_id, backup_id, request):
    backup = get_backup(backup_id)
    if not backup:
        return Response(status_code=404)

    root = etree.Element("backup")
    etree.SubElement(root, "id").text = backup_id
    etree.SubElement(root, "state").text = backup["state"]

    checkpoints = etree.SubElement(root, "checkpoints")
    for cid in backup["checkpoint_ids"]:
        c = etree.SubElement(checkpoints, "checkpoint")
        etree.SubElement(c, "id").text = cid

    return Response(
        content=etree.tostring(root, pretty_print=True),
        media_type="application/xml"
    )

@router.post("/vms/{vm_id}/backups/{backup_id}/finalize")
async def finalize_backup(vm_id, backup_id, request):
    return Response(status_code=200)

