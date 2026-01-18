from fastapi import APIRouter, Request, HTTPException
from app.cloudstack.client import cs_request
from app.utils.xml_builder import xml_response
import time

router = APIRouter()

# In-memory store for jobs
jobs = {}

def cs_async_job_to_ovirt(job: dict) -> dict:
    """
    Convert a CloudStack Async Job dict to an oVirt-compatible Job payload.
    """
    # Map CloudStack job status to oVirt job status
    status_map = {
        "Pending": "started",
        "Running": "running", 
        "Completed": "finished",
        "Failed": "failed"
    }
    
    cs_status = job.get("jobstatus", 0)
    if cs_status == 0:  # Pending
        status = "started"
    elif cs_status == 1:  # Success
        status = "finished"
    elif cs_status == 2:  # Failure
        status = "failed"
    else:
        status = "running"
    
    return {
        "id": job.get("jobid", job.get("id", "")),
        "status": status,
        "description": job.get("jobprocstatus", "Async job"),
        "start_time": job.get("created", ""),
        "end_time": job.get("jobresult", {}).get("completed", "") if job.get("jobstatus") == 1 else "",
    }

@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    """
    Gets the status of a job.
    
    In the current implementation, this attempts to get the status of a CloudStack
    async job. If not found in CloudStack, it checks the local jobs store.
    """
    try:
        # First, try to get job status from CloudStack
        data = await cs_request(request, "queryAsyncJobResult", {"jobid": job_id})
        job_result = data.get("queryasyncjobresultresponse", {})
        
        if "errorcode" in job_result or "errortext" in job_result:
            # Job not found in CloudStack, check local store
            if job_id in jobs:
                job = jobs[job_id]
                payload = {
                    "id": job["id"],
                    "status": job["status"],
                    "description": job["description"],
                    "start_time": job.get("start_time", ""),
                    "end_time": job.get("end_time", "")
                }
            else:
                raise HTTPException(status_code=404, detail="Job not found")
        else:
            # Got job from CloudStack
            cs_job = job_result
            payload = cs_async_job_to_ovirt(cs_job)
            
            # Update local job store if it exists
            if job_id in jobs:
                jobs[job_id]["status"] = payload["status"]
                jobs[job_id]["end_time"] = payload["end_time"]
        
        return xml_response("job", payload)
    
    except HTTPException:
        raise
    except Exception as e:
        # If CloudStack request fails, check local store
        if job_id in jobs:
            job = jobs[job_id]
            payload = {
                "id": job["id"],
                "status": job["status"],
                "description": job["description"],
                "start_time": job.get("start_time", ""),
                "end_time": job.get("end_time", "")
            }
            return xml_response("job", payload)
        else:
            raise HTTPException(status_code=404, detail="Job not found")