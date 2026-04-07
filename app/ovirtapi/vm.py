from fastapi import APIRouter, Request, HTTPException, Response
from app.cloudstack.client import cs_request
from app.utils.response_builder import create_response
from app.utils.async_job import wait_for_job, get_job_id
from app.config import SERVER
from app.utils.logging_config import logger

import json
import time
from typing import Optional

router = APIRouter()
api_prefix = SERVER.get("path", "/ovirt-engine") + "/api"

async def cs_vm_to_ovirt(vm: dict, request: Request) -> dict:
    """
    Convert a CloudStack VM dict to an oVirt-compatible VM payload with full details.
    """

    vm_id = vm.get("id")

    # get request parameter all_content
    all_content = request.query_params.get("all_content", "false").lower() == "true"

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

    # Get volumes attached to this VM to extract storage information
    try:
        volumes_data = await cs_request(request, "listVolumes", {"virtualmachineid": vm_id})
        volumes = volumes_data["listvolumesresponse"].get("volume", [])
    except:
        # If we can't get volumes, use empty list
        volumes = []

    # Create disk attachments with dynamic storage domain IDs
    disk_attachments = []
    for i, volume in enumerate(volumes):
        # Get storage domain ID from the volume
        storage_id = volume.get("storageid", f"dynamic-storage-{i}")

        disk_attachment = {
            "active": "true",
            "bootable": str(volume.get("isbootable", True)).lower(),
            "interface": "virtio_scsi",
            "logical_name": f"/dev/sd{chr(ord('a') + i)}",
            "pass_discard": "false",
            "read_only": "false",
            "uses_scsi_reservation": "false",
            "disk": {
                "actual_size": int(volume.get("size", "1239158784")),
                "alias": volume.get("name", f"Veeam_KvmBackupDisk_{vm.get('name', 'test-vm')}"),
                "backup": "none",
                "content_type": "data",
                "format": "cow",
                "image_id": volume.get("id"),
                "initial_size": int(volume.get("size", "1239158784")),
                "propagate_errors": "false",
                "provisioned_size": int(volume.get("size", "107374182400")),
                "qcow_version": "qcow2_v3",
                "shareable": "false",
                "sparse": str(volume.get("issparse", True)).lower(),
                "status": "ok",
                "storage_type": "image",
                "total_size": int(volume.get("size", "1239158784")),
                "wipe_after_delete": "false",
                "disk_profile": {
                    "href": f"/ovirt-engine/api/diskprofiles/{volume.get('id')}",
                    "id": volume.get('id')
                },
                "quota": {
                    "href": f"/ovirt-engine/api/datacenters/{vm.get('zoneid')}/quotas/{vm.get('zoneid')}",
                    "id": f"{vm.get('zoneid')}"
                },
                "storage_domains": {
                    "storage_domain": [
                        {
                            "href": f"/ovirt-engine/api/storagedomains/{storage_id}",
                            "id": storage_id
                        }
                    ]
                },
                "actions": {
                    "link": [
                        {
                            "href": f"/ovirt-engine/api/disks/{volume.get('id')}/reduce",
                            "rel": "reduce"
                        },
                        {
                            "href": f"/ovirt-engine/api/disks/{volume.get('id')}/copy",
                            "rel": "copy"
                        },
                        {
                            "href": f"/ovirt-engine/api/disks/{volume.get('id')}/export",
                            "rel": "export"
                        },
                        {
                            "href": f"/ovirt-engine/api/disks/{volume.get('id')}/move",
                            "rel": "move"
                        },
                        {
                            "href": f"/ovirt-engine/api/disks/{volume.get('id')}/refreshlun",
                            "rel": "refreshlun"
                        },
                        {
                            "href": f"/ovirt-engine/api/disks/{volume.get('id')}/convert",
                            "rel": "convert"
                        },
                        {
                            "href": f"/ovirt-engine/api/disks/{volume.get('id')}/sparsify",
                            "rel": "sparsify"
                        }
                    ]
                },
                "name": volume.get("name", f"Veeam_KvmBackupDisk_{vm.get('name', 'test-vm')}"),
                "description": volume.get("displaytext", ""),
                "link": [
                    {
                        "href": f"/ovirt-engine/api/disks/{volume.get('id')}/permissions",
                        "rel": "permissions"
                    },
                    {
                        "href": f"/ovirt-engine/api/disks/{volume.get('id')}/disksnapshots",
                        "rel": "disksnapshots"
                    },
                    {
                        "href": f"/ovirt-engine/api/disks/{volume.get('id')}/statistics",
                        "rel": "statistics"
                    }
                ],
                "href": f"/ovirt-engine/api/disks/{volume.get('id')}",
                "id": volume.get("id", f"dynamic-disk-{i}")
            },
            "vm": {
                "href": f"/ovirt-engine/api/vms/{vm_id}",
                "id": vm_id
            },
            "link": [],
            "href": f"/ovirt-engine/api/vms/{vm_id}/diskattachments/{volume.get('id')}",
            "id": volume.get("id", f"dynamic-disk-{i}")
        }
        disk_attachments.append(disk_attachment)

    # Generate NICs dynamically based on VM data
    vm_nics = vm.get("nic", [])
    nics = []
    for i, nic in enumerate(vm_nics):
        nic_id = nic.get("id", f"nic-{i}")
        mac_address = nic.get("macaddress")

        nic_obj = {
            "interface": "virtio",  # Default interface type in CloudStack
            "linked": "true",
            "mac": {
                "address": mac_address
            },
            "plugged": "true",
            "synced": "true",
            "reported_devices": {
                "reported_device": [
                    {
                        "ips": {
                            "ip": [
                                {
                                    "address": nic.get("ipaddress", ""),
                                    "version": "v4"
                                }
                            ]
                        },
                        "mac": {
                            "address": mac_address
                        },
                        "type": "network",
                        "vm": {
                            "href": f"/ovirt-engine/api/vms/{vm_id}",
                            "id": vm_id
                        },
                        "name": f"eth{nic.get('deviceid', i)}",
                        "description": "guest reported data",
                        "href": f"/ovirt-engine/api/vms/{vm_id}/reporteddevices/{nic_id}",
                        "id": nic_id
                    }
                ]
            },
            "vnic_profile": {
                "href": f"/ovirt-engine/api/vnicprofiles/{nic.get('networkid', f'dynamic-vnic-{i}')}",
                "id": nic.get('networkid', f"dynamic-vnic-{i}")
            },
            "actions": {
                "link": [
                    {
                        "href": f"/ovirt-engine/api/vms/{vm_id}/nics/{nic_id}/activate",
                        "rel": "activate"
                    },
                    {
                        "href": f"/ovirt-engine/api/vms/{vm_id}/nics/{nic_id}/deactivate",
                        "rel": "deactivate"
                    }
                ]
            },
            "name": f"nic{i+1}",
            "vm": {
                "href": f"/ovirt-engine/api/vms/{vm_id}",
                "id": vm_id
            },
            "link": [
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/nics/{nic_id}/reporteddevices",
                    "rel": "reporteddevices"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/nics/{nic_id}/networkfilterparameters",
                    "rel": "networkfilterparameters"
                },
                {
                    "href": f"/ovirt-engine/api/vms/{vm_id}/nics/{nic_id}/statistics",
                    "rel": "statistics"
                }
            ],
            "href": f"/ovirt-engine/api/vms/{vm_id}/nics/{nic_id}",
            "id": nic_id
        }
        nics.append(nic_obj)

    # Create the detailed VM structure as specified
    detailed_vm = {
        "status": vm_status,
        "disk_attachments": {
            "disk_attachment": disk_attachments
        },
        "nics": {
            "nic": nics
        },
        "original_template": {
            "href": f"/ovirt-engine/api/templates/{vm.get('templateid', 'dynamic-template')}",
            "id": vm.get('templateid', 'dynamic-template')
        },
        "tags": {},
        "template": {
            "href": f"/ovirt-engine/api/templates/{vm.get('templateid', 'dynamic-template')}",
            "id": vm.get('templateid', 'dynamic-template')
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
        "name": vm.get("instancename", "veeam-worker"),
        "description": vm.get("displayname", vm.get("name")),
        "comment": "",
        "bios": {
            "boot_menu": {
                "enabled": "false"
            },
            "type": "q35_ovmf"
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
            "address": "127.0.0.1",
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
        "memory": int(vm.get("memory", "6144")) * 1024 * 1024,  # Default to 6GB
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
        "type": "server",
        "usb": {
            "enabled": "false"
        },
        "cluster": {
            "href": f"/ovirt-engine/api/clusters/{vm.get('clusterid')}",
            "id": vm.get('clusterid')
        },
        "quota": {
            "id": vm.get('zoneid')
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
        "creation_time": int(time.time()),
        "delete_protected": "false",
        "high_availability": {
            "enabled": "false",
            "priority": "0"
        },
        "large_icon": {
            "href": f"/ovirt-engine/api/icons/{vm.get('iconid', 'dynamic-large-icon')}",
            "id": vm.get('iconid', 'dynamic-large-icon')
        },
        "memory_policy": {
            "ballooning": "true",
            "guaranteed": int(vm.get("memory", "1024")) * 1024 * 1024,
            "max": int(vm.get("memory", "1024")) * 1024 * 1024,
        },
        "migration_downtime": -1,
        "multi_queues_enabled": "true",
        "placement_policy": {
            "affinity": "migratable"
        },
        "small_icon": {
            "href": f"/ovirt-engine/api/icons/{vm.get('smalliconid', 'dynamic-small-icon')}",
            "id": vm.get('smalliconid', 'dynamic-small-icon')
        },
        "start_paused": "false",
        "storage_error_resume_behaviour": "auto_resume",
        "time_zone": {
            "name": "Etc/GMT"
        },
        "virtio_scsi_multi_queues_enabled": "false",
        "cpu_profile": {
            "href": f"/ovirt-engine/api/cpuprofiles/{vm.get('cpuprofileid', 'dynamic-cpu-profile')}",
            "id": vm.get('cpuprofileid', 'dynamic-cpu-profile')
        }
    }

    if all_content:
        # Generate the XML data for the VM
        xml_data = generate_vm_xml(vm, volumes)

        # Add configuratoin data in initialization section
        detailed_vm["initialization"] = {
            "configuration": {
                "data": xml_data
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

def generate_vm_xml(vm, volumes):
    """
    Generate the OVF document in XML describing the virtual machine.
    """
    import xml.etree.ElementTree as ET
    from datetime import datetime
    import uuid

    # Create the root element
    envelope = ET.Element("ovf:Envelope")
    envelope.set("xmlns:ovf", "http://schemas.dmtf.org/ovf/envelope/1/")
    envelope.set("xmlns:rasd", "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData")
    envelope.set("xmlns:vssd", "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData")
    envelope.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
    envelope.set("ovf:version", "4.4.0.0")

    # References section
    references = ET.SubElement(envelope, "References")

    # Add disk file references here based on volumes
    for i, volume in enumerate(volumes):
        file_elem = ET.SubElement(references, "File")
        file_elem.set("ovf:href", f"{volume.get('storageid')}/{volume.get('path')}")
        file_elem.set("ovf:id", volume.get("id"))
        file_elem.set("ovf:size", str(volume.get("size", 0)))
        file_elem.set("ovf:description", volume.get("name", f"Disk {i+1}"))
        file_elem.set("ovf:disk_storage_type", "IMAGE")
        file_elem.set("ovf:cinder_volume_type", "")

    # Network section
    network_section = ET.SubElement(envelope, "NetworkSection")
    ET.SubElement(network_section, "Info").text = "List of networks"
    
    # Add network interfaces
    nics = vm.get("nic", [])
    for nic in nics:
        net_elem = ET.SubElement(network_section, "Network")
        net_elem.set("ovf:name", nic.get("networkname", "No Network"))
        net_elem.set("ovf:description", nic.get("networkname", "No Network"))

    # Disk section
    disk_section = ET.SubElement(envelope, "Section", {"xsi:type": "ovf:DiskSection_Type"})
    ET.SubElement(disk_section, "Info").text = "List of Virtual Disks"
    
    for i, volume in enumerate(volumes):
        disk_elem = ET.SubElement(disk_section, "Disk")
        disk_elem.set("ovf:diskId", volume.get("id"))
        disk_elem.set("ovf:size", str(int(volume.get("size", 0)) // (1024**3)))  # Convert to GB
        disk_elem.set("ovf:actual_size", str(int(volume.get("size", 0)) // (1024**3)))
        disk_elem.set("ovf:vm_snapshot_id", str(uuid.uuid4()))
        disk_elem.set("ovf:parentRef", "")
        disk_elem.set("ovf:fileRef", f"{volume.get('storageid')}/{volume.get('path')}")
        disk_elem.set("ovf:format", "http://www.vmware.com/specifications/vmdk.html#sparse")
        disk_elem.set("ovf:volume-format", "RAW")
        disk_elem.set("ovf:volume-type", "Sparse")
        disk_elem.set("ovf:disk-interface", "VirtIO_SCSI")
        disk_elem.set("ovf:read-only", "false")
        disk_elem.set("ovf:shareable", "false")
        disk_elem.set("ovf:boot", str(i == 0).lower())  # First disk is bootable
        disk_elem.set("ovf:pass-discard", "false")
        disk_elem.set("ovf:incremental-backup", "false")
        disk_elem.set("ovf:disk-alias", f"{volume.get('name', f"Disk{i+1}")}")
        disk_elem.set("ovf:disk-description", volume.get("displaytext", ""))
        disk_elem.set("ovf:wipe-after-delete", "false")

    # Content section (VirtualSystem)
    content = ET.SubElement(envelope, "Content", {
        "ovf:id": "out",
        "xsi:type": "ovf:VirtualSystem_Type"
    })
    
    # Basic VM information
    ET.SubElement(content, "Name").text = vm.get("instancename", "unnamed-vm")
    ET.SubElement(content, "Description").text = vm.get("displayname", "")
    ET.SubElement(content, "Comment").text = ""
    ET.SubElement(content, "CreationDate").text = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    ET.SubElement(content, "ExportDate").text = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    ET.SubElement(content, "DeleteProtected").text = "false"
    ET.SubElement(content, "SsoMethod").text = "guest_agent"
    ET.SubElement(content, "IsSmartcardEnabled").text = "false"
    ET.SubElement(content, "NumOfIoThreads").text = "1"
    ET.SubElement(content, "TimeZone").text = "Etc/GMT"
    ET.SubElement(content, "default_boot_sequence").text = "0"
    ET.SubElement(content, "Generation").text = "1"
    ET.SubElement(content, "ClusterCompatibilityVersion").text = "4.8"
    ET.SubElement(content, "VmType").text = "1"
    ET.SubElement(content, "ResumeBehavior").text = "AUTO_RESUME"
    ET.SubElement(content, "MinAllocatedMem").text = str(vm.get("memory", 1024))
    ET.SubElement(content, "IsStateless").text = "false"
    ET.SubElement(content, "IsRunAndPause").text = "false"
    ET.SubElement(content, "AutoStartup").text = "false"
    ET.SubElement(content, "Priority").text = "0"
    ET.SubElement(content, "CreatedByUserId").text = vm.get("userid")
    ET.SubElement(content, "CreatedByDomain").text = vm.get("domain")
    ET.SubElement(content, "CreatedByDomainId").text = vm.get("domainid")
    ET.SubElement(content, "CreatedByAccount").text = vm.get("account")
    ET.SubElement(content, "CreatedByProjectId").text = vm.get("projectid", "")
    ET.SubElement(content, "MigrationSupport").text = "0"
    ET.SubElement(content, "IsBootMenuEnabled").text = "false"
    ET.SubElement(content, "IsSpiceFileTransferEnabled").text = "true"
    ET.SubElement(content, "IsSpiceCopyPasteEnabled").text = "true"
    ET.SubElement(content, "AllowConsoleReconnect").text = "false"
    ET.SubElement(content, "ConsoleDisconnectAction").text = "LOCK_SCREEN"
    ET.SubElement(content, "ConsoleDisconnectActionDelay").text = "0"
    ET.SubElement(content, "CustomEmulatedMachine").text = ""
    ET.SubElement(content, "BiosType").text = "2"
    ET.SubElement(content, "CustomCpuName").text = ""
    ET.SubElement(content, "PredefinedProperties").text = ""
    ET.SubElement(content, "UserDefinedProperties").text = ""
    ET.SubElement(content, "MaxMemorySizeMb").text = str(int(vm.get("memory", 1024)) * 1)  # 1x memory limit
    ET.SubElement(content, "MultiQueuesEnabled").text = "true"
    ET.SubElement(content, "VirtioScsiMultiQueuesEnabled").text = "false"
    ET.SubElement(content, "UseHostCpu").text = "false"
    ET.SubElement(content, "BalloonEnabled").text = "true"
    ET.SubElement(content, "CpuPinningPolicy").text = "0"
    ET.SubElement(content, "ClusterName").text = "Default"
    ET.SubElement(content, "TemplateId").text = vm.get("templateid", "00000000-0000-0000-0000-000000000000")
    ET.SubElement(content, "TemplateName").text = "Blank"
    ET.SubElement(content, "IsInitilized").text = "true"
    ET.SubElement(content, "Origin").text = "3"
    ET.SubElement(content, "quota_id").text = vm.get("zoneid", "00000000-0000-0000-0000-000000000000")
    ET.SubElement(content, "DefaultDisplayType").text = "2"
    ET.SubElement(content, "TrustedService").text = "false"
    ET.SubElement(content, "OriginalTemplateId").text = vm.get("templateid", "00000000-0000-0000-0000-000000000000")
    ET.SubElement(content, "OriginalTemplateName").text = "Blank"
    ET.SubElement(content, "UseLatestVersion").text = "false"
    ET.SubElement(content, "StopTime").text = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    ET.SubElement(content, "BootTime").text = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    ET.SubElement(content, "Downtime").text = "0"

    # Operating System Section
    os_section = ET.SubElement(content, "Section", {
        "ovf:id": str(uuid.uuid4()),
        "ovf:required": "false",
        "xsi:type": "ovf:OperatingSystemSection_Type"
    })
    ET.SubElement(os_section, "Info").text = "Guest Operating System"
    ET.SubElement(os_section, "Description").text = vm.get("ostype", "other")

    # Virtual Hardware Section
    hardware_section = ET.SubElement(content, "Section", {"xsi:type": "ovf:VirtualHardwareSection_Type"})
    ET.SubElement(hardware_section, "Info").text = f"{vm.get('cpunumber', 1)} CPU, {vm.get('memory', 1024)} Memory"
    
    # System element
    system = ET.SubElement(hardware_section, "System")
    vssd_type = ET.SubElement(system, "vssd:VirtualSystemType")
    vssd_type.text = "ENGINE 4.4.0.0"

    # CPU Item
    cpu_item = ET.SubElement(hardware_section, "Item")
    ET.SubElement(cpu_item, "rasd:Caption").text = f"{vm.get('cpunumber', 1)} virtual cpu"
    ET.SubElement(cpu_item, "rasd:Description").text = "Number of virtual CPU"
    ET.SubElement(cpu_item, "rasd:InstanceId").text = "1"
    ET.SubElement(cpu_item, "rasd:ResourceType").text = "3"
    ET.SubElement(cpu_item, "rasd:num_of_sockets").text = str(vm.get('cpunumber', 1))
    ET.SubElement(cpu_item, "rasd:cpu_per_socket").text = "1"
    ET.SubElement(cpu_item, "rasd:threads_per_cpu").text = "1"
    ET.SubElement(cpu_item, "rasd:max_num_of_vcpus").text = "16"
    ET.SubElement(cpu_item, "rasd:VirtualQuantity").text = str(vm.get('cpunumber', 1))

    # Memory Item
    mem_item = ET.SubElement(hardware_section, "Item")
    ET.SubElement(mem_item, "rasd:Caption").text = f"{vm.get('memory', 1024)} MB of memory"
    ET.SubElement(mem_item, "rasd:Description").text = "Memory Size"
    ET.SubElement(mem_item, "rasd:InstanceId").text = "2"
    ET.SubElement(mem_item, "rasd:ResourceType").text = "4"
    ET.SubElement(mem_item, "rasd:AllocationUnits").text = "MegaBytes"
    ET.SubElement(mem_item, "rasd:VirtualQuantity").text = str(vm.get('memory', 1024))

    # Disk Items
    for i, volume in enumerate(volumes):
        disk_item = ET.SubElement(hardware_section, "Item")
        ET.SubElement(disk_item, "rasd:Caption").text = volume.get("name", f"Disk {i+1}")
        ET.SubElement(disk_item, "rasd:InstanceId").text = volume.get("id")
        ET.SubElement(disk_item, "rasd:ResourceType").text = "17"
        ET.SubElement(disk_item, "rasd:HostResource").text = f"{vm.get('id')}/{volume.get('id')}"
        ET.SubElement(disk_item, "rasd:Parent").text = "00000000-0000-0000-0000-000000000000"
        ET.SubElement(disk_item, "rasd:Template").text = volume.get("templateid", "00000000-0000-0000-0000-000000000000")
        ET.SubElement(disk_item, "rasd:ApplicationList").text = ""
        ET.SubElement(disk_item, "rasd:StorageId").text = volume.get("storageid", str(uuid.uuid4()))
        ET.SubElement(disk_item, "rasd:StoragePoolId").text = vm.get("zoneid", str(uuid.uuid4()))
        ET.SubElement(disk_item, "rasd:CreationDate").text = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        ET.SubElement(disk_item, "rasd:LastModified").text = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        ET.SubElement(disk_item, "rasd:last_modified_date").text = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        ET.SubElement(disk_item, "Type").text = "disk"
        ET.SubElement(disk_item, "Device").text = "disk"
        ET.SubElement(disk_item, "rasd:Address").text = f"{{type=drive, bus=0, controller=0, target=0, unit={i}}}"
        ET.SubElement(disk_item, "BootOrder").text = str(i)
        ET.SubElement(disk_item, "IsPlugged").text = "true"
        ET.SubElement(disk_item, "IsReadOnly").text = "false"
        ET.SubElement(disk_item, "Alias").text = f"ua-{volume.get('id')}"

    # NIC Items
    for i, nic in enumerate(nics):
        nic_item = ET.SubElement(hardware_section, "Item")
        ET.SubElement(nic_item, "rasd:Caption").text = f"Ethernet adapter on [{nic.get('networkname', 'No Network')}]"
        ET.SubElement(nic_item, "rasd:InstanceId").text = nic.get("id", str(uuid.uuid4()))
        ET.SubElement(nic_item, "rasd:ResourceType").text = "10"
        ET.SubElement(nic_item, "rasd:OtherResourceType").text = ""
        ET.SubElement(nic_item, "rasd:ResourceSubType").text = "3"
        ET.SubElement(nic_item, "rasd:Connection").text = nic.get("networkid", "")
        ET.SubElement(nic_item, "rasd:Linked").text = "true"
        ET.SubElement(nic_item, "rasd:Name").text = f"nic{i+1}"
        ET.SubElement(nic_item, "rasd:ElementName").text = f"nic{i+1}"
        ET.SubElement(nic_item, "rasd:MACAddress").text = nic.get("macaddress", "00:00:00:00:00:00")
        ET.SubElement(nic_item, "rasd:speed").text = "1000"
        ET.SubElement(nic_item, "Type").text = "interface"
        ET.SubElement(nic_item, "Device").text = "bridge"
        ET.SubElement(nic_item, "rasd:Address").text = f"{{type=pci, slot=0x0{i}, bus=0x01, domain=0x0000, function=0x0}}"
        ET.SubElement(nic_item, "BootOrder").text = "0"
        ET.SubElement(nic_item, "IsPlugged").text = "true"
        ET.SubElement(nic_item, "IsReadOnly").text = "false"
        ET.SubElement(nic_item, "Alias").text = f"ua-{nic.get('id', str(uuid.uuid4()))}"

    # USB Controller
    usb_item = ET.SubElement(hardware_section, "Item")
    ET.SubElement(usb_item, "rasd:Caption").text = "USB Controller"
    ET.SubElement(usb_item, "rasd:InstanceId").text = "3"
    ET.SubElement(usb_item, "rasd:ResourceType").text = "23"
    ET.SubElement(usb_item, "rasd:UsbPolicy").text = "DISABLED"

    # Graphical Controller (VGA)
    vga_item = ET.SubElement(hardware_section, "Item")
    ET.SubElement(vga_item, "rasd:Caption").text = "Graphical Controller"
    ET.SubElement(vga_item, "rasd:InstanceId").text = vm.get("id", str(uuid.uuid4()))
    ET.SubElement(vga_item, "rasd:ResourceType").text = "20"
    ET.SubElement(vga_item, "rasd:VirtualQuantity").text = "1"
    ET.SubElement(vga_item, "rasd:SinglePciQxl").text = "false"
    ET.SubElement(vga_item, "Type").text = "video"
    ET.SubElement(vga_item, "Device").text = "vga"
    ET.SubElement(vga_item, "rasd:Address").text = "{type=pci, slot=0x01, bus=0x00, domain=0x0000, function=0x0}"
    ET.SubElement(vga_item, "BootOrder").text = "0"
    ET.SubElement(vga_item, "IsPlugged").text = "true"
    ET.SubElement(vga_item, "IsReadOnly").text = "false"
    ET.SubElement(vga_item, "Alias").text = f"ua-{uuid.uuid4()}"
    
    spec_params = ET.SubElement(vga_item, "SpecParams")
    ET.SubElement(spec_params, "vram").text = "16384"

    # Graphical Framebuffer (VNC)
    vnc_item = ET.SubElement(hardware_section, "Item")
    ET.SubElement(vnc_item, "rasd:Caption").text = "Graphical Framebuffer"
    ET.SubElement(vnc_item, "rasd:InstanceId").text = vm.get("id", str(uuid.uuid4()))
    ET.SubElement(vnc_item, "rasd:ResourceType").text = "26"
    ET.SubElement(vnc_item, "Type").text = "graphics"
    ET.SubElement(vnc_item, "Device").text = "vnc"
    ET.SubElement(vnc_item, "rasd:Address").text = ""
    ET.SubElement(vnc_item, "BootOrder").text = "0"
    ET.SubElement(vnc_item, "IsPlugged").text = "true"
    ET.SubElement(vnc_item, "IsReadOnly").text = "false"
    ET.SubElement(vnc_item, "Alias").text = ""

    # CDROM
    cdrom_item = ET.SubElement(hardware_section, "Item")
    ET.SubElement(cdrom_item, "rasd:Caption").text = "CDROM"
    ET.SubElement(cdrom_item, "rasd:InstanceId").text = vm.get("id", str(uuid.uuid4()))
    ET.SubElement(cdrom_item, "rasd:ResourceType").text = "15"
    ET.SubElement(cdrom_item, "Type").text = "disk"
    ET.SubElement(cdrom_item, "Device").text = "cdrom"
    ET.SubElement(cdrom_item, "rasd:Address").text = "{type=drive, bus=0, controller=0, target=0, unit=2}"
    ET.SubElement(cdrom_item, "BootOrder").text = "0"
    ET.SubElement(cdrom_item, "IsPlugged").text = "true"
    ET.SubElement(cdrom_item, "IsReadOnly").text = "true"
    ET.SubElement(cdrom_item, "Alias").text = f"ua-{uuid.uuid4()}"
    
    cdrom_spec = ET.SubElement(cdrom_item, "SpecParams")
    ET.SubElement(cdrom_spec, "path").text = ""

    # Additional hardware items (channels, controllers, etc.)
    # Virtio Serial Channel
    channel_item = ET.SubElement(hardware_section, "Item")
    ET.SubElement(channel_item, "rasd:ResourceType").text = "0"
    ET.SubElement(channel_item, "rasd:InstanceId").text = vm.get("id", str(uuid.uuid4()))
    ET.SubElement(channel_item, "Type").text = "channel"
    ET.SubElement(channel_item, "Device").text = "unix"
    ET.SubElement(channel_item, "rasd:Address").text = "{type=virtio-serial, bus=0, controller=0, port=1}"
    ET.SubElement(channel_item, "BootOrder").text = "0"
    ET.SubElement(channel_item, "IsPlugged").text = "true"
    ET.SubElement(channel_item, "IsReadOnly").text = "false"
    ET.SubElement(channel_item, "Alias").text = "channel0"

    # PCI Controllers
    pci_controllers = [
        {"slot": "0x02", "function": "0x0", "multifunction": "on", "index": "1", "model": "pcie-root-port"},
        {"slot": "0x02", "function": "0x1", "index": "2", "model": "pcie-root-port"},
        {"slot": "0x02", "function": "0x2", "index": "3", "model": "pcie-root-port"},
        {"slot": "0x02", "function": "0x3", "index": "4", "model": "pcie-root-port"},
        {"slot": "0x02", "function": "0x4", "index": "5", "model": "pcie-root-port"},
        {"slot": "0x02", "function": "0x5", "index": "6", "model": "pcie-root-port"},
        {"slot": "0x02", "function": "0x6", "index": "7", "model": "pcie-root-port"},
        {"slot": "0x02", "function": "0x7", "index": "8", "model": "pcie-root-port"},
        {"slot": "0x03", "function": "0x0", "multifunction": "on", "index": "9", "model": "pcie-root-port"},
        {"slot": "0x03", "function": "0x1", "index": "10", "model": "pcie-root-port"},
    ]

    for i, ctrl in enumerate(pci_controllers):
        pci_item = ET.SubElement(hardware_section, "Item")
        ET.SubElement(pci_item, "rasd:ResourceType").text = "0"
        ET.SubElement(pci_item, "rasd:InstanceId").text = vm.get("id", str(uuid.uuid4()))
        ET.SubElement(pci_item, "Type").text = "controller"
        ET.SubElement(pci_item, "Device").text = "pci"
        
        addr_attrs = f"type=pci, slot={ctrl['slot']}, bus=0x00, domain=0x0000, function={ctrl['function']}"
        if ctrl.get("multifunction"):
            addr_attrs += f", multifunction={ctrl['multifunction']}"
        ET.SubElement(pci_item, "rasd:Address").text = f"{{{addr_attrs}}}"
        
        ET.SubElement(pci_item, "BootOrder").text = "0"
        ET.SubElement(pci_item, "IsPlugged").text = "true"
        ET.SubElement(pci_item, "IsReadOnly").text = "false"
        ET.SubElement(pci_item, "Alias").text = f"pci.{ctrl['index']}"
        
        spec_params = ET.SubElement(pci_item, "SpecParams")
        ET.SubElement(spec_params, "index").text = ctrl["index"]
        ET.SubElement(spec_params, "model").text = ctrl["model"]

    # SATA Controller
    sata_item = ET.SubElement(hardware_section, "Item")
    ET.SubElement(sata_item, "rasd:ResourceType").text = "0"
    ET.SubElement(sata_item, "rasd:InstanceId").text = vm.get("id", str(uuid.uuid4()))
    ET.SubElement(sata_item, "Type").text = "controller"
    ET.SubElement(sata_item, "Device").text = "sata"
    ET.SubElement(sata_item, "rasd:Address").text = "{type=pci, slot=0x1f, bus=0x00, domain=0x0000, function=0x2}"
    ET.SubElement(sata_item, "BootOrder").text = "0"
    ET.SubElement(sata_item, "IsPlugged").text = "true"
    ET.SubElement(sata_item, "IsReadOnly").text = "false"
    ET.SubElement(sata_item, "Alias").text = "ide"
    
    sata_spec = ET.SubElement(sata_item, "SpecParams")
    ET.SubElement(sata_spec, "index").text = "0"

    # Virtio Serial Controller
    virtio_serial_item = ET.SubElement(hardware_section, "Item")
    ET.SubElement(virtio_serial_item, "rasd:ResourceType").text = "0"
    ET.SubElement(virtio_serial_item, "rasd:InstanceId").text = vm.get("id", str(uuid.uuid4()))
    ET.SubElement(virtio_serial_item, "Type").text = "controller"
    ET.SubElement(virtio_serial_item, "Device").text = "virtio-serial"
    ET.SubElement(virtio_serial_item, "rasd:Address").text = "{type=pci, slot=0x00, bus=0x03, domain=0x0000, function=0x0}"
    ET.SubElement(virtio_serial_item, "BootOrder").text = "0"
    ET.SubElement(virtio_serial_item, "IsPlugged").text = "true"
    ET.SubElement(virtio_serial_item, "IsReadOnly").text = "false"
    ET.SubElement(virtio_serial_item, "Alias").text = f"ua-{uuid.uuid4()}"

    # RNG Device
    rng_item = ET.SubElement(hardware_section, "Item")
    ET.SubElement(rng_item, "rasd:ResourceType").text = "0"
    ET.SubElement(rng_item, "rasd:InstanceId").text = vm.get("id", str(uuid.uuid4()))
    ET.SubElement(rng_item, "Type").text = "rng"
    ET.SubElement(rng_item, "Device").text = "virtio"
    ET.SubElement(rng_item, "rasd:Address").text = "{type=pci, slot=0x00, bus=0x06, domain=0x0000, function=0x0}"
    ET.SubElement(rng_item, "BootOrder").text = "0"
    ET.SubElement(rng_item, "IsPlugged").text = "true"
    ET.SubElement(rng_item, "IsReadOnly").text = "false"
    ET.SubElement(rng_item, "Alias").text = f"ua-{uuid.uuid4()}"
    
    rng_spec = ET.SubElement(rng_item, "SpecParams")
    ET.SubElement(rng_spec, "source").text = "urandom"

    # Virtio SCSI Controller
    scsi_item = ET.SubElement(hardware_section, "Item")
    ET.SubElement(scsi_item, "rasd:ResourceType").text = "0"
    ET.SubElement(scsi_item, "rasd:InstanceId").text = vm.get("id", str(uuid.uuid4()))
    ET.SubElement(scsi_item, "Type").text = "controller"
    ET.SubElement(scsi_item, "Device").text = "virtio-scsi"
    ET.SubElement(scsi_item, "rasd:Address").text = "{type=pci, slot=0x00, bus=0x02, domain=0x0000, function=0x0}"
    ET.SubElement(scsi_item, "BootOrder").text = "0"
    ET.SubElement(scsi_item, "IsPlugged").text = "true"
    ET.SubElement(scsi_item, "IsReadOnly").text = "false"
    ET.SubElement(scsi_item, "Alias").text = f"ua-{uuid.uuid4()}"
    
    scsi_spec = ET.SubElement(scsi_item, "SpecParams")
    ET.SubElement(scsi_spec, "ioThreadId").text = ""

    # Memory Balloon
    balloon_item = ET.SubElement(hardware_section, "Item")
    ET.SubElement(balloon_item, "rasd:ResourceType").text = "0"
    ET.SubElement(balloon_item, "rasd:InstanceId").text = vm.get("id", str(uuid.uuid4()))
    ET.SubElement(balloon_item, "Type").text = "balloon"
    ET.SubElement(balloon_item, "Device").text = "memballoon"
    ET.SubElement(balloon_item, "rasd:Address").text = "{type=pci, slot=0x00, bus=0x05, domain=0x0000, function=0x0}"
    ET.SubElement(balloon_item, "BootOrder").text = "0"
    ET.SubElement(balloon_item, "IsPlugged").text = "true"
    ET.SubElement(balloon_item, "IsReadOnly").text = "true"
    ET.SubElement(balloon_item, "Alias").text = f"ua-{uuid.uuid4()}"
    
    balloon_spec = ET.SubElement(balloon_item, "SpecParams")
    ET.SubElement(balloon_spec, "model").text = "virtio"

    # USB Controller (XHCI)
    usb_xhci_item = ET.SubElement(hardware_section, "Item")
    ET.SubElement(usb_xhci_item, "rasd:ResourceType").text = "0"
    ET.SubElement(usb_xhci_item, "rasd:InstanceId").text = vm.get("id", str(uuid.uuid4()))
    ET.SubElement(usb_xhci_item, "Type").text = "controller"
    ET.SubElement(usb_xhci_item, "Device").text = "usb"
    ET.SubElement(usb_xhci_item, "rasd:Address").text = "{type=pci, slot=0x00, bus=0x04, domain=0x0000, function=0x0}"
    ET.SubElement(usb_xhci_item, "BootOrder").text = "0"
    ET.SubElement(usb_xhci_item, "IsPlugged").text = "true"
    ET.SubElement(usb_xhci_item, "IsReadOnly").text = "false"
    ET.SubElement(usb_xhci_item, "Alias").text = f"ua-{uuid.uuid4()}"
    
    usb_xhci_spec = ET.SubElement(usb_xhci_item, "SpecParams")
    ET.SubElement(usb_xhci_spec, "index").text = "0"
    ET.SubElement(usb_xhci_spec, "model").text = "qemu-xhci"

    # Snapshots section
    snapshots_section = ET.SubElement(content, "Section", {"xsi:type": "ovf:SnapshotsSection_Type"})
    snapshot_elem = ET.SubElement(snapshots_section, "Snapshot", {"ovf:id": str(uuid.uuid4())})
    ET.SubElement(snapshot_elem, "Type").text = "ACTIVE"
    ET.SubElement(snapshot_elem, "Description").text = "Active VM"
    ET.SubElement(snapshot_elem, "CreationDate").text = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

    # Convert to string and return
    xml_string = ET.tostring(envelope, encoding="unicode")
    return xml_string

def parse_ovf(ovf_doc):
    """
    Parse OVF XML and extract domain id, account, cpu cores, and memory (MiB).

    Accepts either:
    - an OVF XML string
    - a dict containing the XML under the "data" key
    """
    import xml.etree.ElementTree as ET

    domainid = None
    account = None
    cpu_cores = 1
    memory = 1024

    if isinstance(ovf_doc, str):
        xml_data = ovf_doc
    else:
        return domainid, account, cpu_cores, memory

    if not xml_data:
        return domainid, account, cpu_cores, memory

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError:
        logger.warning("Failed to parse OVF XML from initialization.configuration.data")
        return domainid, account, cpu_cores, memory

    def get_text_by_local_name(element, local_name):
        for node in element.iter():
            tag = node.tag
            if isinstance(tag, str) and tag.split("}")[-1] == local_name:
                value = (node.text or "").strip()
                if value:
                    return value
        return None

    def get_item_value(item, local_name):
        for child in item:
            tag = child.tag
            if isinstance(tag, str) and tag.split("}")[-1] == local_name:
                return (child.text or "").strip()
        return ""

    domainid = get_text_by_local_name(root, "CreatedByDomainId")
    account = get_text_by_local_name(root, "CreatedByAccount")
    projectid = get_text_by_local_name(root, "CreatedByProjectId")

    for item in root.iter():
        tag = item.tag
        if not isinstance(tag, str) or tag.split("}")[-1] != "Item":
            continue

        resource_type = get_item_value(item, "ResourceType")

        if resource_type == "3":
            virtual_quantity = get_item_value(item, "VirtualQuantity")
            if virtual_quantity.isdigit():
                cpu_cores = int(virtual_quantity)
            else:
                sockets = get_item_value(item, "num_of_sockets")
                per_socket = get_item_value(item, "cpu_per_socket")
                if sockets.isdigit() and per_socket.isdigit():
                    cpu_cores = int(sockets) * int(per_socket)

        elif resource_type == "4":
            virtual_quantity = get_item_value(item, "VirtualQuantity")
            if virtual_quantity.isdigit():
                memory = int(virtual_quantity)

    return domainid, account, projectid, cpu_cores, memory

@router.get("/vms")
async def list_vms(request: Request, follow: Optional[str] = None):
    data = await cs_request(request,
        "listVirtualMachines",
        {}
    )
    vms = data["listvirtualmachinesresponse"].get("virtualmachine", [])

    host_data = await cs_request(request, "listHosts", {"type": "Routing"})
    hosts = host_data["listhostsresponse"].get("host", [])

    follow_tags = follow and "tags" in [f.strip() for f in follow.split(",")]

    tags_by_vm = {}
    if follow_tags:
        from app.ovirtapi.tags import vm_tags as static_vm_tags
        tags_data = await cs_request(request, "listTags", {
            "key": "veeam_tag",
            "resourcetype": "UserVm"
        })
        cs_tags = tags_data.get("listtagsresponse", {}).get("tag", [])
        for cs_tag in cs_tags:
            vm_id = cs_tag.get("resourceid")
            tag_name = cs_tag.get("value")
            matched = next((t for t in static_vm_tags if t.get("name") == tag_name), None)
            tag_id = matched.get("id") if matched else tag_name
            description = matched.get("description", "") if matched else ""
            tags_by_vm.setdefault(vm_id, []).append({
                "parent": {
                    "href": "/ovirt-engine/api/tags/00000000-0000-0000-0000-000000000000",
                    "id": "00000000-0000-0000-0000-000000000000"
                },
                "vm": {
                    "href": f"/ovirt-engine/api/vms/{vm_id}",
                    "id": vm_id
                },
                "name": tag_name,
                "description": description,
                "href": f"/ovirt-engine/api/vms/{vm_id}/tags/{tag_id}",
                "id": tag_id
            })

    payload = []
    # for each vm, get the host id and add it to the vm
    for vm in vms:
        host_id = vm.get("hostid")
        logger.debug(f"host id: {host_id}")
        if host_id:
            # get host information from hosts data
            host = next((host for host in hosts if host.get("id") == host_id), None)
            logger.debug(f"host: {host}")
            vm["clusterid"] = host.get("clusterid")
        ovirt_vm = await cs_vm_to_ovirt(vm, request)
        if follow_tags:
            vm_id = vm.get("id")
            ovirt_vm["tags"] = {"tag": tags_by_vm.get(vm_id, [])}
        payload.append(ovirt_vm)

    return create_response(request, "vms", payload)


@router.get("/vms/{vm_id}")
async def get_vm(vm_id: str, request: Request, follow: Optional[str] = None):
    data = await cs_request(request,
        "listVirtualMachines",
        {"id": vm_id}
    )
    vms = data["listvirtualmachinesresponse"].get("virtualmachine", [])

    if not vms:
        raise HTTPException(status_code=404, detail="VM not found")

    vm = vms[0]

    if vm and vm.get("hostid"):
        # get host information based on the vm's hostid
        host_data = await cs_request(request, "listHosts", {"id": vm.get("hostid")})
        hosts = host_data["listhostsresponse"].get("host", [])

        if hosts:
            host = hosts[0]            
            vm["clusterid"] = host.get("clusterid")

    payload = await cs_vm_to_ovirt(vm, request)

    if follow and "tags" in [f.strip() for f in follow.split(",")]:
        from app.ovirtapi.tags import vm_tags as static_vm_tags
        tags_data = await cs_request(request, "listTags", {
            "key": "veeam_tag",
            "resourceid": vm_id,
            "resourcetype": "UserVm"
        })
        cs_tags = tags_data.get("listtagsresponse", {}).get("tag", [])
        tag_list = []
        for cs_tag in cs_tags:
            tag_name = cs_tag.get("value")
            matched = next((t for t in static_vm_tags if t.get("name") == tag_name), None)
            tag_id = matched.get("id") if matched else tag_name
            description = matched.get("description", "") if matched else ""
            tag_list.append({
                "parent": {
                    "href": "/ovirt-engine/api/tags/00000000-0000-0000-0000-000000000000",
                    "id": "00000000-0000-0000-0000-000000000000"
                },
                "vm": {
                    "href": f"/ovirt-engine/api/vms/{vm_id}",
                    "id": vm_id
                },
                "name": tag_name,
                "description": description,
                "href": f"/ovirt-engine/api/vms/{vm_id}/tags/{tag_id}",
                "id": tag_id
            })
        payload["tags"] = {"tag": tag_list}

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
        payload = await cs_vm_to_ovirt(vm, request)

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
        "vm": await cs_vm_to_ovirt(vm, request)
    }
    return create_response(request, "job", payload)

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
        "vm": await cs_vm_to_ovirt(vm, request)
    }
    return create_response(request, "job", payload)

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
        "vm": await cs_vm_to_ovirt(vm, request)
    }
    return create_response(request, "job", payload)

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
        vm_display_name = vm_params.get("display_name", "Created via oVirtAPI")
        vm_description = f"{vm_name} {vm_display_name}"
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

        # Extract disk and network information from OVF document if provided
        if "initialization" in vm_params and "configuration" in vm_params["initialization"] and "data" in vm_params["initialization"]["configuration"]:
            ovf_doc = vm_params["initialization"]["configuration"]["data"]
            domainid, account, projectid, cpu_cores, memory = parse_ovf(ovf_doc)
        else:
            domainid, account, projectid = None, None, None

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
        memory_guaranteed = str(2048 * 1024 * 1024)

        cs_params = {
            "name": vm_name,
            "displayname": vm_description,
            "serviceofferingid": service_offering_id,
            "hypervisor": "KVM",
            "dummy": True,
            "boottype": "UEFI",
            "bootmode": "Secure",
            "details[0].guest.cpu.mode": "host-passthrough",
            "details[0].cpuNumber": cpu_cores_total,          # total CPU cores
            "details[0].cpuSpeed": 1000,        # hardcoded
            "details[0].memory": int(int(memory_guaranteed) / 1024 / 1024)  # in MiB
        }

        if domainid and (account or projectid):
            cs_params["domainid"] = domainid
            if projectid:
                cs_params["projectid"] = projectid
            else:
                cs_params["account"] = account

        # Add user data (custom script) if provided
        if custom_script:
            # CloudStack supports user data via the 'userdata' parameter
            import base64
            # Encode the custom script in base64 as required by CloudStack
            encoded_userdata = base64.b64encode(custom_script.encode()).decode()
            cs_params["userdata"] = encoded_userdata

        # Add zone/cluster information if provided
        if cluster_id:
            # If cluster_id is provided, we can use it to get zoneid for CloudStack
            try:
                cluster_data = await cs_request(request, "listClusters", {"id": cluster_id})
                clusters = cluster_data["listclustersresponse"].get("cluster", [])
                if clusters:
                    # Use the zone ID from the cluster
                    zone_id = clusters[0].get("zoneid")
                    if zone_id:
                        cs_params["zoneid"] = zone_id
            except:
                pass

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
        payload = await cs_vm_to_ovirt(vm, request)

        # Update Guest OS to "Rocky Linux 9"
        if vm.get("osdisplayname") != "Rocky Linux 9":
            guestos_data = await cs_request(request, "listOsTypes", {
                "description" : "Rocky Linux 9"
            })
            guestos = guestos_data["listostypesresponse"].get("ostype", [])
            if guestos_data:
                new_guest_os_id = guestos[0].get("id")
                # Prepare parameters for CloudStack updateVirtualMachine API
                update_params = {"id": vm.get("id"), "ostypeid": new_guest_os_id}
                # Call CloudStack API to update the VM
                update_data = await cs_request(request, "updateVirtualMachine", update_params)
                updated_vm = update_data["updatevirtualmachineresponse"].get("virtualmachine", [])
                payload = await cs_vm_to_ovirt(updated_vm, request)

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

