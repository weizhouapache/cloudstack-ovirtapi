import uuid
import time

BACKUPS = {}

def create_backup(vm_id, backup_id, to_checkpoint_id):
    BACKUPS[backup_id] = {
        "vm_id": vm_id,
        "to_checkpoint_id": to_checkpoint_id,
        "phase": "ready",
        "created": int(time.time())
    }
    return backup_id

def get_backup(backup_id):
    return BACKUPS.get(backup_id)

