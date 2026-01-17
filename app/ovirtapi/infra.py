from fastapi import APIRouter, Response, Request
from lxml import etree

from app.cloudstack.client import cs_request

router = APIRouter()

@router.get("/datacenters")
async def list_datacenters(request: Request):
    data = await cs_request(request, "listZones", {})
    zones = data["listzonesresponse"].get("zone", [])

    root = etree.Element("data_centers")

    for zone in zones:
        dc = etree.SubElement(root, "data_center")
        etree.SubElement(dc, "id").text = zone["id"]
        etree.SubElement(dc, "name").text = zone["name"]
        etree.SubElement(dc, "status").text = "up"

    return Response(
        content=etree.tostring(root, pretty_print=True),
        media_type="application/xml"
    )

@router.get("/clusters")
async def list_clusters(request: Request):
    data = await cs_request(request, "listClusters", {})
    clusters = data["listclustersresponse"].get("cluster", [])

    root = etree.Element("clusters")

    for cl in clusters:
        c = etree.SubElement(root, "cluster")
        etree.SubElement(c, "id").text = cl["id"]
        etree.SubElement(c, "name").text = cl["name"]

        # Map CloudStack zone → oVirt datacenter
        dc = etree.SubElement(c, "data_center")
        dc.set("id", cl["zoneid"])

        # Required by Veeam
        cpu = etree.SubElement(c, "cpu")
        etree.SubElement(cpu, "architecture").text = "x86_64"

    return Response(
        content=etree.tostring(root, pretty_print=True),
        media_type="application/xml"
    )

@router.get("/hosts")
async def list_hosts(request: Request):
    data = await cs_request(request, "listHosts", {})
    hosts = data["listhostsresponse"].get("host", [])

    root = etree.Element("hosts")

    for h in hosts:
        host_elem = etree.SubElement(root, "host")
        etree.SubElement(host_elem, "id").text = h["id"]
        etree.SubElement(host_elem, "name").text = h["name"]
        etree.SubElement(host_elem, "type").text = "kvm"

        # Map cluster
        cluster = etree.SubElement(host_elem, "cluster")
        cluster.set("id", h["clusterid"])

        # Map status
        state = h["state"].lower()
        etree.SubElement(host_elem, "status").text = "up" if state == "up" else "down"

    return Response(
        content=etree.tostring(root, pretty_print=True),
        media_type="application/xml"
    )

@router.get("/storagedomains")
async def list_storage_domains(request: Request):
    data = await cs_request(request, "listStoragePools", {})
    pools = data["liststoragepoolsresponse"].get("storagepool", [])

    root = etree.Element("storage_domains")

    for pool in pools:
        sd = etree.SubElement(root, "storage_domain")
        etree.SubElement(sd, "id").text = pool["id"]
        etree.SubElement(sd, "name").text = pool["name"]
        etree.SubElement(sd, "type").text = "data"  # oVirt type: data, iso, export
        etree.SubElement(sd, "status").text = "up" if pool["state"] == "Up" else "down"

        dc = etree.SubElement(sd, "data_center")
        dc.set("id", pool["zoneid"])

    return Response(
        content=etree.tostring(root, pretty_print=True),
        media_type="application/xml"
    )

