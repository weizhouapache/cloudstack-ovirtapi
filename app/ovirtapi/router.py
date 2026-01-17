from fastapi import APIRouter, Request, Response, Depends
from app.xml.builder import api_root_full

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
    return Response(
        content=api_root_full(),
        media_type="application/xml"
    )
