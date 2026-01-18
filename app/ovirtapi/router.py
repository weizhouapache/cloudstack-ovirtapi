from fastapi import APIRouter, Request, Response, Depends
from app.utils.xml_builder import api_root_full
from app.state.sessions import get_session, remove_session
from app.cloudstack.client import cs_request

router = APIRouter()

from app.ovirtapi.infra import router as infra_router
from app.ovirtapi.vm import router as vm_router
from app.ovirtapi.backup import router as backup_router
from app.ovirtapi.network import router as network_router
from app.ovirtapi.imagetransfer import router as imagetransfer_router
from app.ovirtapi.images import router as images_router
from app.ovirtapi.jobs import router as jobs_router
from app.ovirtapi.disks import router as disks_router
from app.ovirtapi.vmdisks import router as vmdisks_router
from app.ovirtapi.vmnics import router as vmnics_router
from app.ovirtapi.vmsnapshots import router as vmsnapshots_router
from app.ovirtapi.tags import router as tags_router
from app.ovirtapi.vnicprofiles import router as vnicprofiles_router

router.include_router(infra_router)
router.include_router(vm_router)
router.include_router(backup_router)
router.include_router(network_router)
router.include_router(imagetransfer_router)
router.include_router(images_router, prefix="/images")
router.include_router(jobs_router)
router.include_router(disks_router)
router.include_router(vmdisks_router)
router.include_router(vmnics_router)
router.include_router(vmsnapshots_router)
router.include_router(tags_router)
router.include_router(vnicprofiles_router)

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
