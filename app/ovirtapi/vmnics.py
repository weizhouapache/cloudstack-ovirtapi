from fastapi import APIRouter, Request, HTTPException
from app.cloudstack.client import cs_request
from app.utils.response_builder import create_response
from app.utils.async_job import wait_for_job, get_job_id

import json
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
        
        return create_response(request, "nics", nic_list)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list VM NICs: {str(e)}")


@router.post("/vms/{vm_id}/nics")
async def create_vm_nic(vm_id: str, request: Request):
    """
    Creates a new network interface for a VM.

    Gets network ID from vnic_profile.id in the request and calls CloudStack's addNicToVirtualMachine API.
    """
    try:
        # Get the request body to extract NIC parameters
        body_bytes = await request.body()
        body_str = body_bytes.decode("utf-8")
        nic_params = json.loads(body_str) if body_str else {}

        # Get VM details to confirm it exists
        vm_data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
        vms = vm_data["listvirtualmachinesresponse"].get("virtualmachine", [])

        if not vms:
            raise HTTPException(status_code=404, detail="VM not found")

        # Extract network ID from vnic_profile in the request
        vnic_profile = nic_params.get("vnic_profile", {})
        network_id = vnic_profile.get("id")

        if not network_id:
            raise HTTPException(status_code=400, detail="Network ID (vnic_profile.id) is required")

        # Assign the virtual machine to the account of the owner of network if it's not already assigned
        vm = vms[0]
        network_data = await cs_request(request, "listNetworks", {"id": network_id})
        network = network_data["listnetworksresponse"].get("network", [])[0]
        if network.get("domainid") != vm.get("domainid") or network.get("account") != vm.get("account"):
            # list accounts to find the account id of the owner of network
            listaccount_params = {
                "domainid": network.get("domainid"),
                "name": network.get("account")
            }
            accounts_data = await cs_request(request, "listAccounts", listaccount_params)
            accounts = accounts_data["listaccountsresponse"].get("account", [])
            if not accounts or len(accounts) == 0:
                raise HTTPException(status_code=404, detail="Account not found for the network owner")
            account = accounts[0]

            # Assign the vm to the account of the owner of network
            assignvm_params = {
                "virtualmachineid": vm.get("id"),
                "domainid": account.get("domainid"),
                "account": account.get("name")
            }
            await cs_request(request, "assignVirtualMachine", assignvm_params)

        # Prepare parameters for CloudStack addNicToVirtualMachine API
        cs_params = {
            "virtualmachineid": vm_id,
            "networkid": network_id
        }

        # Call CloudStack API to add NIC to the VM
        data = await cs_request(request, "addNicToVirtualMachine", cs_params)

        # Check for job response (async)
        job_id = get_job_id(data)

        # Wait for async job to complete
        job_result = await wait_for_job(request, job_id)

        # Extract the created vm from the response
        vm = job_result.get("virtualmachine", {})
        if not vm:
            raise HTTPException(status_code=500, detail="Failed to add NIC to VM - no VM returned from CloudStack")

        # Get NIC information from virtual machine
        new_nic_data = get_nic_by_networkid(vm, network_id)

        # If we don't have NIC data at this point, there was an issue
        if not new_nic_data:
            raise HTTPException(status_code=500, detail="Failed to add NIC to VM - no NIC returned from CloudStack")

        # Convert to oVirt format and return
        payload = cs_nic_to_ovirt(new_nic_data, vm_id)

        return create_response(request, "nic", payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in request body")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create VM NIC: {str(e)}")

def get_nic_by_networkid(virtualmachine: dict, networkid: str):
    for nic in virtualmachine.get("nic", []):
        if nic.get("networkid") == networkid:
            return nic
    return None

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
        
        return create_response(request, "nic", payload)
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
        
        return create_response(request, "nic", payload)
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
        
        return create_response(request, "nic", payload)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to remove VM NIC: {str(e)}")