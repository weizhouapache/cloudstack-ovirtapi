from fastapi import Request, Response
from app.utils.xml_builder import xml_response
from app.utils.json_builder import json_response

def create_response(request: Request, root_name: str, payload, status_code: int = 200) -> Response:
    """
    Creates a response based on the Accept header in the request.
    Returns XML if Accept header contains 'application/xml', otherwise returns JSON.
    """
    content_type = "application/json"

    # Check if the request has Accept header requesting XML
    if request and hasattr(request, 'headers'):
        if "accept" in request.headers:
            content_type = request.headers["accept"].lower()
        elif "Accept" in request.headers:
            content_type = request.headers["Accept"].lower()

    if content_type == "application/xml":
        return xml_response(root_name, payload, status_code)

    # Default to JSON response
    return json_response(payload, status_code)

def api_root_full(request=None):
    """
    Returns API root response, either JSON or XML based on Accept header.
    Returns JSON by default, XML if Accept header contains 'application/xml'.
    """
    # Full API response structure as specified
    payload = {
        "engine_backup": {},
        "product_info": {
            "instance_id": "948b5344-e4d5-11f0-bf11-00163e6c35f4",
            "name": "CloudStack oVirtAPI Engine",
            "version": {
                "build": "1",
                "full_version": "1.0.0",
                "major": "1",
                "minor": "0",
                "revision": "0"
            }
        },
        "special_objects": {
            "blank_template": {
                "href": "/ovirt-engine/api/templates/00000000-0000-0000-0000-000000000000",
                "id": "00000000-0000-0000-0000-000000000000"
            },
            "root_tag": {
                "href": "/ovirt-engine/api/tags/00000000-0000-0000-0000-000000000000",
                "id": "00000000-0000-0000-0000-000000000000"
            }
        },
        "summary": {
            "hosts": {
                "active": "1",
                "total": "1"
            },
            "storage_domains": {
                "active": "1",
                "total": "2"
            },
            "users": {
                "active": "1",
                "total": "1"
            },
            "vms": {
                "active": "1",
                "total": "8"
            }
        },
        "time": 1769037786501,
        "authenticated_user": {
            "href": "/ovirt-engine/api/users/c067a148-e4d5-11f0-98ce-00163e6c35f4",
            "id": "c067a148-e4d5-11f0-98ce-00163e6c35f4"
        },
        "effective_user": {
            "href": "/ovirt-engine/api/users/c067a148-e4d5-11f0-98ce-00163e6c35f4",
            "id": "c067a148-e4d5-11f0-98ce-00163e6c35f4"
        },
        "link": [
            {"href": "/ovirt-engine/api/clusters", "rel": "clusters"},
            {"href": "/ovirt-engine/api/clusters?search={query}", "rel": "clusters/search"},
            {"href": "/ovirt-engine/api/datacenters", "rel": "datacenters"},
            {"href": "/ovirt-engine/api/datacenters?search={query}", "rel": "datacenters/search"},
            {"href": "/ovirt-engine/api/events", "rel": "events"},
            {"href": "/ovirt-engine/api/events;from={event_id}?search={query}", "rel": "events/search"},
            {"href": "/ovirt-engine/api/hosts", "rel": "hosts"},
            {"href": "/ovirt-engine/api/hosts?search={query}", "rel": "hosts/search"},
            {"href": "/ovirt-engine/api/networks", "rel": "networks"},
            {"href": "/ovirt-engine/api/networks?search={query}", "rel": "networks/search"},
            {"href": "/ovirt-engine/api/roles", "rel": "roles"},
            {"href": "/ovirt-engine/api/storagedomains", "rel": "storagedomains"},
            {"href": "/ovirt-engine/api/storagedomains?search={query}", "rel": "storagedomains/search"},
            {"href": "/ovirt-engine/api/tags", "rel": "tags"},
            {"href": "/ovirt-engine/api/bookmarks", "rel": "bookmarks"},
            {"href": "/ovirt-engine/api/icons", "rel": "icons"},
            {"href": "/ovirt-engine/api/templates", "rel": "templates"},
            {"href": "/ovirt-engine/api/templates?search={query}", "rel": "templates/search"},
            {"href": "/ovirt-engine/api/instancetypes", "rel": "instancetypes"},
            {"href": "/ovirt-engine/api/instancetypes?search={query}", "rel": "instancetypes/search"},
            {"href": "/ovirt-engine/api/users", "rel": "users"},
            {"href": "/ovirt-engine/api/users?search={query}", "rel": "users/search"},
            {"href": "/ovirt-engine/api/groups", "rel": "groups"},
            {"href": "/ovirt-engine/api/groups?search={query}", "rel": "groups/search"},
            {"href": "/ovirt-engine/api/domains", "rel": "domains"},
            {"href": "/ovirt-engine/api/vmpools", "rel": "vmpools"},
            {"href": "/ovirt-engine/api/vmpools?search={query}", "rel": "vmpools/search"},
            {"href": "/ovirt-engine/api/vms", "rel": "vms"},
            {"href": "/ovirt-engine/api/vms?search={query}", "rel": "vms/search"},
            {"href": "/ovirt-engine/api/disks", "rel": "disks"},
            {"href": "/ovirt-engine/api/disks?search={query}", "rel": "disks/search"},
            {"href": "/ovirt-engine/api/jobs", "rel": "jobs"},
            {"href": "/ovirt-engine/api/storageconnections", "rel": "storageconnections"},
            {"href": "/ovirt-engine/api/vnicprofiles", "rel": "vnicprofiles"},
            {"href": "/ovirt-engine/api/diskprofiles", "rel": "diskprofiles"},
            {"href": "/ovirt-engine/api/cpuprofiles", "rel": "cpuprofiles"},
            {"href": "/ovirt-engine/api/schedulingpolicyunits", "rel": "schedulingpolicyunits"},
            {"href": "/ovirt-engine/api/schedulingpolicies", "rel": "schedulingpolicies"},
            {"href": "/ovirt-engine/api/permissions", "rel": "permissions"},
            {"href": "/ovirt-engine/api/macpools", "rel": "macpools"},
            {"href": "/ovirt-engine/api/networkfilters", "rel": "networkfilters"},
            {"href": "/ovirt-engine/api/operatingsystems", "rel": "operatingsystems"},
            {"href": "/ovirt-engine/api/externalhostproviders", "rel": "externalhostproviders"},
            {"href": "/ovirt-engine/api/openstackimageproviders", "rel": "openstackimageproviders"},
            {"href": "/ovirt-engine/api/openstackvolumeproviders", "rel": "openstackvolumeproviders"},
            {"href": "/ovirt-engine/api/openstacknetworkproviders", "rel": "openstacknetworkproviders"},
            {"href": "/ovirt-engine/api/katelloerrata", "rel": "katelloerrata"},
            {"href": "/ovirt-engine/api/affinitylabels", "rel": "affinitylabels"},
            {"href": "/ovirt-engine/api/clusterlevels", "rel": "clusterlevels"},
            {"href": "/ovirt-engine/api/imagetransfers", "rel": "imagetransfers"},
            {"href": "/ovirt-engine/api/externalvmimports", "rel": "externalvmimports"},
            {"href": "/ovirt-engine/api/externaltemplateimports", "rel": "externaltemplateimports"}
        ]
    }

    # Check if the request has Accept header requesting XML
    if request and "accept" in request.headers:
        accept_header = request.headers["accept"].lower()
        if "application/xml" in accept_header:
            # For XML, we need to convert the complex structure appropriately
            from lxml.etree import Element, SubElement, tostring
            root = Element("api")

            # Add engine_backup element
            engine_backup = SubElement(root, "engine_backup")

            # Add product_info element
            product_info = SubElement(root, "product_info")
            instance_id = SubElement(product_info, "instance_id")
            instance_id.text = payload["product_info"]["instance_id"]
            name_elem = SubElement(product_info, "name")
            name_elem.text = payload["product_info"]["name"]

            version_elem = SubElement(product_info, "version")
            build_elem = SubElement(version_elem, "build")
            build_elem.text = payload["product_info"]["version"]["build"]
            full_version_elem = SubElement(version_elem, "full_version")
            full_version_elem.text = payload["product_info"]["version"]["full_version"]
            major_elem = SubElement(version_elem, "major")
            major_elem.text = payload["product_info"]["version"]["major"]
            minor_elem = SubElement(version_elem, "minor")
            minor_elem.text = payload["product_info"]["version"]["minor"]
            revision_elem = SubElement(version_elem, "revision")
            revision_elem.text = payload["product_info"]["version"]["revision"]

            # Add special_objects element
            special_objects = SubElement(root, "special_objects")
            blank_template = SubElement(special_objects, "blank_template")
            blank_template.set("href", payload["special_objects"]["blank_template"]["href"])
            blank_template.set("id", payload["special_objects"]["blank_template"]["id"])
            root_tag = SubElement(special_objects, "root_tag")
            root_tag.set("href", payload["special_objects"]["root_tag"]["href"])
            root_tag.set("id", payload["special_objects"]["root_tag"]["id"])

            # Add summary element
            summary = SubElement(root, "summary")
            hosts_summary = SubElement(summary, "hosts")
            active_hosts = SubElement(hosts_summary, "active")
            active_hosts.text = payload["summary"]["hosts"]["active"]
            total_hosts = SubElement(hosts_summary, "total")
            total_hosts.text = payload["summary"]["hosts"]["total"]

            storage_domains_summary = SubElement(summary, "storage_domains")
            active_storage = SubElement(storage_domains_summary, "active")
            active_storage.text = payload["summary"]["storage_domains"]["active"]
            total_storage = SubElement(storage_domains_summary, "total")
            total_storage.text = payload["summary"]["storage_domains"]["total"]

            users_summary = SubElement(summary, "users")
            active_users = SubElement(users_summary, "active")
            active_users.text = payload["summary"]["users"]["active"]
            total_users = SubElement(users_summary, "total")
            total_users.text = payload["summary"]["users"]["total"]

            vms_summary = SubElement(summary, "vms")
            active_vms = SubElement(vms_summary, "active")
            active_vms.text = payload["summary"]["vms"]["active"]
            total_vms = SubElement(vms_summary, "total")
            total_vms.text = payload["summary"]["vms"]["total"]

            # Add time element
            time_elem = SubElement(root, "time")
            time_elem.text = str(payload["time"])

            # Add authenticated_user element
            authenticated_user = SubElement(root, "authenticated_user")
            authenticated_user.set("href", payload["authenticated_user"]["href"])
            authenticated_user.set("id", payload["authenticated_user"]["id"])

            # Add effective_user element
            effective_user = SubElement(root, "effective_user")
            effective_user.set("href", payload["effective_user"]["href"])
            effective_user.set("id", payload["effective_user"]["id"])

            # Add links
            for link_data in payload["link"]:
                link_elem = SubElement(root, "link")
                link_elem.set("href", link_data["href"])
                link_elem.set("rel", link_data["rel"])

            return Response(
                content=tostring(root, xml_declaration=True, encoding="utf-8", pretty_print=True),
                media_type="application/xml",
                status_code=200
            )

    # Default to JSON response
    return json_response(payload)
