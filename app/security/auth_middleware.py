from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from app.security.hashing import hash_auth
from app.state.sessions import get_session, store_session
from app.cloudstack.client import cs_request
import base64

class oVirtAPIAuthMiddleware(BaseHTTPMiddleware):
    """
    Enforces Basic Auth or Bearer token for UHAPI endpoints.
    Stores session in memory with hashed credentials.
    """

    async def dispatch(self, request: Request, call_next):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            raise HTTPException(status_code=401, detail="Authorization required")

        # Determine type
        if auth_header.startswith("Basic "):
            raw_value = self._decode_basic(auth_header)
        elif auth_header.startswith("Bearer "):
            raw_value = auth_header.strip()
        else:
            raise HTTPException(status_code=401, detail="Unsupported auth type")

        auth_hash = hash_auth(raw_value)
        request.state.auth_hash = auth_hash

        # Check cached session
        session = get_session(auth_hash)
        if session is None:
            # Login to CloudStack
            session_data = await self._cloudstack_login(raw_value)
            store_session(auth_hash, session_data)

        response = await call_next(request)
        return response

    def _decode_basic(self, auth_header: str) -> str:
        """
        Decode Basic auth header: returns username@domain:password
        """
        b64_value = auth_header.split(" ", 1)[1]
        decoded = base64.b64decode(b64_value).decode()
        return decoded  # Format: user@domain:password

    async def _cloudstack_login(self, raw_value: str) -> dict:
        """
        Calls CloudStack API login endpoint.
        Returns session data: apikey, secretkey, userid
        """
        try:
            username, password = raw_value.split(":", 1)
            if "@" in username:
                username, domain = username.split("@", 1)
            else:
                domain = ""

            params = {
                "username": username,
                "password": password,
                "domain": domain
            }
            # CloudStack login API call
            resp = await cs_request(request, "login", params)
            # Example expected response:
            # {"loginresponse": {"sessionkey": "...", "userid": "...", "account": "...", "apikey": "...", "secretkey": "..."}}
            return resp["loginresponse"]

        except Exception as e:
            raise HTTPException(status_code=401, detail="CloudStack authentication failed") from e

