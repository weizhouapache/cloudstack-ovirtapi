from fastapi import Request, Response
from app.utils.xml_builder import xml_response
from app.utils.json_builder import json_response

def create_response(request: Request, root_name: str, payload, status_code: int = 200) -> Response:
    """
    Creates a response based on the Accept header in the request.
    Returns XML if Accept header contains 'application/xml', otherwise returns JSON.
    """
    # Check if the request has Accept header requesting XML
    if request and hasattr(request, 'headers') and "accept" in request.headers:
        accept_header = request.headers["accept"].lower()
        if "application/xml" in accept_header:
            return xml_response(root_name, payload, status_code)

    # Default to JSON response
    return json_response(payload, status_code)

def api_root_full(request=None):
    """
    Returns API root response, either JSON or XML based on Accept header.
    Returns JSON by default, XML if Accept header contains 'application/xml'.
    """
    payload = {
        "product_info": {
            "name": "CloudStack oVirtAPI Server",
            "vendor": "Wei Zhou",
        }
    }

    # Check if the request has Accept header requesting XML
    if request and "accept" in request.headers:
        accept_header = request.headers["accept"].lower()
        if "application/xml" in accept_header:
            return xml_response("api", payload)

    # Default to JSON response
    return json_response(payload)
