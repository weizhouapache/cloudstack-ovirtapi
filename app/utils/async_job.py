import asyncio
from fastapi import Request, HTTPException
from app.cloudstack.client import cs_request
from app.utils.logging_config import logger

# Job status codes
JOB_STATUS_PENDING = 0
JOB_STATUS_SUCCEEDED = 1
JOB_STATUS_FAILED = 2

# Job progress codes
JOB_PROGRESS_PENDING = 0
JOB_PROGRESS_RUNNING = 1


async def wait_for_job(request: Request, job_id: str, timeout: int = 300, poll_interval: int = 2):
    """
    Poll an async job until completion.

    Args:
        request: FastAPI Request object
        job_id: CloudStack job ID
        timeout: Maximum time to wait in seconds (default 5 minutes)
        poll_interval: Seconds between polls (default 2 seconds)

    Returns:
        dict: The job result data if successful

    Raises:
        HTTPException: If job fails or times out
    """
    elapsed = 0

    while elapsed < timeout:
        try:
            response = await cs_request(
                request,
                "queryAsyncJobResult",
                {"jobid": job_id}
            )

            job_result = response.get("queryasyncjobresultresponse", {})
            job_status = int(job_result.get("jobstatus", JOB_STATUS_PENDING))
            job_progress = int(job_result.get("jobprocstatus", 0))

            logger.debug(f"Job {job_id}: status={job_status}, progress={job_progress}%")

            # Job succeeded
            if job_status == JOB_STATUS_SUCCEEDED:
                logger.info(f"Job {job_id} completed successfully")
                return job_result.get("jobresult", {})

            # Job failed
            if job_status == JOB_STATUS_FAILED:
                error_text = job_result.get("jobresultcode", "Unknown error")
                logger.error(f"Job {job_id} failed: {error_text}")
                raise HTTPException(
                    status_code=400,
                    detail=f"CloudStack job failed: {error_text}"
                )

            # Job still pending/processing
            logger.debug(f"Job {job_id} still running... ({job_progress}%)")
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error polling job {job_id}: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error waiting for job: {str(e)}"
            )

    # Timeout
    logger.error(f"Job {job_id} timed out after {timeout} seconds")
    raise HTTPException(
        status_code=408,
        detail=f"Job execution timeout after {timeout} seconds"
    )


def get_job_id(response: dict) -> str:
    """
    Extract job ID from CloudStack async response.

    Args:
        response: CloudStack API response dict

    Returns:
        str: Job ID if found, empty string otherwise
    """
    # Try to find jobid in the response
    for key, value in response.items():
        if isinstance(value, dict):
            if "jobid" in value:
                return value["jobid"]

    return ""


# In-memory store for job information
jobs = {}


def create_job_record(job_id: str, description: str = "Job in progress"):
    """
    Create a job record in the in-memory store.
    """
    import time
    current_time = int(time.time() * 1000)  # Milliseconds since epoch
    start_time = int(time.time() * 1000 - 2000)

    job_record = {
        "id": job_id,
        "description": description,
        "status": "finished",
        "auto_cleared": "true",
        "external": "false",
        "start_time": start_time,
        "end_time": current_time,
        "last_updated": current_time,
        "owner": {
            "href": "/ovirt-engine/api/users/c067a148-e4d5-11f0-98ce-00163e6c35f4",
            "id": "c067a148-e4d5-11f0-98ce-00163e6c35f4"
        },
        "actions": {
            "link": [
                {
                    "href": f"/ovirt-engine/api/jobs/{job_id}/clear",
                    "rel": "clear"
                },
                {
                    "href": f"/ovirt-engine/api/jobs/{job_id}/end",
                    "rel": "end"
                }
            ]
        },
        "link": [
            {
                "href": f"/ovirt-engine/api/jobs/{job_id}/steps",
                "rel": "steps"
            }
        ],
        "href": f"/ovirt-engine/api/jobs/{job_id}"
    }

    jobs[job_id] = job_record
    return job_record


def get_job_record(job_id: str):
    """
    Get a job record from the in-memory store.
    """
    if job_id in jobs:
        return jobs[job_id]
    else:
        # If job doesn't exist in memory, create a default one for demonstration
        return create_job_record(job_id, f"Job {job_id}")
