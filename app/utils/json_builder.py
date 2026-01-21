import json
from fastapi import Response

def json_response(payload, status_code: int = 200) -> Response:
    """
    Build JSON response from object/dict/list.
    """
    json_content = json.dumps(payload, indent=2)
    
    return Response(
        content=json_content,
        media_type="application/json",
        status_code=status_code
    )
