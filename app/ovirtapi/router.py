from fastapi import APIRouter, Request, Response, Depends
from app.utils.xml_builder import api_root_full
from app.state.sessions import get_session, remove_session
from app.cloudstack.client import cs_request

router = APIRouter()

from app.ovirtapi.infra import router as infra_router
from app.ovirtapi.vm import router as vm_router
from app.ovirtapi.backup import router as backup_router

router.include_router(infra_router)
router.include_router(vm_router)
router.include_router(backup_router)

@router.head("")
async def api_head(request: Request):
    return Response(status_code=200)

@router.get("")
async def api_get(request: Request):
    return api_root_full()

@router.api_route("/logout", methods=["GET", "POST"])
async def logout(request: Request):
    """
    oVirt-compatible logout endpoint (supports GET and POST).
    """
    await logout_current_session(request)
    return Response(status_code=200)

async def logout_current_session(request: Request):
    auth_hash = getattr(request.state, "auth_hash", None)
    if not auth_hash:
        return
    session = get_session(auth_hash)
    try:
        await cs_request(
            request=request,
            command="logout",
            params={},
            method="POST"
        )
    except Exception as e:
        # Logout failure should not block cleanup
        print(f"CloudStack logout failed: {e}")

    if session:
        print(f"Removing session for auth_hash: {auth_hash}")
        remove_session(auth_hash)
