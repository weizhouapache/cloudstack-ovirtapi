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

# In-memory cache for NBD processes
nbd_processes = {}


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
        dom = conn.lookupByName(vm)
        return dom, get_vm_state(dom)
    except libvirt.libvirtError as e:
        logger.error(f"Error looking up VM {vm}: {e}")
        return None, "stopped"
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

    # For full backup, we'll use a specific checkpoint name pattern
    checkpoint_name = f"full-backup-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    checkpoint_xml = f"<domaincheckpoint><name>{checkpoint_name}</name></domaincheckpoint>"

    # Generate backup XML configuration for full backup
    backup_xml = generate_backup_xml(vm, disk_paths, vm_dir, None, checkpoint_name)

    run_virsh_backup_begin(vm, checkpoint_name, backup_xml, checkpoint_xml)

    return checkpoint_name


# =============================
# Running VM incremental (virsh backup-begin)
# =============================

def generate_backup_xml(vm, disk_paths, vm_dir, checkpoint_id=None, new_checkpoint_name=None):
    root = ET.Element("domainbackup")
    
    # Add incremental element with checkpoint reference if provided
    if checkpoint_id:
        root = ET.Element("domainbackup", {"mode": "pull"})
        incr_element = ET.SubElement(root, "incremental")
        incr_element.text = checkpoint_id
    else:
        # For full backup, we don't add the incremental element
        root = ET.Element("domainbackup", {"mode": "pull"})

    # Add NBD server
    # <server transport="unix" socket="/path/to/server"/>
    ET.SubElement(root, "server", {"transport": "unix", "socket": f"/tmp/nbd-{vm}-{new_checkpoint_name}.sock"})

    disks_elem = ET.SubElement(root, "disks")

    for disk in disk_paths.keys():
        if checkpoint_id:
            d = ET.SubElement(disks_elem, "disk", {"name": disk, "exportname": disk, "exportbitmap": checkpoint_id})
        else:
            d = ET.SubElement(disks_elem, "disk", {"name": disk, "exportname": disk})

    return ET.tostring(root).decode()


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
    proc = subprocess.Popen(cmd)
    wait_for_socket(f"/tmp/nbd-{vm}-{checkpoint_name}.sock")


# =============================
# Internal method: Check backup job status
# =============================

def check_backup_job_status(vm_name: str) -> dict:
    """
    Check if a backup job is currently running for the given VM.
    Uses virsh domjobinfo command to determine backup status.
    Returns a dictionary with backup status information.
    """

    # Since the backup job exposes the VM via NBD server, this returns False always, which means the VM is ready for veeam backup

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
                backup_in_progress = False
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
    dom, state = get_vm(vm)

    if dom:
        disk_paths = get_disk_paths(dom)
    else:
        disk_paths = {}


    vm_dir = os.path.join(BACKUP_ROOT, vm)
    os.makedirs(vm_dir, exist_ok=True)

    backup_id = str(uuid.uuid4())

    # -------------------------
    # FULL BACKUP of Running VM
    # -------------------------
    if not checkpoint_id and state == "running":
        checkpoint_name = full_backup_running_vm(vm, dom)

        meta["previous_mode"] = meta["mode"]
        meta["previous_checkpoint"] = meta["last_checkpoint"]
        meta["mode"] = "cbt"
        meta["last_checkpoint"] = None
        meta["disks"] = {}

        i = 0
        for disk in disk_paths.keys():
            index = "disk" + str(i)
            i += 1
            meta["disks"][index] = {
                "device_name": disk,
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
            if meta.get("last_checkpoint"):
                # check if the checkpoint exists
                cmd = ["virsh", "checkpoint-list", vm]
                output = subprocess.run(cmd, check=True, capture_output=True, text=True)
                if meta["last_checkpoint"] not in output.stdout:
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

            checkpoint_name = f"incremental-backup-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
            checkpoint_xml = f"<domaincheckpoint><name>{checkpoint_name}</name></domaincheckpoint>"

            backup_xml = generate_backup_xml(vm, disk_paths, vm_dir, checkpoint_id, checkpoint_name)

            run_virsh_backup_begin(vm, checkpoint_name, backup_xml, checkpoint_xml)

            i = 0
            for disk in disk_paths.keys():
                index = "disk" + str(i)
                i += 1
                meta["disks"][index] = {
                    "device_name": disk,
                    "file_path": disk_paths.get(disk)
                }

            meta["previous_mode"] = meta["mode"]
            meta["previous_checkpoint"] = meta["last_checkpoint"]
            meta["mode"] = "cbt"
            meta["last_checkpoint"] = checkpoint_name
            save_meta(vm, meta)

        # ---- Stopped VM: bitmap ----
        else:
            checkpoint_name = f"bitmap-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
            # disk_paths is empty for stopped VM, use "volumes" instead
            meta["disks"] = {}
            i = 0
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
                index = "disk" + str(i)
                i += 1
                meta["disks"][index] = {
                    "file_path": volume_path
                }

            meta["previous_mode"] = meta["mode"]
            meta["previous_checkpoint"] = meta["last_checkpoint"]
            meta["mode"] = "bitmap"
            meta["last_checkpoint"] = checkpoint_name
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

def get_extents_for_backup(vm: str, diskpath: str, request: Request, context: str = "zero", transfer_id: str = None):

    meta = load_meta(vm)
    dom, state = get_vm(vm)

    if meta["mode"] == "cbt":
        # online backup for running vm
        # Find the disk by file_path instead of assuming the disk parameter matches the key
        disk_key = None
        for k, v in meta["disks"].items():
            if v.get("file_path") == diskpath:
                disk_key = k
                break

        if not disk_key:
            raise HTTPException(status_code=404, detail=f"Disk label for {diskpath} not found")

        if not os.path.exists(diskpath):
            raise HTTPException(status_code=404, detail=f"Disk image for {diskpath} not found")

        socket_path = f"/tmp/nbd-{vm}-{meta["last_checkpoint"]}.sock"
        disk_label = meta["disks"][disk_key].get("device_name")

    elif meta["mode"] == "bitmap":
        # offline backup for stopped vm
        if not os.path.exists(diskpath):
            raise HTTPException(status_code=404, detail=f"Disk image for {diskpath} not found")
        socket_path = None
        disk_label = None
    else:
        raise HTTPException(status_code=400, detail="Invalid backup mode")

    meta["context"] = context
    save_meta(vm, meta)

    logger.debug(f"Getting extents via NBD server for image {diskpath} and transfer_id {transfer_id}")

    if context == "zero":
        # Full backup
        return get_extents_via_nbd(diskpath, socket_path=socket_path, disk_label=disk_label, context = "zero", transfer_id=transfer_id)

    if context == "dirty":
        # Incremental backup
        return get_extents_via_nbd(diskpath, bitmap_name=meta["previous_checkpoint"], socket_path=socket_path,
                disk_label=disk_label, context = "dirty", transfer_id=transfer_id)

    raise HTTPException(status_code=400, detail="Invalid context")

# =============================
# Internal method: Range download, used by service.py
# =============================

def download_range(vm: str, diskpath: str, request: Request, transfer_id: str):
        
    meta = load_meta(vm)

    if meta["mode"] == "cbt":
        # Find the disk by file_path instead of assuming the disk parameter matches the key
        disk_key = None
        for k, v in meta["disks"].items():
            if v.get("file_path") == diskpath:
                disk_key = k
                break

        if not disk_key:
            raise HTTPException(status_code=404, detail=f"Disk label for {diskpath} not found")

        socket_path = f"/tmp/nbd-{vm}-{meta["last_checkpoint"]}.sock"
        disk_label = meta["disks"][disk_key].get("device_name")

    elif meta["mode"] == "bitmap":
        socket_path = None
        disk_label = None
    else:
        raise HTTPException(status_code=400, detail="Invalid backup mode")

    if not os.path.exists(diskpath):
        raise HTTPException(status_code=404, detail=f"Disk image for {diskpath} not found")

    if meta["context"] == "dirty":
        bitmap_name = meta["previous_checkpoint"]
    else:
        bitmap_name = None

    if socket_path:
        # NBD server is already running via "virsh backup-begin"
        logger.debug(f"Using existing NBD server for image {diskpath} with socket {socket_path}")
        proc = None
    else:
        socket_path = get_socket_path(diskpath, transfer_id)
        if os.path.exists(socket_path):
            logger.debug(f"Using existing NBD server for image {diskpath} with socket {socket_path}")
        else:
            socket_path, proc = create_nbd_socket(diskpath, bitmap_name=bitmap_name, transfer_id=transfer_id)
            nbd_processes[diskpath] = proc
            logger.debug(f"Started NBD server for image {diskpath} with socket {socket_path} and proc {proc}")

    if not os.path.exists(socket_path):
        raise HTTPException(status_code=404, detail=f"Socket {socket_path} not found")

    conn = nbd.NBD()
    logger.debug(f"Test: Connecting to NBD socket {socket_path}")
    conn.connect_unix(socket_path)
    logger.debug(f"Test: NBD socket {socket_path} size: {conn.get_size()}")  # conn.get_size()
    conn.close()

    def reader_via_nbd(start: int, length: int, image: str, disk_label: str = None, bitmap_name: str = None, socket_path: str = None):
        conn = nbd.NBD()
        try:
            if bitmap_name:
                # Tell NBD which bitmap to use
                conn.add_meta_context(f"{nbd.CONTEXT_QEMU_DIRTY_BITMAP}{bitmap_name}")
            if disk_label:
                conn.set_export_name(disk_label)

            logger.debug(f"Connecting to NBD socket {socket_path}")
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

    file_size = get_virtual_size(diskpath)
    range_header = request.headers.get("range")

    if not range_header:
        # No range requested, return full file
        return StreamingResponse(
            reader_via_nbd(0, file_size, diskpath, disk_label, bitmap_name, socket_path),
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
        reader_via_nbd(start, length, diskpath, disk_label, bitmap_name, socket_path),
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


def get_extents_via_nbd(image, bitmap_name = None, socket_path=None, disk_label=None, context="dirty", transfer_id: str = None):
    """
    Generate image extents for Veeam from raw or qcow2 image.

    :param image: path to qcow2/raw image
    :param context: "zero" for full backup, "dirty" for incremental
    :return: list of extents dictionaries
    """

    extents = []

    if socket_path:
        # NBD server is already running via "virsh backup-begin"
        logger.debug(f"Using existing NBD server for image {image} with socket {socket_path}")
        proc = None
    else:
        logger.debug(f"Starting NBD server for image {image} for transfer_id {transfer_id}")
        socket_path, proc = create_nbd_socket(image, bitmap_name, transfer_id=transfer_id)
        logger.debug(f"Started NBD server for image {image} with socket {socket_path} and proc {proc}")

    conn = nbd.NBD()
    try:
        if bitmap_name:
            # Tell NBD which bitmap to use
            conn.add_meta_context(f"{nbd.CONTEXT_QEMU_DIRTY_BITMAP}{bitmap_name}")
        else:
            conn.add_meta_context(nbd.CONTEXT_BASE_ALLOCATION)    # only metadata for allocation

        if disk_label:
            conn.set_export_name(disk_label)

        conn.connect_unix(socket_path)

        count = conn.get_nr_meta_contexts()
        for i in range(count):
            logger.debug(f"Connected to NBD socket: {socket_path} with meta context: {conn.get_meta_context(i)}")

        img_size = conn.get_size()  # virtual size

        if context == "zero" or bitmap_name is None:
            def callback(metacontext, offset, entries, handle):
                pos = offset
                for i in range(0, len(entries), 2):
                    length = entries[i]
                    flags = entries[i+1]
                    zero = bool(flags & nbd.STATE_ZERO)
                    hole = bool(flags & nbd.STATE_HOLE)
                    extents.append({
                        "start": pos,
                        "length": length,
                        "zero": zero,
                        "hole": hole,
                    })
                    pos += length

            conn.block_status(
                img_size,
                0,
                callback
            )

        elif context == "dirty":
            def callback(metacontext, offset, entries, handle):
                pos = offset
                for i in range(0, len(entries), 2):
                    length = entries[i]
                    flags = entries[i+1]
                    dirty = bool(flags & nbd.STATE_DIRTY)
                    zero = bool(flags & nbd.STATE_ZERO)
                    extents.append({
                        "start": pos,
                        "length": length,
                        "dirty": dirty,
                        "zero": zero,
                    })
                    pos += length

            conn.block_status(
                img_size,
                0,
                callback
            )
    finally:
        conn.close()  # must close explicitly
        if proc:
            proc.terminate()
            proc.wait()

    logger.info(f"Extents of {image} before merging: {extents}")

    # Merge adjacent extents with same flags to reduce number of extents
    merged = []
    for e in extents:
        if not merged:
            merged.append(e)
            continue
        last = merged[-1]
        if context == "zero" or bitmap_name is None:
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

def get_socket_path(image, transfer_id: str = None):
    if transfer_id:
        socket_path = f"/tmp/nbd-{os.path.basename(image)}--{transfer_id}.sock"
    else:
        socket_path = f"/tmp/nbd-{os.path.basename(image)}--{uuid.uuid4().hex}.sock"
    return socket_path

def create_nbd_socket(image, bitmap_name=None, read_only=True, transfer_id=None):
    socket_path = get_socket_path(image, transfer_id)
    if os.path.exists(socket_path):
        os.remove(socket_path)
    if read_only:
        read_only_flag = "--read-only"
    else:
        read_only_flag = ""
    if bitmap_name:
        cmd = ["qemu-nbd", "-f", "qcow2", read_only_flag, "--persistent", f"--socket={socket_path}", "--shared", "100", f"--bitmap={bitmap_name}", image]
    else:
        cmd = ["qemu-nbd", "-f", "qcow2", read_only_flag, "--persistent", f"--socket={socket_path}", "--shared", "100", image]
    logger.debug(f"Starting NBD server: {cmd}")
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

    dom, state = get_vm(vm)
    if state == "running":
        try:
            subprocess.run(["virsh", "domjobabort", vm], check=True)
            logger.debug(f"Aborted backup job and stopped NBD server for {vm}")
        except Exception as e:
            logger.error(f"Error aborting backup job for {vm}: {e}")

    else:
        for volume in volumes:
            # stop NBD process
            volume_path = f"/mnt/{volume['storageid']}/{volume['path']}"
            proc = nbd_processes.get(volume_path)
            if proc:
                logger.debug(f"Terminating NBD server for image {volume_path} with proc {proc}")
                proc.terminate()
                proc.wait()

    # remove previous checkpint by virsh checkpoint-delete
    if previous_checkpoint:

        if state == "running":
            try:
                subprocess.run(["virsh", "checkpoint-delete", vm, previous_checkpoint], check=True)
                logger.debug(f"Deleted previous checkpoint {previous_checkpoint} for {vm}")                
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


        meta["previous_mode"] = None
        meta["previous_checkpoint"] = None
        save_meta(vm, meta)

# ---- Finalize backup ----

@backup_router.post("/internal/backup/{vm}/finalize")
async def finalize_backup(vm: str, request: Request):
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
    checkpoint_xml += f"<creationTime>{extract_timestamp(last_checkpoint)}</creationTime>"
    for disk in disk_paths.keys():
        checkpoint_xml += f"<disk name='{disk}' checkpoint='bitmap' bitmap='{last_checkpoint}'></disk>"
    checkpoint_xml += "</disks></domaincheckpoint>"

    logger.debug(f"checkpoint xml for {vm}: {checkpoint_xml}")

    return checkpoint_xml

def extract_timestamp(checkpoint_name):
    from datetime import datetime, timezone
    import re
    match = re.search(r'(\d{8}-\d{6})', checkpoint_name)
    if match:
        timestamp = match.group(1)
        dt = datetime.strptime(timestamp, "%Y%m%d-%H%M%S")
        return int(dt.replace(tzinfo=timezone.utc).timestamp())
    return 1767225600   # 2026-01-01 00:00:00 UTC
