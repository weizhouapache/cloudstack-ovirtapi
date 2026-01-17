import asyncio
import logging
from fastapi import Request, HTTPException
from app.cloudstack.client import cs_request

logger = logging.getLogger(__name__)

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
