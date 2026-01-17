from fastapi import APIRouter, Request, HTTPException
from app.cloudstack.client import cs_request
from app.utils.xml_builder import xml_response

router = APIRouter()

def cs_network_to_ovirt(network: dict) -> dict:
    """
    Convert a CloudStack Network dict to an oVirt-compatible Network payload.
    """
    return {
        "id": network["id"],
        "name": network["name"],
        "status": "up" if network.get("state") == "Implemented" else "down",
    }

@router.get("/networks")
async def list_networks(request: Request):
    data = await cs_request(request, "listNetworks", {})
    networks = data["listnetworksresponse"].get("network", [])

    payload = [cs_network_to_ovirt(network) for network in networks]

    return xml_response("networks", payload)

@router.get("/networks/{network_id}")
async def get_network(network_id: str, request: Request):
    data = await cs_request(request, "listNetworks", {"id": network_id})
    networks = data["listnetworksresponse"].get("network", [])

    if not networks:
        raise HTTPException(status_code=404, detail="Network not found")

    network = cs_network_to_ovirt(networks[0])

    return xml_response("network", network)

@router.get("/datacenters/{datacenter_id}/networks")
async def list_datacenter_networks(datacenter_id: str, request: Request):
    data = await cs_request(request, "listNetworks", {})
    networks = data["listnetworksresponse"].get("network", [])

    # Filter by datacenter (zone) id
    filtered_networks = [network for network in networks if network.get("zoneid") == datacenter_id]

    payload = [cs_network_to_ovirt(network) for network in filtered_networks]

    return xml_response("networks", payload)
