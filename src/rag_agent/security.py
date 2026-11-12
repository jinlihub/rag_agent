"""密码散列与 JWT 签发/校验（不依赖 FastAPI，保持可独立测试）。"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from rag_agent.config import get_settings

_TOKEN_TTL = timedelta(days=7)
_PBKDF2_ROUNDS = 100_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return f"{salt.hex()}:{dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split(":", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), _PBKDF2_ROUNDS
    )
    return secrets.compare_digest(dk.hex(), dk_hex)


def create_access_token(user_id: int, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + _TOKEN_TTL,
    }
    return jwt.encode(payload, get_settings().auth_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    """校验并解码，失败（过期/伪造）抛 jwt 异常。"""
    return jwt.decode(token, get_settings().auth_secret, algorithms=["HS256"])
