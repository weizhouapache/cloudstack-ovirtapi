from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from app.security.hashing import hash_auth
from app.state.sessions import get_session, store_session
from app.cloudstack.client import cs_request
from app.config import SERVER
import base64
import logging

logger = logging.getLogger(__name__)

class oVirtAPIAuthMiddleware(BaseHTTPMiddleware):
    """
    Enforces Basic Auth or Bearer token for UHAPI endpoints.
    Stores session in memory with hashed credentials.
    """

    async def dispatch(self, request: Request, call_next):
        # Skip auth for PKI services
        if "/services/" in request.url.path:
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header:
            logger.warning(f"Missing authorization header for {request.method} {request.url.path}")
            raise HTTPException(status_code=401, detail="Authorization required")

        # Determine type
        if auth_header.startswith("Basic "):
            raw_value = self._decode_basic(auth_header)
        elif auth_header.startswith("Bearer "):
            raw_value = auth_header.strip()
        else:
            logger.warning(f"Unsupported auth type for {request.method} {request.url.path}")
            raise HTTPException(status_code=401, detail="Unsupported auth type")

        auth_hash = hash_auth(raw_value)
        request.state.auth_hash = auth_hash
        logger.debug(f"Auth hash generated: {auth_hash[:16]}...")

        logoutUrl = SERVER.get("path", "/ovirt-engine/api") + "/logout"

        # Check cached session
        session = get_session(auth_hash)
        if session is None and request.url.path != logoutUrl:
            # Login to CloudStack
            session_data = await self._cloudstack_login(request, raw_value)
            if request.state.jsessionid:
                session_data["jsessionid"] = request.state.jsessionid
            # Store session data
            store_session(auth_hash, session_data)
            # Get User Keys
            session_data = await self._cloudstack_get_userkeys(request, session_data)
            # Update session data
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

    async def _cloudstack_login(self, request: Request, raw_value: str) -> dict:
        """
        Calls CloudStack API login endpoint.
        Returns session data: userid
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

    async def _cloudstack_get_userkeys(self, request: Request, session_data: dict) -> dict:
        """
        Given login session data (with sessionkey and userid),
        fetch the permanent CloudStack API keys (apikey and secretkey)
        and return updated session data.
        """
        if "sessionkey" not in session_data or "userid" not in session_data:
            raise ValueError("session_data must include 'sessionkey' and 'userid'")

        params = {
            "id": session_data["userid"],
            "sessionkey": session_data["sessionkey"],
            "response": "json"
        }

        # CloudStack getUserKeys command
        resp = await cs_request(request, "getUserKeys", params, method="GET")

        # Extract apikey and secretkey
        userkeys = resp.get("getuserkeysresponse", {}).get("userkeys", [])
        if not userkeys:
            raise ValueError("No user keys returned by CloudStack")

        session_data["apikey"] = userkeys["apikey"]
        session_data["secretkey"] = userkeys["secretkey"]

        return session_data
