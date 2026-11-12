"""注册 / 登录（FR-01、FR-02）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from rag_agent.security import create_access_token, hash_password, verify_password
from rag_agent.store import DuplicateUser, create_user, get_user_by_username

router = APIRouter(prefix="/api/auth", tags=["auth"])

_USER_TYPES = {"企业用户", "自然人"}


def _user_payload(user: dict) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "user_type": user["user_type"],
        "role": user["role"],
    }


class RegisterRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=64)
    email: str | None = None
    user_type: str = "自然人"
    display_name: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/register")
def register(req: RegisterRequest) -> dict:
    if req.user_type not in _USER_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "user_type 仅支持：企业用户 / 自然人")
    try:
        user_id = create_user(
            username=req.username.strip(),
            password_hash=hash_password(req.password),
            email=req.email,
            user_type=req.user_type,
            display_name=(req.display_name or "").strip() or None,
        )
    except DuplicateUser as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    user = get_user_by_username(req.username.strip())
    assert user is not None
    return {
        "access_token": create_access_token(user_id, user["role"]),
        "token_type": "bearer",
        "user": _user_payload(user),
    }


@router.post("/login")
def login(req: LoginRequest) -> dict:
    user = get_user_by_username(req.username.strip())
    if user is None or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    return {
        "access_token": create_access_token(user["id"], user["role"]),
        "token_type": "bearer",
        "user": _user_payload(user),
    }
