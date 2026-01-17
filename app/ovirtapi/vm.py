from fastapi import APIRouter, Request, HTTPException
from app.cloudstack.client import cs_request
from app.utils.xml_builder import xml_response
from app.utils.async_job import wait_for_job, get_job_id

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

@router.post("/vms/{vm_id}/start")
async def start_vm(vm_id: str, request: Request):
    """Start a stopped VM."""
    data = await cs_request(request, "startVirtualMachine", {"id": vm_id})

    # Check for job response (async)
    job_id = get_job_id(data)
    if job_id:
        # Wait for async job to complete
        job_result = await wait_for_job(request, job_id)
        vm = job_result.get("virtualmachine", {})
    else:
        # Direct response (unlikely but handle it)
        if "errortext" in data:
            raise HTTPException(status_code=400, detail=data.get("errortext"))
        vm = data.get("startvirtualmachineresponse", {}).get("virtualmachine", {})

    payload = cs_vm_to_ovirt(vm)
    return xml_response("vm", payload)

@router.post("/vms/{vm_id}/stop")
async def stop_vm(vm_id: str, request: Request):
    """Forcefully stop a running VM (does not gracefully shutdown)."""
    data = await cs_request(request, "stopVirtualMachine", {"id": vm_id, "forced": "true"})

    # Check for job response (async)
    job_id = get_job_id(data)
    if job_id:
        # Wait for async job to complete
        job_result = await wait_for_job(request, job_id)
        vm = job_result.get("virtualmachine", {})
    else:
        # Direct response (unlikely but handle it)
        if "errortext" in data:
            raise HTTPException(status_code=400, detail=data.get("errortext"))
        vm = data.get("stopvirtualmachineresponse", {}).get("virtualmachine", {})

    payload = cs_vm_to_ovirt(vm)
    return xml_response("vm", payload)

@router.post("/vms/{vm_id}/shutdown")
async def shutdown_vm(vm_id: str, request: Request):
    """Gracefully shutdown a running VM."""
    data = await cs_request(request, "stopVirtualMachine", {"id": vm_id, "forced": "false"})

    # Check for job response (async)
    job_id = get_job_id(data)
    if job_id:
        # Wait for async job to complete
        job_result = await wait_for_job(request, job_id)
        vm = job_result.get("virtualmachine", {})
    else:
        # Direct response (unlikely but handle it)
        if "errortext" in data:
            raise HTTPException(status_code=400, detail=data.get("errortext"))
        vm = data.get("stopvirtualmachineresponse", {}).get("virtualmachine", {})

    payload = cs_vm_to_ovirt(vm)
    return xml_response("vm", payload)

