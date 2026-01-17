from fastapi import APIRouter, Response, Depends
from app.cloudstack.client import cs_request
from app.xml.builder import vms_response

router = APIRouter()

@router.get("/vms")
async def list_vms(request):
    data = await cs_request(request,
        "listVirtualMachines",
        {}
    )
    vms = data["listvirtualmachinesresponse"]["virtualmachine"]

    mapped = [
        {
            "id": vm["id"],
            "name": vm["name"],
            "state": vm["state"].lower()
        }
        for vm in vms
    ]

    return Response(
        content=vms_response(mapped),
        media_type="application/xml"
    )


@router.get("/vms/{vm_id}")
async def get_vm(vm_id: str, request):
    data = await cs_request(request,
        "listVirtualMachines",
        {"id": vm_id}
    )
    vms = data["listvirtualmachinesresponse"]["virtualmachine"]

    if not vms:
        return Response(status_code=404)

    vm = vms[0]

    return Response(
        content=vms_response([{
            "id": vm["id"],
            "name": vm["name"],
            "state": vm["state"].lower()
        }]),
        media_type="application/xml"
    )

