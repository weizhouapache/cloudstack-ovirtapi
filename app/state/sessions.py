import time

SESSIONS = {}

def store_session(auth_hash: str, session_data: dict):
    """
    Stores CloudStack session data by hashed credentials
    """
    SESSIONS[auth_hash] = {
        **session_data,
        "created": time.time()
    }
    print("Stored session data " + str(session_data.items()))

def get_session(auth_hash: str):
    """
    Retrieve CloudStack session info by hashed credentials
    """
    return SESSIONS.get(auth_hash)

def clear_expired(ttl=3600):
    """
    Optional: remove expired sessions
    """
    now = time.time()
    expired_keys = [k for k, v in SESSIONS.items() if now - v["created"] > ttl]
    for k in expired_keys:
        del SESSIONS[k]
