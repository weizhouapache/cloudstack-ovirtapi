from fastapi import APIRouter, Request, HTTPException
from app.cloudstack.client import cs_request
from app.utils.xml_builder import xml_response
import uuid

router = APIRouter()

def cs_network_to_vnic_profile(network: dict) -> dict:
    """
    Convert a CloudStack Network to an oVirt-compatible vNIC Profile payload.
    """
    return {
        "id": network.get("id", str(uuid.uuid4())),
        "name": network.get("name", "unnamed-network"),
        "description": network.get("displaytext", ""),
        "network": {
            "id": network.get("id", ""),
            "name": network.get("name", "")
        },
        "pass_through": {
            "mode": "disabled"
        }
    }

@router.get("/vnicprofiles")
async def list_vnic_profiles(request: Request):
    """
    Lists all vNIC profiles in the system.
    
    In CloudStack, this maps to networks that can be used for VM interfaces.
    """
    try:
        # Get all networks from CloudStack
        data = await cs_request(request, "listNetworks", {})
        networks = data["listnetworksresponse"].get("network", [])
        
        # Convert each network to a vNIC profile
        vnic_profiles = [cs_network_to_vnic_profile(network) for network in networks]
        
        return xml_response("vnic_profiles", vnic_profiles)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list vNIC profiles: {str(e)}")


@router.get("/vnicprofiles/{profile_id}")
async def get_vnic_profile(profile_id: str, request: Request):
    """
    Gets information about a specific vNIC profile.
    """
    try:
        # Get all networks from CloudStack
        data = await cs_request(request, "listNetworks", {"id": profile_id})
        networks = data["listnetworksresponse"].get("network", [])
        
        if not networks:
            raise HTTPException(status_code=404, detail="vNIC profile not found")
        
        network = networks[0]
        vnic_profile = cs_network_to_vnic_profile(network)
        
        return xml_response("vnic_profile", vnic_profile)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get vNIC profile: {str(e)}")