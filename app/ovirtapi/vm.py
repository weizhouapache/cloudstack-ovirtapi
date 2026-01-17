from fastapi import APIRouter, Request, HTTPException
from app.cloudstack.client import cs_request
from app.utils.xml_builder import xml_response

router = APIRouter()

def cs_vm_to_ovirt(vm: dict) -> dict:
    """
    Convert a CloudStack VM dict to an oVirt-compatible VM payload.
    """
    return {
        "id": vm["id"],
        "name": vm["name"],
        "status": vm["state"].lower(),
    }

@router.get("/vms")
async def list_vms(request: Request):
    data = await cs_request(request,
        "listVirtualMachines",
        {}
    )
    vms = data["listvirtualmachinesresponse"].get("virtualmachine", [])

    payload = [cs_vm_to_ovirt(vm) for vm in vms]

    return xml_response("vms", payload)


@router.get("/vms/{vm_id}")
async def get_vm(vm_id: str, request: Request):
    data = await cs_request(request,
        "listVirtualMachines",
        {"id": vm_id}
    )
    vms = data["listvirtualmachinesresponse"].get("virtualmachine", [])

    if not vms:
        raise HTTPException(status_code=404, detail="VM not found")

    vm = vms[0]
    payload = cs_vm_to_ovirt(vm)

    return xml_response("vm", payload)

