from fastapi import APIRouter, HTTPException, Response, Query
from app.config import SSL
import os

router = APIRouter()

def read_certificate_file(cert_path: str) -> str:
    """Read certificate file and return content as string."""
    if not os.path.exists(cert_path):
        raise HTTPException(status_code=404, detail="Certificate file not found")

    try:
        with open(cert_path, 'r') as f:
            return f.read()
    except IOError as e:
        raise HTTPException(status_code=500, detail=f"Failed to read certificate: {str(e)}")

@router.get("/pki-resource")
async def get_pki_resource(resource: str = Query(None), format: str = Query(None)):
    """
    Get PKI resources (CA certificate, etc).

    Query Parameters:
        resource: Type of resource (ca-certificate, etc)
        format: Format of the resource (X509-PEM-CA, etc)

    Returns:
        200 OK: Certificate in requested format
        400 Bad Request: Missing or invalid parameters
        404 Not Found: Resource not found
    """
    # Validate parameters
    if not resource:
        raise HTTPException(
            status_code=400,
            detail="Missing required parameter: resource"
        )

    if not format:
        raise HTTPException(
            status_code=400,
            detail="Missing required parameter: format"
        )

    # Handle CA certificate request
    if resource.lower() == "ca-certificate" and format.upper() == "X509-PEM-CA":
        cert_file = SSL.get("cert_file", "./certs/server.crt")

        # Read the certificate
        cert_content = read_certificate_file(cert_file)

        # Return as PEM format
        return Response(
            content=cert_content,
            media_type="application/pkix-cert",
            headers={"Content-Disposition": "attachment; filename=ca-certificate.pem"}
        )

    # Unsupported resource or format
    raise HTTPException(
        status_code=400,
        detail=f"Unsupported resource='{resource}' or format='{format}'"
    )
