from fastapi import APIRouter, Request, HTTPException

from app.cloudstack.client import cs_request
from app.utils.xml_builder import xml_response

router = APIRouter()

@router.get("/datacenters")
async def list_datacenters(request: Request):
    data = await cs_request(request, "listZones", {})
    zones = data["listzonesresponse"].get("zone", [])

    payload = [cs_zone_to_ovirt(zone) for zone in zones]

    return xml_response("data_centers", payload)

def cs_zone_to_ovirt(zone: dict) -> dict:
    """
    Convert a CloudStack Zone dict to an oVirt-compatible DataCenter payload.
    """
    return {
        "id": zone["id"],
        "name": zone["name"],
        "status": "up" if zone.get("allocationstate") == "Enabled" else "down",
    }

def cs_cluster_to_ovirt(cluster: dict) -> dict:
    """
    Convert a CloudStack Cluster dict to an oVirt-compatible Cluster payload.
    """
    return {
        "id": cluster["id"],
        "name": cluster["name"],
        "data_center": {"id": cluster["zoneid"]},
        "cpu": {"architecture": "x86_64"},
    }

@router.get("/clusters")
async def list_clusters(request: Request):
    data = await cs_request(request, "listClusters", {})
    clusters = data["listclustersresponse"].get("cluster", [])

    payload = [cs_cluster_to_ovirt(cluster) for cluster in clusters]

    return xml_response("clusters", payload)

def cs_host_to_ovirt(host: dict) -> dict:
    """
    Convert a CloudStack Host dict to an oVirt-compatible Host payload.
    """
    state = host["state"].lower()
    return {
        "id": host["id"],
        "name": host["name"],
        "type": "kvm",
        "cluster": {"id": host["clusterid"]},
        "status": "up" if state == "up" else "down",
    }

@router.get("/hosts")
async def list_hosts(request: Request):
    data = await cs_request(request, "listHosts",
        { "type": "Routing" })
    hosts = data["listhostsresponse"].get("host", [])

    payload = [cs_host_to_ovirt(host) for host in hosts]

    return xml_response("hosts", payload)

@router.get("/hosts/{host_id}")
async def get_host(host_id: str, request: Request):
    data = await cs_request(request, "listHosts", {"id": host_id})
    hosts = data["listhostsresponse"].get("host", [])

    if not hosts:
        raise HTTPException(status_code=404, detail="Host not found")

    host = cs_host_to_ovirt(hosts[0])

    return xml_response("host", host)

def cs_storage_pool_to_ovirt(pool: dict) -> dict:
    """
    Convert a CloudStack StoragePool dict to an oVirt-compatible StorageDomain payload.
    """
    return {
        "id": pool["id"],
        "name": pool["name"],
        "type": "data",
        "status": "up" if pool["state"] == "Up" else "down",
        "data_center": {"id": pool["zoneid"]},
    }

@router.get("/storagedomains")
async def list_storage_domains(request: Request):
    data = await cs_request(request, "listStoragePools", {})
    pools = data["liststoragepoolsresponse"].get("storagepool", [])

    payload = [cs_storage_pool_to_ovirt(pool) for pool in pools]

    return xml_response("storage_domains", payload)

@router.get("/datacenters/{datacenter_id}/storagedomains")
async def list_datacenter_storage_domains(datacenter_id: str, request: Request):
    data = await cs_request(request, "listStoragePools", {})
    pools = data["liststoragepoolsresponse"].get("storagepool", [])

    # Filter by datacenter (zone) id
    filtered_pools = [pool for pool in pools if pool.get("zoneid") == datacenter_id]

    payload = [cs_storage_pool_to_ovirt(pool) for pool in filtered_pools]

    return xml_response("storage_domains", payload)

