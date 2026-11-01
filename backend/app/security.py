import hashlib
import hmac
import os

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from . import models
from .config import EXTENSION_API_KEY
from .database import get_db

# PBKDF2-SHA256 via the stdlib - deliberately not passlib/bcrypt: recent
# bcrypt releases made their length check stricter in a way that breaks
# passlib's own internal self-test (ValueError: password cannot be
# longer than 72 bytes - confirmed hitting this at startup with
# passlib==1.7.4 + current bcrypt), and pinning a compatible bcrypt
# version is one more thing to get right/keep pinned under time
# pressure. PBKDF2-SHA256 with a high iteration count needs nothing but
# the standard library and is still an accepted password KDF.
PBKDF2_ITERATIONS = 390_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = password_hash.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, AttributeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return hmac.compare_digest(actual, expected)


def check_extension_api_key(request: Request):
    """Dependency for the extension-facing endpoints - a shared key, not
    a per-operator login (see project chat: any operator may handle any
    line's truck, so there is nothing to tell operators apart by)."""
    key = request.headers.get("X-API-Key")
    if key != EXTENSION_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")


def get_current_admin(request: Request, db: Session = Depends(get_db)) -> models.AdminUser:
    user_id = request.session.get("admin_user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})
    user = db.query(models.AdminUser).get(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})
    return user
