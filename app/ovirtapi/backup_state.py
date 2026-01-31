import uuid
import time

BACKUPS = {}

def create_backup(vm_id, vm_name, backup_id, to_checkpoint_id, target_host_ip):

    # remove all backups for this VM
    for item_backup_id, backup in list(BACKUPS.items()):
        if backup["vm_id"] == vm_id:
            del BACKUPS[item_backup_id]

    BACKUPS[backup_id] = {
        "vm_id": vm_id,
        "vm_name": vm_name,
        "to_checkpoint_id": to_checkpoint_id,
        "target_host_ip": target_host_ip,
        "phase": "starting",
        "created": int(time.time())
    }

def get_backup(backup_id):
    return BACKUPS.get(backup_id)

def get_vm_backups(vm_id):
    return []       # TODO: fix it
    # return [backup for backup in BACKUPS.values() if backup["vm_id"] == vm_id]

def remove_backup(backup_id):
    BACKUPS.pop(backup_id)

def update_backup(backup_id, payload):
    BACKUPS[backup_id].update(payload)