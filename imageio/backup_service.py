import os
import json
import subprocess
import datetime
import xml.etree.ElementTree as ET
import libvirt
import nbd
import uuid
import time
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

CHUNK_SIZE = 2 * 1024 * 1024

backup_router = APIRouter()

# =============================
# Models
# =============================

class BackupResponse(BaseModel):
    vm_name: str
    mode: str
    backup_id: str
    new_checkpoint_id: str

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
            "previous_mode":   None,
            "previous_checkpoint": None,
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
    try:
        return conn.lookupByName(vm)
    except libvirt.libvirtError as e:
        logger.error(f"Error looking up VM {vm}: {e}")
        return None
    finally:
        conn.close()

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

def full_backup_running_vm(vm, dom):
    disk_paths = get_disk_paths(dom)
    vm_dir = os.path.join(BACKUP_ROOT, vm)
    os.makedirs(vm_dir, exist_ok=True)

    result = {}

    # Generate backup XML configuration for full backup
    backup_xml, targets = generate_backup_xml(vm, disk_paths, vm_dir)

    # For full backup, we'll use a specific checkpoint name pattern
    checkpoint_name = f"full-backup-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    checkpoint_xml = f"<domaincheckpoint><name>{checkpoint_name}</name></domaincheckpoint>"

    run_virsh_backup_begin(vm, checkpoint_name, backup_xml, checkpoint_xml)

    # Update result with target paths from backup XML
    for disk, path in targets.items():
        result[disk] = path

    return result, checkpoint_name


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

    backup_type = "incremental" if checkpoint_id else "full"

    for disk in disk_paths.keys():
        file_path = os.path.join(vm_dir, f"{disk}-{backup_type}-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.qcow2")
        d = ET.SubElement(disks_elem, "disk", {"name": disk, "type": "file"})
        ET.SubElement(d, "target", {"file": file_path})
        targets[disk] = file_path

    return ET.tostring(root).decode(), targets


def run_virsh_backup_begin(vm, checkpoint_name, backup_xml, checkpoint_xml):
    vm_dir = os.path.join(BACKUP_ROOT, vm)
    os.makedirs(vm_dir, exist_ok=True)

    # Create backup.xml and checkpoint.xml in vm_dir
    backup_xml_file = os.path.join(vm_dir, f"{checkpoint_name}-backup.xml")
    checkpont_xml_file = os.path.join(vm_dir, f"{checkpoint_name}-checkpoint.xml")

    with open(backup_xml_file, "w") as f:
        f.write(backup_xml)
    with open(checkpont_xml_file, "w") as f:
        f.write(checkpoint_xml)


    # Execute virsh backup-begin command for full or incremental backup
    cmd = [
        "virsh", "backup-begin", vm,
        "--backupxml", backup_xml_file,
        "--checkpointxml", checkpont_xml_file
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
async def backup_vm(vm: str, request: Request):
    # Check internal authentication
    if not check_internal_auth(request, INTERNAL_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid internal token")

    # Get from_checkpoint_id from headers
    checkpoint_id = request.headers.get("from_checkpoint_id")

    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8")
    payload = json.loads(body_str) if body_str else {}

    volumes = payload["volumes"]

    meta = load_meta(vm)
    dom = get_vm(vm)

    if dom:
        state = get_vm_state(dom)
        disk_paths = get_disk_paths(dom)
    else:
        state = "stopped"
        disk_paths = {}


    vm_dir = os.path.join(BACKUP_ROOT, vm)
    os.makedirs(vm_dir, exist_ok=True)

    backup_id = str(uuid.uuid4())

    # -------------------------
    # FULL BACKUP of Running VM
    # -------------------------
    if not checkpoint_id and state == "running":
        full_images, checkpoint_name = full_backup_running_vm(vm, dom)

        meta["previous_mode"] = meta["mode"]
        meta["previous_checkpoint"] = meta["last_checkpoint"]
        meta["mode"] = "cbt"
        meta["last_checkpoint"] = None
        meta["disks"] = {}

        i = 0
        for disk, path in full_images.items():
            index = "disk" + str(i)
            i += 1
            meta["disks"][index] = {
                "device_name": disk,
                "backup_path": path,                # the full backup path, will be removed when finalize the backup
                "file_path": disk_paths.get(disk),  # the original path
            }

        # Create initial checkpoint if running
        if state == "running":
            meta["last_checkpoint"] = checkpoint_name

        save_meta(vm, meta)

        return BackupResponse(
            vm_name=vm,
            mode="full",
            backup_id=backup_id,
            new_checkpoint_id=checkpoint_name or "none",
        )

    elif not checkpoint_id and state == "stopped":
        # -------------------------
        # FULL BACKUP of Stopped VM
        # -------------------------
        checkpoint_name = f"bitmap-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"

        # Create bitmap on images of stopped VM
        for volume in volumes:
            volume_path = f"/mnt/{volume['storageid']}/{volume['path']}"
            if os.path.exists(volume_path):
                # create bitmap using "qemu-img bitmap" command
                cmd = [
                    "qemu-img", "bitmap",
                    "--add",
                    volume_path,
                    checkpoint_name
                ]
                subprocess.run(cmd, check=True)
                logger.info(f"Created bitmap for full backup for {volume_path} as {checkpoint_name}")

                if meta["last_checkpoint"]:
                    try:
                        # remove last bitmap or checkpoint if exists
                        cmd = [
                            "qemu-img", "bitmap",
                            "--remove",
                            volume_path,
                            meta["last_checkpoint"]
                        ]
                        subprocess.run(cmd, check=True)
                        logger.info(f"Removed last bitmap {meta["previous_checkpoint"]} from {volume_path}")
                    except Exception as e:
                        logger.error(f"Error removing previous bitmap {meta['previous_checkpoint']} from {volume_path}: {e}")


        meta = {
            "mode": "bitmap",
            "last_checkpoint": checkpoint_name,
            "previous_mode": None,
            "previous_checkpoint": None,        # no previous checkpoint for full backup
            "cluster_size": CLUSTER_SIZE,
            "disks": {}
        }

        i = 0
        for volume in volumes:
            volume_path = f"/mnt/{volume['storageid']}/{volume['path']}"
            index = "disk" + str(i)
            i += 1
            meta["disks"][index] = {
                "file_path": volume_path
            }

        save_meta(vm, meta)

        return BackupResponse(
            vm_name=vm,
            mode="full",
            backup_id=backup_id,
            new_checkpoint_id=checkpoint_name,
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

        # ---- Running VM: virsh backup-begin ----
        if state == "running":
            if meta.get("last_checkpoint") and meta.get("mode") == "bitmap":
                # generate checkpoint xml with the bitmap
                previous_checkpoint_xml = generate_checkpoint_xml_from_bitmap(meta["last_checkpoint"], disk_paths)
                # run "echo previous_checkpoint_xml | virsh checkpoint-create --xmlfile /dev/stdin --redefine"
                cmd = ["echo", previous_checkpoint_xml, "|",
                    "virsh", "checkpoint-create",
                    "--xmlfile", "/dev/stdin",
                    "--redefine"
                ]
                subprocess.run(cmd, check=True, shell=True)
                logger.info(f"Created checkpoint {meta['last_checkpoint']} from bitmap")


            backup_xml, targets = generate_backup_xml(vm, disk_paths, vm_dir, checkpoint_id)

            checkpoint_name = f"incremental-backup-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
            checkpoint_xml = f"<domaincheckpoint><name>{checkpoint_name}</name></domaincheckpoint>"

            run_virsh_backup_begin(vm, checkpoint_name, backup_xml, checkpoint_xml)

            i = 0
            for disk, path in targets.items():
                index = "disk" + str(i)
                i += 1
                meta["disks"][index] = {
                    "device_name": disk,
                    "backup_path": path,
                    "file_path": disk_paths.get(disk)
                }

            meta["previous_mode"] = meta["mode"]
            meta["previous_checkpoint"] = meta["last_checkpoint"]
            meta["mode"] = "cbt"
            meta["last_checkpoint"] = checkpoint_name

        # ---- Stopped VM: bitmap ----
        else:
            checkpoint_name = f"bitmap-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
            # disk_paths is empty for stopped VM, use "volumes" instead
            for volume in volumes:
                volume_path = f"/mnt/{volume['storageid']}/{volume['path']}"
                if os.path.exists(volume_path):
                    # create new bitmap using "qemu-img bitmap" command
                    cmd = [
                        "qemu-img", "bitmap",
                        "--add",
                        volume_path,
                        checkpoint_name
                    ]
                    subprocess.run(cmd, check=True)
                    logger.info(f"Created bitmap for incremental backup for {volume_path} as {checkpoint_name}")

            meta["previous_mode"] = meta["mode"]
            meta["previous_checkpoint"] = meta["last_checkpoint"]
            meta["mode"] = "bitmap"
            meta["last_checkpoint"] = checkpoint_name
            meta["disks"] = {}

            i = 0
            for volume in volumes:
                volume_path = f"/mnt/{volume['storageid']}/{volume['path']}"
                index = "disk" + str(i)
                i += 1
                meta["disks"][index] = {
                    "file_path": volume_path
                }

        save_meta(vm, meta)

        return BackupResponse(
            vm_name=vm,
            mode="incremental",
            backup_id=backup_id,
            new_checkpoint_id=checkpoint_name,
        )

# =============================
# Internal method: Get extents for backup image, used by service.py
# =============================

def get_extents_for_backup(vm: str, diskpath: str, request: Request, context: str = "zero"):

    meta = load_meta(vm)

    if meta["mode"] == "cbt":
        # Find the disk by file_path instead of assuming the disk parameter matches the key
        disk_key = None
        for k, v in meta["disks"].items():
            if v.get("file_path") == diskpath:
                disk_key = k
                break

        if not disk_key:
            raise HTTPException(status_code=404, detail=f"Disk image {diskpath} not found")

        image = meta["disks"][disk_key]["backup_path"]
        if not os.path.exists(image):
            raise HTTPException(status_code=404, detail=f"Backup image for {diskpath} not found")

    elif meta["mode"] == "bitmap":
        image = diskpath
        if not os.path.exists(image):
            raise HTTPException(status_code=404, detail=f"Disk image {image} not found")
    else:
        raise HTTPException(status_code=400, detail="Invalid backup mode")

    if context == "zero":
        # Full backup
        return get_extents_via_nbd(image, bitmap_name=None, context = "zero")

    if context == "dirty":
        # Incremental backup
        return get_extents_via_nbd(image, bitmap_name=meta["previous_checkpoint"], context = "dirty")

    raise HTTPException(status_code=400, detail="Invalid context")

# =============================
# Internal method: Range download, used by service.py
# =============================

def download_range(vm: str, diskpath: str, request: Request):
        
    meta = load_meta(vm)

    if meta["mode"] == "cbt":
        # Find the disk by file_path instead of assuming the disk parameter matches the key
        disk_key = None
        for k, v in meta["disks"].items():
            if v.get("file_path") == diskpath:
                disk_key = k
                break

        if not disk_key:
            raise HTTPException(status_code=404, detail=f"Disk image {diskpath} not found")

        image = meta["disks"][disk_key]["backup_path"]
        if not os.path.exists(image):
            raise HTTPException(status_code=404, detail=f"Backup image for {diskpath} not found")

    elif meta["mode"] == "bitmap":
        image = diskpath
        if not os.path.exists(image):
            raise HTTPException(status_code=404, detail=f"Disk image {image} not found")
    else:
        raise HTTPException(status_code=400, detail="Invalid backup mode")

    def reader(start, length, image):
        with open(image, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    def reader_via_nbd(start: int, length: int, image: str):
        socket_path, proc = create_nbd_socket(image)
        conn = nbd.NBD()
        try:
            conn.connect_unix(socket_path)
            offset = start
            remaining = length

            while remaining > 0:
                chunk_len = min(CHUNK_SIZE, remaining)
                data = conn.pread(chunk_len, offset)
                if not data:
                    data = b"\x00" * chunk_len
                yield bytes(data)
                offset += chunk_len
                remaining -= chunk_len
        finally:
            conn.close()
            proc.terminate()
            proc.wait()
            if os.path.exists(socket_path):
                os.unlink(socket_path)

    file_size = get_virtual_size(image)
    range_header = request.headers.get("range")

    if not range_header:
        # No range requested, return full file
        return StreamingResponse(
            reader_via_nbd(0, file_size, image),
            headers={"Content-Length": str(file_size)},
            media_type="application/octet-stream"
        )

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



    headers = {
        "Content-Range": f"bytes {start}-{start+length-1}/{file_size}/*",
        "Content-Length": str(length),
        "Accept-Ranges": "bytes"
    }

    return StreamingResponse(
        reader_via_nbd(start, length, image),
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

# =============================
# Internal method: Get extents for qcow2 file via libnbd
# =============================


def get_extents_via_nbd(image, bitmap_name, context="dirty"):
    """
    Generate image extents for Veeam from raw or qcow2 image.

    :param image: path to qcow2/raw image
    :param context: "zero" for full backup, "dirty" for incremental
    :return: list of extents dictionaries
    """

    extents = []
    socket_path, proc = create_nbd_socket(image)
    conn = nbd.NBD()
    try:
        conn.connect_unix(socket_path)
        img_size = conn.get_size()  # virtual size

        if context == "zero" or bitmap_name is None:
            offset = 0
            while offset < img_size:
                length = min(CHUNK_SIZE, img_size - offset)
                data = conn.pread(length, offset)  # read virtual bytes

                is_zero = all(b == 0 for b in data)

                # hole detection: if qcow2 and fully zero, consider it a hole
                hole = is_zero and conn.is_hole(offset, length) if hasattr(conn, "is_hole") else False
                extents.append({
                    "start": offset,
                    "length": length,
                    "zero": is_zero,
                    "hole": hole
                })
                offset += length

        elif context == "dirty":
            def callback(metacontext, offset, entries, err):
                if err:
                    raise RuntimeError(err)

                for e in entries:
                    length = e["length"]

                    is_allocated = bool(e["flags"] & nbd.STATE_ALLOCATED)
                    is_zero = not is_allocated
                    dirty = is_allocated   # bitmap marks dirty regions

                    extents.append({
                        "start": offset,
                        "length": length,
                        "dirty": dirty,
                        "zero": is_zero
                    })

            conn.block_status(
                0,
                size,
                nbd.CMD_FLAG_REQ_ONE,
                callback,
                bitmap=bitmap_name
            )
    finally:
        conn.close()  # must close explicitly
        proc.terminate()
        proc.wait()
        if os.path.exists(socket_path):
            os.unlink(socket_path)

    logger.info(f"Extents of {image} before merging: {extents}")

    # Merge adjacent extents with same flags to reduce number of extents
    merged = []
    for e in extents:
        if not merged:
            merged.append(e)
            continue
        last = merged[-1]
        if context == "zero":
            if e["zero"] == last["zero"] and e.get("hole", False) == last.get("hole", False) and last["start"] + last["length"] == e["start"]:
                last["length"] += e["length"]
            else:
                merged.append(e)
        else:
            if e["dirty"] == last["dirty"] and e["zero"] == last["zero"] and last["start"] + last["length"] == e["start"]:
                last["length"] += e["length"]
            else:
                merged.append(e)

    logger.info(f"Extents of {image}: {merged}")

    return merged

# =============================
# Internal method: Create NBD socket and wait for connection
# =============================

def create_nbd_socket(image):
    socket_path = f"/tmp/nbd-{os.path.basename(image)}-{uuid.uuid4().hex}.sock"
    if os.path.exists(socket_path):
        os.remove(socket_path)
    cmd = ["qemu-nbd", "-f", "qcow2", "--read-only", f"--socket={socket_path}", image]
    proc = subprocess.Popen(cmd)
    wait_for_socket(socket_path)
    return socket_path, proc

def wait_for_socket(path, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            return
        time.sleep(0.05)
    raise RuntimeError(f"NBD socket not accepting connections: {path}")

# =============================
# Internal method: Get virtual size of qcow2 file
# =============================
def get_virtual_size(file_path):
    output = subprocess.check_output(["qemu-img", "info", "-U", file_path])
    output = output.decode("utf-8")
    lines = output.split("\n")
    for line in lines:
        if line.startswith("virtual size"):
            size = line.split()[4].split("(")[1]
            return int(size)
    raise ValueError(f"Could not find virtual size for {file_path}")

# =============================
# Internal method: Finalize backup - merge backup into VM
# =============================

def finalize_backup_vm(vm, volumes):
    """
    Finalize backup by merging the backup file into the original VM disk
    using virsh blockcommit command.
    """
    # Load metadata to get disk information
    meta = load_meta(vm)
    previous_checkpoint = meta["previous_checkpoint"]

    # remove previous checkpint by virsh checkpoint-delete
    if previous_checkpoint:
        dom = get_vm(vm)
        state = "stopped"
        if dom:
            state = get_vm_state(dom)

        if state == "running":
            try:
                subprocess.run(["virsh", "checkpoint-delete", vm, previous_checkpoint], check=True)
            except Exception as e:
                logger.error(f"Error deleting previous checkpoint: {e}")
        elif meta["previous_checkpoint"] and volumes:
            for volume in volumes:
                try:
                    volume_path = f"/mnt/{volume['storageid']}/{volume['path']}"
                    # remove last bitmap or checkpoint if exists
                    cmd = [
                        "qemu-img", "bitmap",
                        "--remove",
                        volume_path,
                        meta["previous_checkpoint"]
                    ]
                    subprocess.run(cmd, check=True)
                    logger.info(f"Removed previous bitmap {meta["previous_checkpoint"]} from {volume_path}")
                except Exception as e:
                    logger.error(f"Error removing previous bitmap {meta["previous_checkpoint"]} from {volume_path}: {e}")


        meta["previous_checkpoint"] = None
        save_meta(vm, meta)

# ---- Finalize backup ----

@backup_router.post("/internal/backup/{vm}/finalize")
def finalize_backup(vm: str, request: Request):
    # Check internal authentication
    if not check_internal_auth(request, INTERNAL_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid internal token")

    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8")
    payload = json.loads(body_str) if body_str else {}

    volumes = payload["volumes"]

    return finalize_backup_vm(vm, volumes)

# =============================
# Internal method: Create checkpoint xml from bitmap
# =============================

def generate_checkpoint_xml_from_bitmap(vm, last_checkpoint, disk_paths):
    # generate checkpoint xml like below
    checkpoint_xml = f"<domaincheckpoint><name>{last_checkpoint}</name><disks>"
    for disk in disk_paths.keys():
        checkpoint_xml += f"<disk name='{disk}'><bitmap name='{last_checkpoint}'/></disk>"
    checkpoint_xml += "</disks></domaincheckpoint>"

    logger.debug(f"checkpoint xml for {vm}: {checkpoint_xml}")

    return checkpoint_xml
