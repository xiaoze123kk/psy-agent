from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from app.core.config import settings


PASSWORD_ITERATIONS = 390000


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode((raw + padding).encode("ascii"))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded_password: str) -> bool:
    try:
        algorithm, iterations_str, salt_b64, digest_b64 = encoded_password.split("$", 3)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    salt = _b64decode(salt_b64)
    expected_digest = _b64decode(digest_b64)
    computed_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        int(iterations_str),
    )
    return hmac.compare_digest(computed_digest, expected_digest)


def _sign(message: bytes) -> str:
    signature = hmac.new(
        settings.secret_key.encode("utf-8"),
        message,
        hashlib.sha256,
    ).digest()
    return _b64encode(signature)


def create_token(subject: str, token_type: str, expires_in_seconds: int) -> str:
    payload = {
        "sub": subject,
        "type": token_type,
        "exp": int(time.time()) + expires_in_seconds,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_part = _b64encode(payload_bytes)
    signature_part = _sign(payload_bytes)
    return f"{payload_part}.{signature_part}"


def create_access_token(subject: str) -> str:
    return create_token(subject, "access", settings.access_token_ttl_seconds)


def create_refresh_token(subject: str) -> str:
    return create_token(subject, "refresh", settings.refresh_token_ttl_seconds)


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload_part, signature_part = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("Malformed token.") from exc

    payload_bytes = _b64decode(payload_part)
    expected_signature = _sign(payload_bytes)
    if not hmac.compare_digest(signature_part, expected_signature):
        raise ValueError("Invalid token signature.")

    payload = json.loads(payload_bytes.decode("utf-8"))
    if payload.get("type") != expected_type:
        raise ValueError("Unexpected token type.")
    if int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("Token expired.")
    if not payload.get("sub"):
        raise ValueError("Missing token subject.")
    return payload
