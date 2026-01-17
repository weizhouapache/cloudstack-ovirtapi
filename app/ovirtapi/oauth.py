import secrets
import time
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Response, Form
from app.cloudstack.client import cs_request
from app.state.sessions import get_session, store_session
from app.security.hashing import hash_auth
import logging
import json

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory token store: token -> {user_info, expires_at, created_at}
token_store = {}

TOKEN_EXPIRY_HOURS = 24

def generate_token() -> str:
    """Generate a secure OAuth token."""
    return secrets.token_urlsafe(32)

def store_token(token: str, user_info: dict):
    """Store token with expiry time."""
    expires_at = time.time() + (TOKEN_EXPIRY_HOURS * 3600)
    token_store[token] = {
        "user_info": user_info,
        "expires_at": expires_at,
        "created_at": time.time(),
    }
    logger.info(f"Token stored for user: {user_info.get('account')}")

def verify_token(token: str) -> dict:
    """Verify token and return user info if valid."""
    if token not in token_store:
        return None

    token_data = token_store[token]

    # Check expiry
    if time.time() > token_data["expires_at"]:
        logger.warning(f"Token expired")
        del token_store[token]
        return None

    return token_data["user_info"]

def revoke_token(token: str):
    """Revoke a token."""
    if token in token_store:
        del token_store[token]
        logger.info(f"Token revoked")

@router.post("/oauth/token")
async def oauth_token(
    grant_type: str = Form(None),
    username: str = Form(None),
    password: str = Form(None),
    scope: str = Form(None),
):
    """
    OAuth 2.0 Token Endpoint.

    Form Parameters:
        grant_type: Must be "password" for user credentials grant
        username: User login (format: user@domain)
        password: User password
        scope: Optional scope (not used in basic implementation)

    Returns:
        200 OK: {
            "access_token": "...",
            "token_type": "Bearer",
            "expires_in": 86400,
            "scope": "ovirt-engine-api"
        }
        400 Bad Request: Invalid grant type or missing parameters
        401 Unauthorized: Invalid credentials
    """
    logger.debug(f"OAuth token request: grant_type={grant_type}, username={username}")

    # Validate grant type
    if grant_type != "password":
        logger.warning(f"Unsupported grant_type: {grant_type}")
        raise HTTPException(
            status_code=400,
            detail="Unsupported grant_type. Only 'password' is supported."
        )

    # Validate required parameters
    if not username or not password:
        raise HTTPException(
            status_code=400,
            detail="Missing required parameters: username, password"
        )

    # Parse username format: user@domain
    try:
        if "@" in username:
            user, domain = username.split("@", 1)
        else:
            user = username
            domain = ""
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid username format")

    # Authenticate with CloudStack
    try:
        import httpx
        from app.config import CLOUDSTACK

        # Direct CloudStack API call for login (doesn't need signature)
        api_url = CLOUDSTACK["endpoint"]

        params = {
            "command": "login",
            "username": user,
            "password": password,
            "domain": domain,
            "response": "json"
        }

        async with httpx.AsyncClient(verify=False) as client:
            response = await client.post(api_url, data=params)

            # Don't raise for status - we want to check the response body
            login_data = response.json()

        login_response = login_data.get("loginresponse", {})

        if "errortext" in login_response:
            logger.warning(f"Login failed for user: {username} - {login_response.get('errortext')}")
            raise HTTPException(
                status_code=401,
                detail="Invalid username or password"
            )

        # Extract session info
        session_data = login_response
        user_id = session_data.get("userid")
        account = session_data.get("account")
        sessionkey = session_data.get("sessionkey")
        jsessionid = response.cookies.get("JSESSIONID")

        if not user_id or not sessionkey:
            logger.warning(f"Login response missing required fields")
            raise HTTPException(
                status_code=401,
                detail="Login failed: incomplete response"
            )

        # Get API keys for this user
        params_keys = {
            "command": "getUserKeys",
            "id": user_id,
            "sessionkey": sessionkey,
            "response": "json"
        }

        async with httpx.AsyncClient(verify=False) as client:
            cookies = {"JSESSIONID": jsessionid, "sessionkey": sessionkey} if jsessionid else {}
            keys_response = await client.post(api_url, data=params_keys, cookies=cookies)
            keys_data = keys_response.json()

        user_keys = keys_data.get("getuserkeysresponse", {}).get("userkeys", {})

        if not user_keys:
            logger.warning(f"Failed to get API keys for user: {username}")
            raise HTTPException(
                status_code=401,
                detail="Failed to retrieve user API keys"
            )

        # Generate OAuth token
        access_token = generate_token()

        # Store token with user info
        user_info = {
            "user_id": user_id,
            "username": username,
            "account": account,
            "apikey": user_keys.get("apikey"),
            "secretkey": user_keys.get("secretkey"),
            "sessionkey": sessionkey,
            "jsessionid": jsessionid,
        }

        store_token(access_token, user_info)
        logger.info(f"OAuth token generated for user: {username}")

        # Return OAuth token response
        data = {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": TOKEN_EXPIRY_HOURS * 3600,
            "scope": "ovirt-engine-api"
        }

        # Convert the data to JSON with indentation
        json_data = json.dumps(data, indent=4)

        # Return the JSON data as a response
        return Response(json_data, media_type='application/json')

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OAuth token error: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail="Authentication failed"
        )

@router.post("/oauth/revoke")
async def oauth_revoke(token: str = Form(None)):
    """
    Revoke an OAuth token.

    Form Parameters:
        token: The access token to revoke

    Returns:
        200 OK: Token revoked
        400 Bad Request: Missing token
    """
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Missing required parameter: token"
        )

    revoke_token(token)

    return {
        "status": "revoked"
    }

def get_token_info(token: str) -> dict:
    """Get token info for middleware use."""
    return verify_token(token)
