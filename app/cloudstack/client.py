import httpx
from fastapi import Request
from app.config import CLOUDSTACK
from app.cloudstack.signature import generate_signature
from app.state.sessions import get_session
import logging

logger = logging.getLogger(__name__)

API_URL=CLOUDSTACK["endpoint"]

async def cs_request(request: Request, command: str, params: dict, method: str = "GET"):
    params["command"] = command
    params["response"] = "json"

    logger.debug(f"CloudStack request: {command}")

    # Skip signature for login/logout/getUserKeys
    if command.lower() not in ("login", "logout", "getuserkeys"):
        if request is None or not hasattr(request.state, "auth_hash"):
            raise ValueError("auth_hash is required for signed commands")

        auth_hash = request.state.auth_hash
        session = get_session(auth_hash)
        if session is None:
            raise ValueError("No session found for auth_hash")

        apikey = session["apikey"]
        secretkey = session["secretkey"]
        params["apikey"] = apikey
        params["signature"] = generate_signature(params, secretkey)

    cookies = {}
    if command.lower() in ("getuserkeys", "logout"):
        if request is None or not hasattr(request.state, "auth_hash"):
            if command.lower() == "logout":
                return
            raise ValueError("auth_hash is required for signed command: getuserkeys")

        auth_hash = request.state.auth_hash
        session = get_session(auth_hash)
        if session is None:
            if command.lower() == "logout":
                return
            raise ValueError("No session found for auth_hash")
        cookies = {"JSESSIONID": session["jsessionid"], "sessionkey": session["sessionkey"]}

    async with httpx.AsyncClient(verify=False) as client:
        if command.lower() in ("login", "logout", "getuserkeys") or method.upper() == "POST":
            r = await client.post(API_URL, data=params, cookies=cookies)
        else:
            r = await client.get(API_URL, params=params, cookies=cookies)
        r.raise_for_status()
        if request and r.cookies.get("JSESSIONID"):
            request.state.jsessionid = r.cookies.get("JSESSIONID")

        logger.debug(f"CloudStack response for {command}: {r.status_code}")
        return r.json()

