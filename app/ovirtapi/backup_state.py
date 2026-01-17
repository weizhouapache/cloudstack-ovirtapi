import uuid
import time

BACKUPS = {}

def create_backup(vm_id, snapshot_ids):
    backup_id = str(uuid.uuid4())
    BACKUPS[backup_id] = {
        "vm_id": vm_id,
        "checkpoint_ids": snapshot_ids,
        "state": "ready",
        "created": time.time()
    }
    return backup_id

def get_backup(backup_id):
    return BACKUPS.get(backup_id)

