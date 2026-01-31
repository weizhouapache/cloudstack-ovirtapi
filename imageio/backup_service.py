import os
import json
import subprocess
import datetime
import xml.etree.ElementTree as ET
import libvirt
import uuid
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.security.certs import get_default_ip
from imageio.config import IMAGEIO
from imageio.utils import check_internal_auth
from imageio.logging_imageio import logger


# Import the internal token
INTERNAL_TOKEN = IMAGEIO.get("internal_token", None)


# =============================
# Config
# =============================

BACKUP_ROOT = "/backup"
META_ROOT = "/backup/meta"
CLUSTER_SIZE = 65536
KEEP_CHECKPOINTS = 1

backup_router = APIRouter()

# =============================
# Models
# =============================

class BackupResponse(BaseModel):
    vm_name: str
    mode: str
    backup_id: str
    new_checkpoint_id: str
    disks: dict

class BackupStatusResponse(BaseModel):
    vm_name: str
    backup_in_progress: bool
    job_info: str

# =============================
# Metadata helpers
# =============================

def meta_path(vm):
    return os.path.join(META_ROOT, f"{vm}.json")


def load_meta(vm):
    path = meta_path(vm)
    if not os.path.exists(path):
        return {
            "mode": None,
            "last_checkpoint": None,
            "cluster_size": CLUSTER_SIZE,
            "disks": {}
        }
    with open(path) as f:
        return json.load(f)


def save_meta(vm, meta):
    os.makedirs(META_ROOT, exist_ok=True)
    tmp = meta_path(vm) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(meta, f, indent=2)
    os.replace(tmp, meta_path(vm))


# =============================
# Libvirt helpers
# =============================

def get_vm(vm):
    conn = libvirt.open(None)
    dom = conn.lookupByName(vm)
    return conn, dom


def get_vm_state(dom):
    state, _ = dom.state()
    if state == libvirt.VIR_DOMAIN_RUNNING:
        return "running"
    else:
        return "stopped"


def get_disk_paths(dom):
    tree = ET.fromstring(dom.XMLDesc())
    disks = {}
    for d in tree.findall(".//devices/disk"):
        target = d.find("target")
        source = d.find("source")
        if target is not None and source is not None:
            dev = target.attrib["dev"]
            path = source.attrib.get("file") or source.attrib.get("dev")
            disks[dev] = path
    return disks


# =============================
# Full backup
# =============================

def run_full_backup(vm, dom):
    disk_paths = get_disk_paths(dom)
    vm_dir = os.path.join(BACKUP_ROOT, vm)
    os.makedirs(vm_dir, exist_ok=True)

    result = {}

    # Generate backup XML configuration for full backup
    backup_xml, targets = generate_backup_xml(vm, disk_paths, vm_dir)
    # For full backup, we'll use a specific checkpoint name pattern
    checkpoint_name = f"full-backup-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    checkpoint_xml = f"<domaincheckpoint><name>{checkpoint_name}</name></domaincheckpoint>"

    # Execute virsh backup-begin command for full backup
    with open("/tmp/backup.xml", "w") as f:
        f.write(backup_xml)
    with open("/tmp/checkpoint.xml", "w") as f:
        f.write(checkpoint_xml)

    cmd = [
        "virsh", "backup-begin", vm,
        "--backupxml", "/tmp/backup.xml",
        "--checkpointxml", "/tmp/checkpoint.xml"
    ]
    subprocess.run(cmd, check=True)

    # Update result with target paths from backup XML
    for disk, path in targets.items():
        result[disk] = path

    return result


# =============================
# Running VM incremental (virsh backup-begin)
# =============================

def generate_backup_xml(vm, disk_paths, vm_dir, checkpoint_id=None):
    root = ET.Element("domainbackup")
    
    # Add incremental element with checkpoint reference if provided
    if checkpoint_id:
        incr_element = ET.SubElement(root, "incremental")
        incr_element.text = checkpoint_id
    else:
        # For full backup, we don't add the incremental element
        pass
        
    disks_elem = ET.SubElement(root, "disks")

    targets = {}

    for disk in disk_paths.keys():
        inc_path = os.path.join(vm_dir, f"{disk}-inc-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.qcow2")
        d = ET.SubElement(disks_elem, "disk", {"name": disk, "type": "file"})
        ET.SubElement(d, "target", {"file": inc_path})
        targets[disk] = inc_path

    return ET.tostring(root).decode(), targets


def generate_checkpoint_xml():
    name = f"backup-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    xml = f"<domaincheckpoint><name>{name}</name></domaincheckpoint>"
    return name, xml


def run_virsh_backup_begin(vm, backup_xml, checkpoint_xml):
    with open("/tmp/backup.xml", "w") as f:
        f.write(backup_xml)
    with open("/tmp/checkpoint.xml", "w") as f:
        f.write(checkpoint_xml)

    cmd = [
        "virsh", "backup-begin", vm,
        "--backupxml", "/tmp/backup.xml",
        "--checkpointxml", "/tmp/checkpoint.xml"
    ]
    subprocess.run(cmd, check=True)


# =============================
# Stopped VM incremental (image diff)
# =============================

def get_image_diff_extents(current, previous):
    cmd = ["qemu-img", "compare", "-f", "qcow2", "-F", "qcow2", "-s", current, previous]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=True)

    extents = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) == 2:
            extents.append({"offset": int(parts[0]), "length": int(parts[1])})
    return extents


def create_incremental_from_extents(current, previous, out, extents):
    if os.path.exists(out):
        os.remove(out)

    for e in extents:
        cmd = [
            "qemu-img", "convert",
            "-f", "qcow2",
            "-O", "qcow2",
            "-o", f"cluster_size={CLUSTER_SIZE},backing_file={previous}",
            "-S", str(e["offset"]),
            "-s", str(e["length"]),
            current, out
        ]
        subprocess.run(cmd, check=True)


# =============================
# Internal method: Check backup job status
# =============================

def check_backup_job_status(vm_name: str) -> dict:
    """
    Check if a backup job is currently running for the given VM.
    Uses virsh domjobinfo command to determine backup status.
    Returns a dictionary with backup status information.
    """
    try:
        # Run virsh domjobinfo command
        result = subprocess.run(
            ["virsh", "domjobinfo", vm_name],
            capture_output=True,
            text=True,
            check=False
        )
        
        # If command fails or returns empty output, no backup job is running
        if result.returncode != 0 or not result.stdout.strip():
            return {
                "backup_in_progress": False,
                "job_info": ""
            }
        
        job_info = result.stdout.strip()

        # Loop through lines and check for both keywords
        backup_in_progress = False
        for line in job_info.split('\n'):
            if "Operation:" in line and "Backup" in line:
                backup_in_progress = True
                break

        return {
            "backup_in_progress": backup_in_progress,
            "job_info": job_info
        }
        
    except Exception as e:
        # If any error occurs, assume no backup job is running
        return {
            "backup_in_progress": False,
            "job_info": f"Error checking backup status: {str(e)}"
        }

# =============================
# FastAPI: Backup endpoint
# =============================

@backup_router.post("/internal/backup/{vm}", response_model=BackupResponse)
def backup_vm(vm: str, request: Request):
    # Check internal authentication
    if not check_internal_auth(request, INTERNAL_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid internal token")
        
    # Get checkpoint_id from headers
    checkpoint_id = request.headers.get("checkpoint-id")
        
    meta = load_meta(vm)
    conn, dom = get_vm(vm)
    state = get_vm_state(dom)
    disk_paths = get_disk_paths(dom)

    vm_dir = os.path.join(BACKUP_ROOT, vm)
    os.makedirs(vm_dir, exist_ok=True)

    backup_id = str(uuid.uuid4())

    # -------------------------
    # FULL BACKUP
    # -------------------------
    if not checkpoint_id:
        full_images = run_full_backup(vm, dom)

        meta["mode"] = "cbt" if state == "running" else "image-diff"
        meta["last_checkpoint"] = None
        meta["disks"] = {}

        for disk, path in full_images.items():
            meta["disks"][disk] = {
                "last_backup": path,
                "file_path": disk_paths.get(disk)
            }

        # Create initial checkpoint if running
        new_cp = None
        if state == "running":
            new_cp, cp_xml = generate_checkpoint_xml()
            dom.checkpointCreateXML(cp_xml, 0)
            meta["last_checkpoint"] = new_cp

        save_meta(vm, meta)
        conn.close()

        return BackupResponse(
            vm_name=vm,
            mode="full",
            backup_id=backup_id,
            new_checkpoint_id=new_cp or "none",
            disks=full_images
        )

    # -------------------------
    # INCREMENTAL BACKUP
    # -------------------------
    else:
        if meta.get("last_checkpoint") and meta["last_checkpoint"] != checkpoint_id:
            raise HTTPException(
                status_code=400,
                detail=f"Checkpoint mismatch: expected {meta.get('last_checkpoint')}, got {checkpoint_id}"
            )

        result = {}

        # ---- Running VM: virsh backup-begin ----
        if state == "running":
            backup_xml, targets = generate_backup_xml(vm, disk_paths, vm_dir)
            new_cp, cp_xml = generate_checkpoint_xml()

            run_virsh_backup_begin(vm, backup_xml, cp_xml)

            for disk, path in targets.items():
                meta["disks"][disk] = {
                    "last_backup": path,
                    "file_path": disk_paths.get(disk)
                }
                result[disk] = path

            meta["mode"] = "cbt"
            meta["last_checkpoint"] = new_cp

        # ---- Stopped VM: image-diff ----
        else:
            for disk, current in disk_paths.items():
                previous = meta["disks"][disk]["last_backup"]
                inc_path = os.path.join(vm_dir, f"{disk}-inc-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.qcow2")

                extents = get_image_diff_extents(current, previous)
                if not extents:
                    continue

                create_incremental_from_extents(current, previous, inc_path, extents)

                meta["disks"][disk]["last_backup"] = inc_path
                result[disk] = inc_path

            meta["mode"] = "image-diff"
            meta["last_checkpoint"] = None
            new_cp = f"{vm}-image-diff-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"

        save_meta(vm, meta)
        conn.close()

        return BackupResponse(
            vm_name=vm,
            mode="incremental",
            backup_id=backup_id,
            new_checkpoint_id=new_cp,
            disks=result
        )

# =============================
# Internal method: Get extents for backup image, used by service.py
# =============================

def get_extents_with_context(vm: str, diskpath: str, request: Request, context: str = "zero"):

    meta = load_meta(vm)

    # Find the disk by file_path instead of assuming the disk parameter matches the key
    disk_key = None
    for k, v in meta["disks"].items():
        if v.get("file_path") == diskpath:
            disk_key = k
            break

    if not disk_key:
        raise HTTPException(status_code=404, detail="Disk not found")

    image = meta["disks"][disk_key]["last_backup"]
    if not os.path.exists(image):
        raise HTTPException(status_code=404, detail="Backup image not found")

    extents = get_backup_extents_with_context(image, context)

    return extents

# =========================
# Internal method: Get extents for qcow2 file, used by backup_service.py
# =========================

def get_backup_extents_with_context(image, context: str = "zero"):
    cmd = ["qemu-img", "map", "-U", "--output=json", image]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, check=True, text=True)
    layout = json.loads(proc.stdout)

    extents = []
    for e in layout:
        start = e["start"]
        length = e["length"]
        is_data = e.get("data", False)
        is_zero = e.get("zero", False)
        is_present = e.get("present", False)
        depth = e.get("depth", 0)

        # True if data is actually readable for this backup
        is_backing_data = depth > 0  # block exists in backing file
        is_top_data = is_present and is_data
        is_readable = is_top_data or is_backing_data

        if context == "dirty":
            # Incremental backup: mark modified blocks
            extents.append({
                "start": start,
                "length": length,
                "dirty": is_readable,  # should download if true
                "zero": is_zero        # can be written efficiently as zeroes
            })
        else:
            # Full backup: mark zero/hole blocks
            extents.append({
                "start": start,
                "length": length,
                "zero": is_zero,
                "hole": False  # always False
            })

    logger.info(f"Extents of {image}: {extents}")

    return extents

# =============================
# Internal method: Range download, used by service.py
# =============================

def download_range(vm: str, diskpath: str, request: Request):
        
    meta = load_meta(vm)

    # Find the disk by file_path instead of assuming the disk parameter matches the key
    disk_key = None
    for k, v in meta["disks"].items():
        if v.get("file_path") == diskpath:
            disk_key = k
            break

    if not disk_key:
        raise HTTPException(status_code=404, detail="Disk not found")

    image = meta["disks"][disk_key]["last_backup"]
    if not os.path.exists(image):
        raise HTTPException(status_code=404, detail="Backup image not found")

    file_size = os.path.getsize(image)
    range_header = request.headers.get("range")

    if not range_header:
        # No range requested, return full file
        def reader():
            with open(image, "rb") as f:
                yield from f
        return StreamingResponse(reader(), media_type="application/octet-stream")

    # Parse range header (format: "bytes=start-end")
    try:
        range_type, range_spec = range_header.split("=")
        if range_type.strip().lower() != "bytes":
            raise HTTPException(status_code=400, detail="Invalid range type")
        
        start_str, end_str = range_spec.split("-")
        start = int(start_str)
        end = int(end_str) if end_str else file_size - 1
        
        # Handle negative values and bounds checking
        if start < 0 or start >= file_size:
            raise HTTPException(status_code=416, detail="Range Not Satisfiable")
        end = min(end, file_size - 1)
        
        length = end - start + 1
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid range format")

    def reader():
        with open(image, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}/*",
        "Content-Length": str(length),
        "Accept-Ranges": "bytes"
    }

    return StreamingResponse(
        reader(), 
        media_type="application/octet-stream",
        headers=headers,
        status_code=206
    )

# =============================
# Internal API endpoint: Check backup job status
# =============================

@backup_router.get("/internal/backup/{vm}/status", response_model=BackupStatusResponse)
def get_backup_status(vm: str, request: Request):
    """
    Internal API endpoint to check the status of backup job for a VM.
    Uses virsh domjobinfo command to determine if backup is in progress.
    Returns backup status information.
    """
    # Check internal authentication
    if not check_internal_auth(request, INTERNAL_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid internal token")
    
    # Check backup job status
    status_info = check_backup_job_status(vm)
    
    return BackupStatusResponse(
        vm_name=vm,
        backup_in_progress=status_info["backup_in_progress"],
        job_info=status_info["job_info"]
    )
