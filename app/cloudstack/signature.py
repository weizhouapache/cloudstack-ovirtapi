import hmac
import hashlib
import base64
from urllib.parse import quote_plus

def generate_signature(params: dict, secretkey: str) -> str:
    """
    Generate CloudStack API signature.

    Steps:
    1. Sort parameters by key (case-insensitive)
    2. URL-encode values
    3. Concatenate as query string
    4. Lowercase the query string
    5. HMAC-SHA1 with secret key, then Base64 encode
    """
    # 1. sort params by key
    sorted_params = sorted((k.lower(), v) for k, v in params.items())

    # 2. build query string
    query_string = "&".join(f"{k}={quote_plus(str(v))}" for k, v in sorted_params)

    # 3. HMAC-SHA1 & Base64
    signature = base64.b64encode(
        hmac.new(secretkey.encode("utf-8"), query_string.lower().encode("utf-8"), hashlib.sha1).digest()
    ).decode()

    return signature

