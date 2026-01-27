from fastapi import Request

# =========================
# Internal Authentication
# =========================

def check_internal_auth(request: Request, INTERNAL_TOKEN: str) -> bool:
    """
    Check if the request contains the correct internal token in the Authorization header
    """
    if not INTERNAL_TOKEN:
        # If no internal token is configured, skip authentication
        return True

    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return False

    # Check if the header matches the internal token
    return auth_header.strip() == INTERNAL_TOKEN
