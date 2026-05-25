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


MIN_PASSWORD_LENGTH = 8


def validate_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"密码至少需要 {MIN_PASSWORD_LENGTH} 个字符。")
    if not any(c.isupper() for c in password):
        raise ValueError("密码需要包含至少一个大写字母。")
    if not any(c.islower() for c in password):
        raise ValueError("密码需要包含至少一个小写字母。")
    if not any(c.isdigit() for c in password):
        raise ValueError("密码需要包含至少一个数字。")


def _sign(message: bytes) -> str:
    signature = hmac.new(
        settings.secret_key.encode("utf-8"),
        message,
        hashlib.sha256,
    ).digest()
    return _b64encode(signature)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_token(subject: str, token_type: str, expires_in_seconds: int, *, token_id: str | None = None, token_version: int | None = None) -> str:
    payload = {
        "sub": subject,
        "type": token_type,
        "exp": int(time.time()) + expires_in_seconds,
    }
    if token_id is not None:
        payload["jti"] = token_id
    if token_version is not None:
        payload["ver"] = token_version
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_part = _b64encode(payload_bytes)
    signature_part = _sign(payload_bytes)
    return f"{payload_part}.{signature_part}"


def create_access_token(subject: str, token_version: int | None = None) -> str:
    return create_token(subject, "access", settings.access_token_ttl_seconds, token_version=token_version)


def create_refresh_token(subject: str, token_id: str, ttl_seconds: int, token_version: int | None = None) -> str:
    return create_token(subject, "refresh", ttl_seconds, token_id=token_id, token_version=token_version)


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
