from fastapi import APIRouter, Request, HTTPException

from app.cloudstack.client import cs_request
from app.utils.response_builder import create_response

router = APIRouter()

@router.get("/datacenters")
async def list_datacenters(request: Request):
    data = await cs_request(request, "listZones", {})
    zones = data["listzonesresponse"].get("zone", [])

    payload = [cs_zone_to_ovirt(zone) for zone in zones]

    return create_response(request, "data_centers", payload)

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

    return create_response(request, "clusters", payload)

@router.get("/clusters/{cluster_id}")
async def get_cluster(cluster_id: str, request: Request):
    data = await cs_request(request, "listClusters", {"id": cluster_id})
    clusters = data["listclustersresponse"].get("cluster", [])

    if not clusters:
        raise HTTPException(status_code=404, detail="Cluster not found")

    cluster = cs_cluster_to_ovirt(clusters[0])

    return create_response(request, "cluster", cluster)

def cs_host_to_ovirt(host: dict) -> dict:
    """
    Convert a CloudStack Host dict to an oVirt-compatible Host payload.
    """
    state = host["state"].lower()
    return {
        "id": host["id"],
        "name": host["name"],
        "type": "rhel",
        "cluster": {"id": host["clusterid"]},
        "status": "up" if state == "up" else "down",
    }

@router.get("/hosts")
async def list_hosts(request: Request):
    data = await cs_request(request, "listHosts",
        { "type": "Routing" })
    hosts = data["listhostsresponse"].get("host", [])

    payload = [cs_host_to_ovirt(host) for host in hosts]

    return create_response(request, "hosts", payload)

@router.get("/hosts/{host_id}")
async def get_host(host_id: str, request: Request):
    data = await cs_request(request, "listHosts", {"id": host_id})
    hosts = data["listhostsresponse"].get("host", [])

    if not hosts:
        raise HTTPException(status_code=404, detail="Host not found")

    host = cs_host_to_ovirt(hosts[0])

    return create_response(request, "host", host)

def cs_storage_pool_to_ovirt(pool: dict) -> dict:
    """
    Convert a CloudStack StoragePool dict to an oVirt-compatible StorageDomain payload.
    """
    # Extract storage details from CloudStack pool
    pool_id = pool.get("id", "41609681-c92a-410a-bcc2-5b5e1305cdd1")
    pool_name = pool.get("name", "hosted_storage")
    pool_zone_id = pool.get("zoneid", "91f4d826-e4d5-11f0-bd93-00163e6c35f4")

    # Calculate related values based on the example
    available = int(pool.get("capacitybytes", 1128502657024))
    used = int(pool.get("usedbytes", 1769526525952))
    committed = int(pool.get("allocated", 403726925824))

    storage_type = "nfs" if pool.get("type", "nfs") == 'NetworkFilesystem' else pool.get("type", "nfs")

    # Create the detailed storage domain structure as specified
    storage_domain = {
        "available": str(available),
        "backup": "false",
        "block_size": "512",
        "committed": str(committed),
        "critical_space_action_blocker": "5",
        "discard_after_delete": "false",
        "external_status": "ok",
        "master": "true",
        "storage": {
            "address": pool.get("ipaddress", "10.0.32.4"),
            "mount_options": "",
            "nfs_version": pool.get("nfs_version", "auto"),
            "path": pool.get("path", "/acs/primary/ovirt-storage"),
            "type": storage_type
        },
        "storage_format": "v5",
        "supports_discard": "false",
        "supports_discard_zeroes_data": "false",
        "type": "data",
        "used": str(used),
        "warning_low_space_indicator": "10",
        "wipe_after_delete": "false",
        "data_centers": {
            "data_center": [
                {
                    "href": f"/ovirt-engine/api/datacenters/{pool_zone_id}",
                    "id": pool_zone_id
                }
            ]
        },
        "actions": {
            "link": [
                {
                    "href": f"/ovirt-engine/api/storagedomains/{pool_id}/isattached",
                    "rel": "isattached"
                },
                {
                    "href": f"/ovirt-engine/api/storagedomains/{pool_id}/updateovfstore",
                    "rel": "updateovfstore"
                },
                {
                    "href": f"/ovirt-engine/api/storagedomains/{pool_id}/refreshluns",
                    "rel": "refreshluns"
                },
                {
                    "href": f"/ovirt-engine/api/storagedomains/{pool_id}/reduceluns",
                    "rel": "reduceluns"
                }
            ]
        },
        "name": pool_name,
        "description": pool.get("description", ""),
        "comment": "",
        "link": [
            {
                "href": f"/ovirt-engine/api/storagedomains/{pool_id}/diskprofiles",
                "rel": "diskprofiles"
            },
            {
                "href": f"/ovirt-engine/api/storagedomains/{pool_id}/disks",
                "rel": "disks"
            },
            {
                "href": f"/ovirt-engine/api/storagedomains/{pool_id}/storageconnections",
                "rel": "storageconnections"
            },
            {
                "href": f"/ovirt-engine/api/storagedomains/{pool_id}/permissions",
                "rel": "permissions"
            },
            {
                "href": f"/ovirt-engine/api/storagedomains/{pool_id}/templates",
                "rel": "templates"
            },
            {
                "href": f"/ovirt-engine/api/storagedomains/{pool_id}/vms",
                "rel": "vms"
            },
            {
                "href": f"/ovirt-engine/api/storagedomains/{pool_id}/disksnapshots",
                "rel": "disksnapshots"
            }
        ],
        "href": f"/ovirt-engine/api/storagedomains/{pool_id}",
        "id": pool_id
    }
    return storage_domain

@router.get("/storagedomains")
async def list_storage_domains(request: Request):
    data = await cs_request(request, "listStoragePools", {})
    pools = data["liststoragepoolsresponse"].get("storagepool", [])

    payload = [cs_storage_pool_to_ovirt(pool) for pool in pools]

    return create_response(request, "storage_domains", payload)

@router.get("/datacenters/{datacenter_id}/storagedomains")
async def list_datacenter_storage_domains(datacenter_id: str, request: Request):
    data = await cs_request(request, "listStoragePools", {})
    pools = data["liststoragepoolsresponse"].get("storagepool", [])

    # Filter by datacenter (zone) id
    filtered_pools = [pool for pool in pools if pool.get("zoneid") == datacenter_id]

    payload = [cs_storage_pool_to_ovirt(pool) for pool in filtered_pools]

    return create_response(request, "storage_domains", payload)

