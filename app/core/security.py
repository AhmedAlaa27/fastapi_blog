from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import hashlib
import secrets
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash

from app.core.config import settings

password_hash = PasswordHash.recommended()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/users/token")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)


def generate_reset_token() -> str:
    """Generate a secure random token for password reset."""
    return secrets.token_urlsafe(32)


def hash_reset_token(token: str) -> str:
    """Hash the reset token using SHA-256."""
    return hashlib.sha256(token.encode()).hexdigest()


def _decode_token(token: str, expected_type: str) -> dict | None:
    """Decode a JWT and verify its `type` claim matches expected_type."""
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.algorithm],
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.InvalidTokenError:
        return None

    if payload.get("type") != expected_type:
        return None
    return payload


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(
            minutes=settings.access_token_expire_minutes,
        )
    to_encode.update(
        {
            "exp": expire,
            "iat": datetime.now(UTC),
            "jti": uuid4().hex,
            "type": "access",
        }
    )
    encoded_jwt = jwt.encode(
        to_encode,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )
    return encoded_jwt


def verify_access_token(token: str) -> str | None:
    """Verify a JWT access token and return the subject (user id) if valid."""
    payload = _decode_token(token, expected_type="access")
    if payload is None:
        return None
    return payload.get("sub")


def create_refresh_token(user_id: int) -> str:
    """Create a JWT refresh token."""
    expire = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    to_encode = {
        "sub": str(user_id),
        "exp": expire,
        "iat": datetime.now(UTC),
        "jti": uuid4().hex,
        "type": "refresh",
    }
    return jwt.encode(
        to_encode,
        settings.secret_key.get_secret_value(),
        algorithm=settings.algorithm,
    )


def verify_refresh_token(token: str) -> str | None:
    """Verify a JWT refresh token and return the subject (user id) if valid."""
    payload = _decode_token(token, expected_type="refresh")
    if payload is None:
        return None
    return payload.get("sub")
