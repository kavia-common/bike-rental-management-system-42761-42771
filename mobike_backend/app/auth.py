import os
import time
from functools import wraps
from typing import Any, Callable, Dict, Optional, Tuple

import jwt
from flask import request
from werkzeug.security import check_password_hash, generate_password_hash

from .storage import JsonFileStorage, _utc_ts

DEFAULT_JWT_TTL_SECONDS = 60 * 60 * 24  # 24 hours


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    """Read environment variable with default."""
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def get_jwt_secret() -> str:
    """
    Get JWT secret from env.

    Env:
      - MOBIKE_JWT_SECRET: secret used to sign JWTs (default is insecure/dev only)
    """
    return _get_env("MOBIKE_JWT_SECRET", "dev-insecure-secret-change-me")  # nosec B105


def get_jwt_ttl_seconds() -> int:
    """Return JWT TTL seconds from env MOBIKE_JWT_TTL_SECONDS."""
    raw = _get_env("MOBIKE_JWT_TTL_SECONDS", str(DEFAULT_JWT_TTL_SECONDS))
    try:
        return int(raw)  # type: ignore[arg-type]
    except Exception:
        return DEFAULT_JWT_TTL_SECONDS


def create_access_token(user: Dict[str, Any]) -> str:
    """Create a signed JWT for a user."""
    now = int(time.time())
    payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        "is_admin": bool(user.get("is_admin", False)),
        "iat": now,
        "exp": now + get_jwt_ttl_seconds(),
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm="HS256")


def decode_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT."""
    return jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])


def _extract_bearer_token() -> Optional[str]:
    """Extract Bearer token from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth:
        return None
    parts = auth.split(" ", 1)
    if len(parts) != 2:
        return None
    if parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def _public_user(u: Dict[str, Any]) -> Dict[str, Any]:
    """Remove sensitive fields from user record."""
    return {
        "id": u["id"],
        "name": u.get("name"),
        "email": u.get("email"),
        "is_admin": bool(u.get("is_admin", False)),
        "created_at": u.get("created_at"),
    }


def seed_admin_if_missing(storage: JsonFileStorage) -> None:
    """
    Ensure demo users have proper password hashes.

    Env:
      - MOBIKE_ADMIN_PASSWORD (default: admin123)
      - MOBIKE_DEMO_USER_PASSWORD (default: user123)
    """
    data = storage.get_all()
    admin_pw = _get_env("MOBIKE_ADMIN_PASSWORD", "admin123")
    user_pw = _get_env("MOBIKE_DEMO_USER_PASSWORD", "user123")

    changed = False
    for u in data.get("users", []):
        if u.get("email") == "admin@mobike.local":
            if not u.get("password_hash"):
                u["password_hash"] = generate_password_hash(admin_pw)
                changed = True
        if u.get("email") == "user@mobike.local":
            if not u.get("password_hash"):
                u["password_hash"] = generate_password_hash(user_pw)
                changed = True

    if changed:
        storage.update_all(data)


def register_user(
    storage: JsonFileStorage, name: str, email: str, password: str
) -> Tuple[Dict[str, Any], str]:
    """Create a user record and return (user_public, token)."""
    email_norm = email.strip().lower()
    if storage.find_one("users", email=email_norm) is not None:
        raise ValueError("Email already registered")

    data = storage.get_all()
    user_id = storage.next_id("users")
    now = _utc_ts()
    user = {
        "id": user_id,
        "name": name.strip(),
        "email": email_norm,
        "password_hash": generate_password_hash(password),
        "is_admin": False,
        "created_at": now,
    }
    data["users"].append(user)
    storage.update_all(data)

    token = create_access_token(user)
    return _public_user(user), token


def authenticate_user(storage: JsonFileStorage, email: str, password: str) -> Tuple[Dict[str, Any], str]:
    """Authenticate email/password and return (user_public, token)."""
    email_norm = email.strip().lower()
    user = storage.find_one("users", email=email_norm)
    if user is None:
        raise ValueError("Invalid email or password")
    if not check_password_hash(user.get("password_hash", ""), password):
        raise ValueError("Invalid email or password")

    token = create_access_token(user)
    return _public_user(user), token


def get_current_user(storage: JsonFileStorage) -> Dict[str, Any]:
    """Return current authenticated user (public + is_admin) or raise ValueError."""
    token = _extract_bearer_token()
    if token is None:
        raise ValueError("Missing Authorization: Bearer <token> header")
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError as e:
        raise ValueError("Token expired") from e
    except jwt.InvalidTokenError as e:
        raise ValueError("Invalid token") from e

    user_id = int(payload.get("sub"))
    user = storage.find_one("users", id=user_id)
    if user is None:
        raise ValueError("User not found")

    return user


def auth_required(storage: JsonFileStorage) -> Callable:
    """Decorator enforcing authenticated access."""

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            user = get_current_user(storage)
            return fn(user, *args, **kwargs)

        return wrapper

    return decorator


def admin_required(storage: JsonFileStorage) -> Callable:
    """Decorator enforcing admin access."""

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            user = get_current_user(storage)
            if not bool(user.get("is_admin", False)):
                return {"error": "Admin access required"}, 403
            return fn(user, *args, **kwargs)

        return wrapper

    return decorator
