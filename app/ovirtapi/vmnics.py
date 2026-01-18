from fastapi import APIRouter, Request, HTTPException
from app.cloudstack.client import cs_request
from app.utils.xml_builder import xml_response
import uuid

router = APIRouter()

def cs_nic_to_ovirt(nic: dict, vm_id: str) -> dict:
    """
    Convert a CloudStack NIC to an oVirt-compatible vNIC profile payload.
    """
    return {
        "id": nic.get("id", str(uuid.uuid4())),
        "name": f"nic-{nic.get('deviceid', '0')}",
        "vm": {"id": vm_id},
        "interface": "virtio",  # Default interface type in CloudStack
        "linked": nic.get("isdefault", True),
        "plugged": True,  # Assuming plugged for simplicity
        "mac": {
            "address": nic.get("macaddress", "00:00:00:00:00:00")
        },
        "ip": {
            "address": nic.get("ipaddress", ""),
            "gateway": nic.get("gateway", ""),
            "netmask": nic.get("netmask", "")
        },
        "network": {
            "id": nic.get("networkid", ""),
            "name": nic.get("networkname", "")
        }
    }

@router.get("/vms/{vm_id}/nics")
async def list_vm_nics(vm_id: str, request: Request):
    """
    Lists all network interfaces for a VM.
    """
    try:
        # Get VM details to confirm it exists
        vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
        vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])
        
        if not vms:
            raise HTTPException(status_code=404, detail="VM not found")
        
        vm = vms[0]
        
        # Get NICs for the VM (in CloudStack, these are represented as nics in the VM object)
        nics = vm.get("nic", [])
        
        # Convert nics to oVirt format
        nic_list = [cs_nic_to_ovirt(nic, vm_id) for nic in nics]
        
        return xml_response("nics", nic_list)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list VM NICs: {str(e)}")


@router.post("/vms/{vm_id}/nics")
async def create_vm_nic(vm_id: str, request: Request):
    """
    Creates a new network interface for a VM.
    
    Note: This would call CloudStack's addNicToVirtualMachine API in a real implementation.
    """
    try:
        # Get VM details to confirm it exists
        vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
        vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])
        
        if not vms:
            raise HTTPException(status_code=404, detail="VM not found")
        
        # In a real implementation, this would call CloudStack's addNicToVirtualMachine API
        # For now, we'll simulate adding a NIC
        new_nic = {
            "id": str(uuid.uuid4()),
            "deviceid": len(vms[0].get("nic", [])),  # Next device ID
            "macaddress": f"02:00:00:{uuid.uuid4().hex[:2]}:{uuid.uuid4().hex[2:4]}:{uuid.uuid4().hex[4:6]}",
            "ipaddress": "192.168.1.100",  # Simulated IP
            "netmask": "255.255.255.0",
            "gateway": "192.168.1.1",
            "networkid": "default-network-id",  # Simulated network ID
            "networkname": "default-network"
        }
        
        payload = cs_nic_to_ovirt(new_nic, vm_id)
        
        return xml_response("nic", payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create VM NIC: {str(e)}")


@router.get("/vms/{vm_id}/nics/{nic_id}")
async def get_vm_nic(vm_id: str, nic_id: str, request: Request):
    """
    Gets information about a specific NIC on a VM.
    """
    try:
        # Get VM details to confirm it exists
        vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
        vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])
        
        if not vms:
            raise HTTPException(status_code=404, detail="VM not found")
        
        vm = vms[0]
        nics = vm.get("nic", [])
        
        # Find the specific NIC
        target_nic = None
        for nic in nics:
            if nic.get("id") == nic_id or str(nic.get("deviceid", "")) == nic_id:
                target_nic = nic
                break
        
        if not target_nic:
            raise HTTPException(status_code=404, detail="NIC not found")
        
        payload = cs_nic_to_ovirt(target_nic, vm_id)
        
        return xml_response("nic", payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get VM NIC: {str(e)}")


@router.put("/vms/{vm_id}/nics/{nic_id}")
async def update_vm_nic(vm_id: str, nic_id: str, request: Request):
    """
    Updates a network interface on a VM.
    
    Note: CloudStack has limited NIC update capabilities.
    This is a simplified implementation for API compatibility.
    """
    try:
        # Get VM details to confirm it exists
        vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
        vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])
        
        if not vms:
            raise HTTPException(status_code=404, detail="VM not found")
        
        vm = vms[0]
        nics = vm.get("nic", [])
        
        # Find the specific NIC
        target_nic = None
        for nic in nics:
            if nic.get("id") == nic_id or str(nic.get("deviceid", "")) == nic_id:
                target_nic = nic
                break
        
        if not target_nic:
            raise HTTPException(status_code=404, detail="NIC not found")
        
        # In a real implementation, this would update the NIC properties
        # For now, return the current NIC info to simulate update
        payload = cs_nic_to_ovirt(target_nic, vm_id)
        
        return xml_response("nic", payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update VM NIC: {str(e)}")


@router.delete("/vms/{vm_id}/nics/{nic_id}")
async def delete_vm_nic(vm_id: str, nic_id: str, request: Request):
    """
    Removes a network interface from a VM.
    
    Note: This would call CloudStack's removeNicFromVirtualMachine API in a real implementation.
    """
    try:
        # Get VM details to confirm it exists
        vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
        vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])
        
        if not vms:
            raise HTTPException(status_code=404, detail="VM not found")
        
        # In a real implementation, this would call CloudStack's removeNicFromVirtualMachine API
        # For now, we'll simulate the removal
        payload = {
            "id": nic_id,
            "vm": {"id": vm_id}
        }
        
        return xml_response("nic", payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to remove VM NIC: {str(e)}")