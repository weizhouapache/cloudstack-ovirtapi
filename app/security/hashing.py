import hmac
import hashlib
from app.config import SECURITY

def hash_auth(value: str) -> str:
    secret = SECURITY["hmac_secret"]
    return hmac.new(
        secret.encode(),
        value.encode(),
        hashlib.sha256
    ).hexdigest()

