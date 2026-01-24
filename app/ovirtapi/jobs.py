from fastapi import APIRouter, Request
from app.utils.async_job import get_job_record
from app.utils.response_builder import create_response

router = APIRouter()


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    """
    Gets the status of an async job.
    
    Returns job information in oVirt API format.
    """
    job_info = get_job_record(job_id)

    return create_response(request, "job", job_info)