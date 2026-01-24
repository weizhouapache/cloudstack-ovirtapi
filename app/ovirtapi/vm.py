from fastapi import APIRouter, Request, HTTPException, Response
from app.cloudstack.client import cs_request
from app.utils.response_builder import create_response
from app.utils.async_job import wait_for_job, get_job_id
from app.config import SERVER

import json

router = APIRouter()
api_prefix = SERVER.get("path", "/ovirt-engine") + "/api"

def cs_vm_to_ovirt(vm: dict) -> dict:
    """
    Convert a CloudStack VM dict to an oVirt-compatible VM payload with full details.
    """

    vm_id = vm.get("id", "NULL")

    # Use match/case to determine VM status
    vm_state = vm.get("state", "down").lower()
    match vm_state:
        case "running":
            vm_status = "up"
        case "stopped" | "error" | "shutdown":
            vm_status = "down"
        case "stopping":
            vm_status = "powering_down"
        case "starting":
            vm_status = "powering_up"
        case "migrating":
            vm_status = "migrating"
        case "restoring":
            vm_status = "restoring_state"
        case "destroyed" | "expunging":
            vm_status = "down"
        case "unknown":
            vm_status = "unknown"
        case _:
            vm_status = vm_state

    # Create the detailed VM structure as specified
    detailed_vm = {
        "status": vm_status,
        "disk_attachments": {
            "disk_attachment": [
                {
                    "active": "true",
                    "bootable": "true",
                    "interface": "virtio_scsi",
                    "logical_name": "/dev/sda",
                    "pass_discard": "false",
                    "read_only": "false",
                    "uses_scsi_reservation": "false",
                    "disk": {
                        "actual_size": "1239158784",
                        "alias": "Veeam_KvmBackupDisk_" + vm.get("name", "test-vm"),
                        "backup": "none",
                        "content_type": "data",
                        "format": "cow",
                        "image_id": "fa25e57f-f666-4e05-aa5d-c9ab66a0e232",
                        "propagate_errors": "false",
                        "provisioned_size": "107374182400",
                        "qcow_version": "qcow2_v3",
                        "shareable": "false",
                        "sparse": "true",
                        "status": "ok",
                        "storage_type": "image",
                        "total_size": "1239158784",
                        "wipe_after_delete": "false",
                        "disk_profile": {
                            "href": "/ovirt-engine/api/diskprofiles/97588d4a-0219-4ff0-8792-375b61976c1e",
                            "id": "97588d4a-0219-4ff0-8792-375b61976c1e"
                        },
                        "quota": {
                            "href": "/ovirt-engine/api/datacenters/91f4d826-e4d5-11f0-bd93-00163e6c35f4/quotas/95e46398-e4d5-11f0-bb71-00163e6c35f4",
                            "id": "95e46398-e4d5-11f0-bb71-00163e6c35f4"
                        },
                        "storage_domains": {
                            "storage_domain": [
                                {
                                    "href": "/ovirt-engine/api/storagedomains/41609681-c92a-410a-bcc2-5b5e1305cdd1",
                                    "id": "41609681-c92a-410a-bcc2-5b5e1305cdd1"
                                }
                            ]
                        },
                        "actions": {
                            "link": [
                                {
                                    "href": f"/ovirt-engine/api/disks/b4ace9df-f1fb-4595-8e87-b4c43f13035a/reduce",
                                    "rel": "reduce"
                                },
                                {
                                    "href": f"/ovirt-engine/api/disks/b4ace9df-f1fb-4595-8e87-b4c43f13035a/copy",
                                    "rel": "copy"
                                },
                                {
                                    "href": f"/ovirt-engine/api/disks/b4ace9df-f1fb-4595-8e87-b4c43f13035a/export",
                                    "rel": "export"
                                },
                                {
                                    "href": f"/ovirt-engine/api/disks/b4ace9df-f1fb-4595-8e87-b4c43f13035a/move",
                                    "rel": "move"
                                },
                                {
                                    "href": f"/ovirt-engine/api/disks/b4ace9df-f1fb-4595-8e87-b4c43f13035a/refreshlun",
                                    "rel": "refreshlun"
                                },
                                {
                                    "href": f"/ovirt-engine/api/disks/b4ace9df-f1fb-4595-8e87-b4c43f13035a/convert",
                                    "rel": "convert"
                                },
                                {
                                    "href": f"/ovirt-engine/api/disks/b4ace9df-f1fb-4595-8e87-b4c43f13035a/sparsify",
                                    "rel": "sparsify"
                                }
                            ]
                        },
                        "name": "Veeam_KvmBackupDisk_" + vm.get("name", "test-vm"),
                        "description": "",
                        "link": [
                            {
                                "href": "/ovirt-engine/api/disks/b4ace9df-f1fb-4595-8e87-b4c43f13035a/permissions",
                                "rel": "permissions"
                            },
                            {
                                "href": "/ovirt-engine/api/disks/b4ace9df-f1fb-4595-8e87-b4c43f13035a/disksnapshots",
                                "rel": "disksnapshots"
                            },
                            {
                                "href": "/ovirt-engine/api/disks/b4ace9df-f1fb-4595-8e87-b4c43f13035a/statistics",
                                "rel": "statistics"
                            }
                        ],
                        "href": "/ovirt-engine/api/disks/b4ace9df-f1fb-4595-8e87-b4c43f13035a",
                        "id": "b4ace9df-f1fb-4595-8e87-b4c43f13035a"
                    },
                    "vm": {
                        "href": f"/ovirt-engine/api/vms/{vm_id}",
                        "id": vm_id
                    },
                    "link": [],
                    "href": f"/ovirt-engine/api/vms/{vm_id}/diskattachments/b4ace9df-f1fb-4595-8e87-b4c43f13035a",
                    "id": "b4ace9df-f1fb-4595-8e87-b4c43f13035a"
                }
            ]
        },
        "nics": {
            "nic": [
                {
                    "interface": "virtio",
                    "linked": "true",
                    "mac": {
                        "address": "56:6f:9f:c0:00:06"
                    },
                    "plugged": "true",
                    "synced": "true",
                    "reported_devices": {
                        "reported_device": [
                            {
                                "ips": {
                                    "ip": [
                                        {
                                            "address": "10.0.113.115",
                                            "version": "v4"
                                        }
                                    ]
                                },
                                "mac": {
                                    "address": "56:6f:9f:c0:00:06"
                                },
                                "type": "network",
                                "vm": {
                                    "href": f"/ovirt-engine/api/vms/{vm_id}",
                                    "id": vm_id
                                },
                                "name": "eth0",
                                "description": "guest reported data",
                                "href": f"/ovirt-engine/api/vms/{vm_id}/reporteddevices/65746830-3536-3a36-663a-39663a63303a",
                                "id": "65746830-3536-3a36-663a-39663a63303a"
                            }
                        ]
                    },
                    "vnic_profile": {
                        "href": "/ovirt-engine/api/vnicprofiles/0000000a-000a-000a-000a-000000000398",
                        "id": "0000000a-000a-000a-000a-000000000398"
                    },
                    "actions": {
                        "link": [
                            {
                                "href": f"/ovirt-engine/api/vms/{vm_id}/nics/6215ed25-a865-41b7-972e-9b9a0401bdc1/activate",
                                "rel": "activate"
                            },
                            {
                                "href": f"/ovirt-engine/api/vms/{vm_id}/nics/6215ed25-a865-41b7-972e-9b9a0401bdc1/deactivate",
                                "rel": "deactivate"
                            }
                        ]
                    },
                    "name": "nic1",
                    "vm": {
                        "href": f"/ovirt-engine/api/vms/{vm_id}",
                        "id": vm_id
                    },
                    "link": [
                        {
                            "href": f"/ovirt-engine/api/vms/{vm_id}/nics/6215ed25-a865-41b7-972e-9b9a0401bdc1/reporteddevices",
                            "rel": "reporteddevices"
                        },
                        {
                            "href": f"/ovirt-engine/api/vms/{vm_id}/nics/6215ed25-a865-41b7-972e-9b9a0401bdc1/networkfilterparameters",
                            "rel": "networkfilterparameters"
                        },
                        {
                            "href": f"/ovirt-engine/api/vms/{vm_id}/nics/6215ed25-a865-41b7-972e-9b9a0401bdc1/statistics",
                            "rel": "statistics"
                        }
                    ],
                    "href": f"/ovirt-engine/api/vms/{vm_id}/nics/6215ed25-a865-41b7-972e-9b9a0401bdc1",
                    "id": "6215ed25-a865-41b7-972e-9b9a0401bdc1"
                }
            ]
        },
        "original_template": {
            "href": "/ovirt-engine/api/templates/00000000-0000-0000-0000-000000000000",
            "id": "00000000-0000-0000-0000-000000000000"
        },
        "tags": {},
        "template": {
            "href": "/ovirt-engine/api/templates/00000000-0000-0000-0000-000000000000",
            "id": "00000000-0000-0000-0000-000000000000"
        },
        "actions": {
            "link": [
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/detach",
                    "rel": "detach"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/shutdown",
                    "rel": "shutdown"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/start",
                    "rel": "start"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/stop",
                    "rel": "stop"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/suspend",
                    "rel": "suspend"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/reset",
                    "rel": "reset"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/autopincpuandnumanodes",
                    "rel": "autopincpuandnumanodes"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/reordermacaddresses",
                    "rel": "reordermacaddresses"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/thawfilesystems",
                    "rel": "thawfilesystems"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/undosnapshot",
                    "rel": "undosnapshot"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/screenshot",
                    "rel": "screenshot"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/ticket",
                    "rel": "ticket"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/reboot",
                    "rel": "reboot"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/migrate",
                    "rel": "migrate"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/cancelmigration",
                    "rel": "cancelmigration"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/commitsnapshot",
                    "rel": "commitsnapshot"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/clone",
                    "rel": "clone"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/freezefilesystems",
                    "rel": "freezefilesystems"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/logon",
                    "rel": "logon"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/maintenance",
                    "rel": "maintenance"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/previewsnapshot",
                    "rel": "previewsnapshot"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/export",
                    "rel": "export"
                }
            ]
        },
        "name": vm.get("name", "veeam-worker"),
        "description": vm.get("displayname", "Created by .\\Administrator at 12/29/2025 10:55 PM."),
        "comment": "",
        "bios": {
            "boot_menu": {
                "enabled": "false"
            },
            "type": "q35_secure_boot"
        },
        "cpu": {
            "architecture": "x86_64",
            "topology": {
                "cores": "1",
                "sockets": "6",
                "threads": "1"
            }
        },
        "display": {
            "allow_override": "false",
            "copy_paste_enabled": "true",
            "disconnect_action": "LOCK_SCREEN",
            "disconnect_action_delay": "0",
            "file_transfer_enabled": "true",
            "monitors": "1",
            "smartcard_enabled": "false",
            "type": "vnc",
            "video_type": "vga"
        },
        "io": {
            "threads": "1"
        },
        "memory": str(vm.get("memory", 6442450944)),  # Default to 6GB
        "migration": {
            "auto_converge": "inherit",
            "compressed": "inherit",
            "encrypted": "inherit",
            "parallel_migrations_policy": "inherit"
        },
        "origin": "ovirt",
        "os": {
            "boot": {
                "devices": {
                    "device": [
                        "hd"
                    ]
                }
            },
            "type": vm.get("ostype", "other")
        },
        "sso": {
            "methods": {
                "method": [
                    {
                        "id": "guest_agent"
                    }
                ]
            }
        },
        "stateless": "false",
        "type": "desktop",
        "usb": {
            "enabled": "false"
        },
        "cluster": {
            "href": "/ovirt-engine/api/clusters/91f79836-e4d5-11f0-884a-00163e6c35f4",
            "id": "91f79836-e4d5-11f0-884a-00163e6c35f4"
        },
        "quota": {
            "id": "95e46398-e4d5-11f0-bb71-00163e6c35f4"
        },
        "link": [
            {
                "href": f"/ovirt-engine/api/vms/{vm_id}/snapshots",
                "rel": "snapshots"
            },
            {
                "href": f"/ovirt-engine/api/vms/{vm_id}/applications",
                "rel": "applications"
            },
            {
                "href": f"/ovirt-engine/api/vms/{vm_id}/hostdevices",
                "rel": "hostdevices"
            },
            {
                "href": f"/ovirt-engine/api/vms/{vm_id}/reporteddevices",
                "rel": "reporteddevices"
            },
            {
                "href": f"/ovirt-engine/api/vms/{vm_id}/sessions",
                "rel": "sessions"
            },
            {
                "href": f"/ovirt-engine/api/vms/{vm_id}/backups",
                "rel": "backups"
            },
            {
                "href": f"/ovirt-engine/api/vms/{vm_id}/checkpoints",
                "rel": "checkpoints"
            },
            {
                "href": f"/ovirt-engine/api/vms/{vm_id}/watchdogs",
                "rel": "watchdogs"
            },
            {
                "href": f"/ovirt-engine/api/vms/{vm_id}/graphicsconsoles",
                "rel": "graphicsconsoles"
            },
            {
                "href": f"/ovirt-engine/api/vms/{vm_id}/diskattachments",
                "rel": "diskattachments"
            },
            {
                "href": f"/ovirt-engine/api/vms/{vm_id}/cdroms",
                "rel": "cdroms"
            },
            {
                "href": f"/ovirt-engine/api/vms/{vm_id}/mediateddevices",
                "rel": "mediateddevices"
            },
            {
                "href": f"/ovirt-engine/api/vms/{vm_id}/nics",
                "rel": "nics"
            },
            {
                "href": f"/ovirt-engine/api/vms/{vm_id}/numanodes",
                "rel": "numanodes"
            },
            {
                "href": f"/ovirt-engine/api/vms/{vm_id}/katelloerrata",
                "rel": "katelloerrata"
            },
            {
                "href": f"/ovirt-engine/api/vms/{vm_id}/permissions",
                "rel": "permissions"
            },
            {
                "href": f"/ovirt-engine/api/vms/{vm_id}/tags",
                "rel": "tags"
            },
            {
                "href": f"/ovirt-engine/api/vms/{vm_id}/affinitylabels",
                "rel": "affinitylabels"
            },
            {
                "href": f"/ovirt-engine/api/vms/{vm_id}/statistics",
                "rel": "statistics"
            }
        ],
        "href": f"/ovirt-engine/api/vms/{vm_id}",
        "id": vm_id,
        "auto_pinning_policy": "disabled",
        "cpu_pinning_policy": "none",
        "cpu_shares": "0",
        "creation_time": 1767630835851,
        "delete_protected": "false",
        "high_availability": {
            "enabled": "false",
            "priority": "0"
        },
        "large_icon": {
            "href": "/ovirt-engine/api/icons/4d71f9a0-24aa-4dea-aa40-da300e0f2e99",
            "id": "4d71f9a0-24aa-4dea-aa40-da300e0f2e99"
        },
        "memory_policy": {
            "ballooning": "true",
            "guaranteed": str(vm.get("memory", 6442450944)),
            "max": str(vm.get("memory", 6442450944))
        },
        "migration_downtime": "0",
        "multi_queues_enabled": "true",
        "placement_policy": {
            "affinity": "migratable"
        },
        "small_icon": {
            "href": "/ovirt-engine/api/icons/60d8af9d-1d9d-4f85-8fe5-e3385145d7d8",
            "id": "60d8af9d-1d9d-4f85-8fe5-e3385145d7d8"
        },
        "start_paused": "false",
        "storage_error_resume_behaviour": "auto_resume",
        "time_zone": {
            "name": "Etc/GMT"
        },
        "virtio_scsi_multi_queues_enabled": "false",
        "cpu_profile": {
            "href": "/ovirt-engine/api/cpuprofiles/58ca604e-01a7-003f-01de-000000000250",
            "id": "58ca604e-01a7-003f-01de-000000000250"
        }
    }

    # Add host information if host_id is present in the VM data
    host_id = vm.get("hostid")
    if host_id:
        detailed_vm["host"] = {
            "href": f"/ovirt-engine/api/hosts/{host_id}",
            "id": host_id
        }

    return detailed_vm

@router.get("/vms")
async def list_vms(request: Request):
    data = await cs_request(request,
        "listVirtualMachines",
        {}
    )
    vms = data["listvirtualmachinesresponse"].get("virtualmachine", [])

    payload = [cs_vm_to_ovirt(vm) for vm in vms]

    return create_response(request, "vms", payload)


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

    return create_response(request, "vm", payload)

@router.put("/vms/{vm_id}")
async def update_vm(vm_id: str, request: Request):
    """
    Updates a VM with the provided parameters.

    Gets the request body to extract VM update parameters and calls CloudStack's updateVirtualMachine API.
    """
    try:
        # Get the request body to extract VM update parameters
        body_bytes = await request.body()
        body_str = body_bytes.decode("utf-8")
        vm_update_params = json.loads(body_str) if body_str else {}

        # Get current VM data to confirm it exists
        data = await cs_request(request,
            "listVirtualMachines",
            {"id": vm_id}
        )
        vms = data["listvirtualmachinesresponse"].get("virtualmachine", [])

        if not vms:
            raise HTTPException(status_code=404, detail="VM not found")

        # Prepare parameters for CloudStack updateVirtualMachine API
        cs_params = {"id": vm_id}

        # Extract update parameters from the request
        if "name" in vm_update_params:
            cs_params["name"] = vm_update_params["name"]
        if "displayname" in vm_update_params:
            cs_params["displayname"] = vm_update_params["displayname"]
        if "group" in vm_update_params:
            cs_params["group"] = vm_update_params["group"]
        if "haenable" in vm_update_params:
            cs_params["haenable"] = vm_update_params["haenable"]
        if "hakeyword" in vm_update_params:
            cs_params["hakeyword"] = vm_update_params["hakeyword"]
        if "ostypeid" in vm_update_params:
            cs_params["ostypeid"] = vm_update_params["ostypeid"]
        if "securitygroupenabled" in vm_update_params:
            cs_params["securitygroupenabled"] = vm_update_params["securitygroupenabled"]
        if "userdata" in vm_update_params:
            # For userdata, we need to encode it in base64 as required by CloudStack
            import base64
            encoded_userdata = base64.b64encode(vm_update_params["userdata"].encode()).decode()
            cs_params["userdata"] = encoded_userdata

        # Call CloudStack API to update the VM
        update_data = await cs_request(request, "updateVirtualMachine", cs_params)

        vm = update_data["updatevirtualmachineresponse"].get("virtualmachine", [])

        # If we don't have VM data at this point, there was an issue
        if not vm:
            raise HTTPException(status_code=500, detail="Failed to update VM - no VM returned from CloudStack")

        # Convert to oVirt format and return
        payload = cs_vm_to_ovirt(vm)

        return create_response(request, "vm", payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in request body")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update VM: {str(e)}")

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
        raise HTTPException(status_code=400, detail="Failed to start VM")

    job = {
        "id": job_id,
        "href": f"{api_prefix}/jobs/{job_id}"
    }

    payload = {
        "job": job,
        "status": "complete",
        "vm": cs_vm_to_ovirt(vm)
    }
    return create_response(request, "vm", payload)

@router.post("/vms/{vm_id}/stop")
async def stop_vm(vm_id: str, request: Request):
    """Forcefully stop a running VM (does not gracefully shutdown)."""
    data = await cs_request(request, "stopVirtualMachine", {"id": vm_id, "forced": "true"})

    # TODO: get force from POST data, to stop the VM even if a backup is running for it
    # <action>
    # <force>true</force>
    # </action>

    # Check for job response (async)
    job_id = get_job_id(data)
    if job_id:
        # Wait for async job to complete
        job_result = await wait_for_job(request, job_id)
        vm = job_result.get("virtualmachine", {})
    else:
        raise HTTPException(status_code=400, detail="Failed to stop VM")

    job = {
        "id": job_id,
        "href": f"{api_prefix}/jobs/{job_id}"
    }
    payload = {
        "job": job,
        "status": "complete",
        "vm": cs_vm_to_ovirt(vm)
    }
    return create_response(request, "vm", payload)

@router.post("/vms/{vm_id}/shutdown")
async def shutdown_vm(vm_id: str, request: Request):
    """Gracefully shutdown a running VM."""
    data = await cs_request(request, "stopVirtualMachine", {"id": vm_id, "forced": "false"})

    # TODO: get force from POST data, to stop the VM even if a backup is running for it
    # <action>
    # <force>true</force>
    # </action>

    # Check for job response (async)
    job_id = get_job_id(data)
    if job_id:
        # Wait for async job to complete
        job_result = await wait_for_job(request, job_id)
        vm = job_result.get("virtualmachine", {})
    else:
        raise HTTPException(status_code=400, detail="Failed to shutdown VM")

    job = {
        "id": job_id,
        "href": f"{api_prefix}/jobs/{job_id}"
    }
    payload = {
        "job": job,
        "status": "complete",
        "vm": cs_vm_to_ovirt(vm)
    }
    return create_response(request, "vm", payload)

@router.post("/vms")
async def create_vm(request: Request):
    """
    Creates a new VM from the provided configuration.

    Expects a JSON payload with VM parameters.
    """
    try:
        # Get the request body to extract VM parameters
        body_bytes = await request.body()
        body_str = body_bytes.decode("utf-8")
        vm_params = json.loads(body_str) if body_str else {}

        # Extract VM parameters from the request
        vm_name = vm_params.get("name", "new-vm")
        vm_description = vm_params.get("description", "Created via API")
        vm_memory = vm_params.get("memory", 1073741824)  # Default 1GB
        vm_stateless = vm_params.get("stateless", False)
        vm_type = vm_params.get("type", "server")

        # Extract CPU information
        cpu_info = vm_params.get("cpu", {})
        cpu_arch = cpu_info.get("architecture", "x86_64")
        cpu_topology = cpu_info.get("topology", {})
        cpu_cores = cpu_topology.get("cores", 1)
        cpu_sockets = cpu_topology.get("sockets", 1)
        cpu_threads = cpu_topology.get("threads", 1)

        # Extract cluster information
        cluster_info = vm_params.get("cluster", {})
        cluster_id = cluster_info.get("id", "")

        # Extract BIOS settings
        bios_info = vm_params.get("bios", {})
        bios_type = bios_info.get("type", "q35_secure_boot")

        # Extract memory policy
        memory_policy = vm_params.get("memory_policy", {})
        memory_guaranteed = memory_policy.get("guaranteed", vm_memory)
        memory_max = memory_policy.get("max", vm_memory)

        # Prepare parameters for CloudStack deployVirtualMachine API
        # First, we need to determine appropriate service offering based on CPU and memory
        # For now, we'll use a default service offering, but in a real implementation
        # we would need to query CloudStack for an appropriate offering

        # Find or create the service offering with name "Veeam Custom"
        # First, try to find the service offering by name
        try:
            offering_data = await cs_request(request, "listServiceOfferings", {"name": "Veeam Custom"})
            offerings = offering_data.get("listserviceofferingsresponse", {}).get("serviceoffering", [])

            if offerings:
                # Use existing service offering
                service_offering_id = offerings[0]["id"]
            else:
                # Service offering doesn't exist, create a custom one
                # Calculate CPU cores from topology
                cpu_cores_total = cpu_cores * cpu_sockets  # Total cores based on topology

                # Create custom service offering
                create_offering_params = {
                    "name": "Veeam Custom",
                    "displaytext": "Custom service offering for Veeam backups",
                    "customized": "true",
                }

                # Create the service offering
                create_result = await cs_request(request, "createServiceOffering", create_offering_params, method = "POST")
                service_offering_id = create_result["createserviceofferingresponse"]["serviceoffering"]["id"]
        except Exception as e:
            raise HTTPException(status_code=500, detail="Failed to find or create service offering 'Veeam Custom'")

        # Extract initialization parameters if provided
        initialization = vm_params.get("initialization", {})
        custom_script = initialization.get("custom_script", "")

        # TODO: remove this
        cpu_cores_total = 2
        memory_guaranteed = str(4096 * 1024 * 1024)

        cs_params = {
            "name": vm_name,
            "displayname": vm_description,
            "serviceofferingid": service_offering_id,
            "hypervisor": "KVM",
            "dummy": True,
            "details[0].guest.cpu.model": "host_passthrough",
            "details[0].cpuNumber": cpu_cores_total,          # total CPU cores
            "details[0].cpuSpeed": 1000,        # hardcoded
            "details[0].memory": int(int(memory_guaranteed) / 1024 / 1024)  # in MiB
        }

        # Add user data (custom script) if provided
        if custom_script:
            # CloudStack supports user data via the 'userdata' parameter
            import base64
            # Encode the custom script in base64 as required by CloudStack
            encoded_userdata = base64.b64encode(custom_script.encode()).decode()
            cs_params["userdata"] = encoded_userdata

        # Add zone/cluster information if provided
        if cluster_id:
            # If cluster_id is provided, we can use it as zoneid for CloudStack
            # Alternatively, we might need to look up the actual zone ID
            try:
                cluster_data = await cs_request(request, "listClusters", {"id": cluster_id})
                clusters = cluster_data["listclustersresponse"].get("cluster", [])
                if clusters:
                    # Use the zone ID from the cluster
                    zone_id = clusters[0].get("zoneid")
                    if zone_id:
                        cs_params["zoneid"] = zone_id
                    else:
                        # If no zone ID found in cluster, use cluster_id as zoneid
                        cs_params["zoneid"] = cluster_id
                else:
                    # If cluster not found, use cluster_id as zoneid
                    cs_params["zoneid"] = cluster_id
            except:
                # If there's an error looking up the cluster, use cluster_id as zoneid
                cs_params["zoneid"] = cluster_id

        # Call CloudStack API to create the VM
        data = await cs_request(request, "deployVirtualMachine", cs_params, method="POST")

        # Handle potential async job response
        if "jobid" in data.get("deployvirtualmachineresponse", {}):
            # Async job was started, need to wait for completion
            job_id = data["deployvirtualmachineresponse"]["jobid"]
            job_result = await wait_for_job(request, job_id)
            vm = job_result.get("virtualmachine", {})
        else:
            raise HTTPException(status_code=500, detail="Failed to create VM - job failed")

        # If we don't have a VM at this point, there was an issue
        if not vm:
            raise HTTPException(status_code=500, detail="Failed to create VM - no VM returned from CloudStack")

        # Convert to oVirt format and return
        payload = cs_vm_to_ovirt(vm)

        return create_response(request, "vm", payload)

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in request body")
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing required parameter: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create VM: {str(e)}")


@router.delete("/vms/{vm_id}")
async def delete_vm(vm_id: str, request: Request):
    """
    Deletes a virtual machine.

    Supports the detach_only parameter to control whether the VM is only detached or fully destroyed.
    """
    # Parse query parameters to check for detach_only
    detach_only = request.query_params.get("detach_only", "false").lower() == "true"
    # expunge = str(not detach_only).lower()

    # Prepare parameters for CloudStack destroyVirtualMachine API
    # If detach_only is true, we might need to use a different approach or parameter
    # In CloudStack, the expunge parameter controls whether to fully destroy or just stop
    cs_params = {
        "id": vm_id,
        "expunge": True
    }

    # Call CloudStack API to destroy the VM
    data = await cs_request(request, "destroyVirtualMachine", cs_params)

    # Check for job response (async)
    job_id = get_job_id(data)

    # Wait for async job to complete
    job_result = await wait_for_job(request, job_id)

    return Response(status_code=200)


@router.get("/vms/{vm_id}/diskattachments")
async def get_vm_disk_attachment(vm_id: str, request: Request):
    """
    Gets the disk attachments for a specific VM.
    """
    # First, get the VM to confirm it exists
    data = await cs_request(request, "listVirtualMachines", {"id": vm_id})
    vms = data["listvirtualmachinesresponse"].get("virtualmachine", [])

    if not vms:
        raise HTTPException(status_code=404, detail="VM not found")

    # Get volumes attached to this VM
    volumes_data = await cs_request(request, "listVolumes", {"virtualmachineid": vm_id})
    volumes = volumes_data["listvolumesresponse"].get("volume", [])

    # Convert volumes to disk attachment format
    disk_attachments = []
    for i, volume in enumerate(volumes):
        volume_id = volume.get("id", f"disk-attachment-{i}")
        # Create a disk attachment entry for each volume
        disk_attachment = {
            "id": volume_id,
            "href": f"/ovirt-engine/api/vms/{vm_id}/diskattachments/{volume_id}",
            "active": "true",
            "bootable": str(volume.get("isbootable", False)).lower(),
            "interface": "virtio",  # Default interface
            "pass_discard": "false",
            "read_only": "false",
            "uses_scsi_reservation": "false",
            "vm": {
                "id": vm_id,
                "href": f"/ovirt-engine/api/vms/{vm_id}"
            },
            "disk": {
                "id": volume.get("id", f"disk-{i}"),
                "href": f"/ovirt-engine/api/disks/{volume_id}",
                "name": volume.get("name", volume_id),
                "actual_size": str(volume.get("size", 0)),
                "provisioned_size": str(volume.get("size", 0)),
                "status": "ok" if volume.get("state") == "Ready" else "locked",
                "sparse": str(volume.get("issparse", True)).lower(),
                "bootable": str(volume.get("isbootable", False)).lower(),
                "propagate_errors": "false",
                "wipe_after_delete": "false",
                "content_type": "data",
                "format": "cow",
                "storage_type": "image"
            }
        }
        disk_attachments.append(disk_attachment)

    # Return the disk attachments as a collection
    payload = {"disk_attachment": disk_attachments}
    return create_response(request, "disk_attachment", payload)
