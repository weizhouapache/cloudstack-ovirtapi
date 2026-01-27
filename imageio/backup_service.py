import os
import json
import subprocess
import datetime
import xml.etree.ElementTree as ET
import libvirt
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

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
    new_checkpoint_id: str
    disks: dict


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
    os.remove(tmp)


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

    for disk, src in disk_paths.items():
        out = os.path.join(vm_dir, f"{disk}-full.qcow2")
        cmd = ["qemu-img", "convert", "-f", "qcow2", "-O", "qcow2", src, out]
        subprocess.run(cmd, check=True)
        result[disk] = out

    return result


# =============================
# Running VM incremental (virsh backup-begin)
# =============================

def generate_backup_xml(vm, disk_paths, vm_dir):
    root = ET.Element("domainbackup", {"mode": "incremental"})
    disks_elem = ET.SubElement(root, "disks")

    targets = {}

    for disk in disk_paths.keys():
        inc_path = os.path.join(vm_dir, f"{disk}-inc.qcow2")
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
# Extent discovery (unified)
# =============================

def get_backup_extents(image):
    cmd = ["qemu-img", "map", "--output=json", image]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, check=True, text=True)
    layout = json.loads(proc.stdout)

    extents = []
    for e in layout:
        if e.get("data", False):
            extents.append({
                "offset": e["start"],
                "length": e["length"]
            })
    return extents


# =============================
# FastAPI: Backup endpoint
# =============================

@backup_router.post("/internal/backup/{vm}", response_model=BackupResponse)
def backup_vm(vm: str, checkpoint_id: str | None = Header(default=None, alias="Checkpoint-Id")):
    meta = load_meta(vm)
    conn, dom = get_vm(vm)
    state = get_vm_state(dom)
    disk_paths = get_disk_paths(dom)

    vm_dir = os.path.join(BACKUP_ROOT, vm)
    os.makedirs(vm_dir, exist_ok=True)

    # -------------------------
    # FULL BACKUP
    # -------------------------
    if checkpoint_id is None:
        full_images = run_full_backup(vm, dom)

        meta["mode"] = "cbt" if state == "running" else "image-diff"
        meta["last_checkpoint"] = None
        meta["disks"] = {}

        for disk, path in full_images.items():
            meta["disks"][disk] = {"last_backup": path}

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
                meta["disks"][disk]["last_backup"] = path
                result[disk] = path

            meta["mode"] = "cbt"
            meta["last_checkpoint"] = new_cp

        # ---- Stopped VM: image-diff ----
        else:
            for disk, current in disk_paths.items():
                previous = meta["disks"][disk]["last_backup"]
                inc_path = os.path.join(vm_dir, f"{disk}-inc.qcow2")

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
            new_checkpoint_id=new_cp,
            disks=result
        )


# =============================
# FastAPI: Get extents
# =============================

@backup_router.get("/internal/backup/{vm}/{disk}/extents")
def get_extents(vm: str, disk: str):
    meta = load_meta(vm)

    if disk not in meta["disks"]:
        raise HTTPException(status_code=404, detail="Disk not found")

    image = meta["disks"][disk]["last_backup"]
    if not os.path.exists(image):
        raise HTTPException(status_code=404, detail="Backup image not found")

    extents = get_backup_extents(image)

    return {
        "vm": vm,
        "disk": disk,
        "image": image,
        "extents": extents
    }


# =============================
# FastAPI: Range download
# =============================

@backup_router.get("/internal/backup/{vm}/{disk}/data")
def download_range(vm: str, disk: str, offset: int, length: int):
    meta = load_meta(vm)

    if disk not in meta["disks"]:
        raise HTTPException(status_code=404, detail="Disk not found")

    image = meta["disks"][disk]["last_backup"]
    if not os.path.exists(image):
        raise HTTPException(status_code=404, detail="Backup image not found")

    def reader():
        with open(image, "rb") as f:
            f.seek(offset)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(reader(), media_type="application/octet-stream")
