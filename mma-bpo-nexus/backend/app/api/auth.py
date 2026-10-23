"""Authentication, administrator setup, user management, and audit routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..repositories import ConflictError
from ..schemas import (
    LoginRequest,
    PasswordInput,
    RetentionUpdate,
    SetupRequest,
    UserAccessUpdate,
    UserCreateRequest,
)

COOKIE_NAME = "mma_nexus_session"
COOKIE_MAX_AGE = 8 * 60 * 60

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication and access"])


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def issue_session(request: Request, user: dict) -> JSONResponse:
    session = request.app.state.auth.create_session(user["id"])
    response = JSONResponse(content={
        "authenticated": True,
        "user": user,
        "csrfToken": session["csrfToken"],
        "expiresAt": session["expiresAt"],
    })
    response.set_cookie(
        COOKIE_NAME,
        session["token"],
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return response


def require_admin(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user or user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required")
    return user


@router.get("/status")
def auth_status(request: Request) -> dict:
    if request.app.state.preview_auth:
        return {
            "requiresSetup": False,
            "authenticated": True,
            **request.app.state.preview_auth,
        }
    setup = request.app.state.auth.requires_setup()
    session = request.app.state.auth.get_session(request.cookies.get(COOKIE_NAME))
    if not session:
        return {"requiresSetup": setup, "authenticated": False}
    return {
        "requiresSetup": False,
        "authenticated": True,
        **session,
    }


@router.post("/setup")
def setup(payload: SetupRequest, request: Request) -> JSONResponse:
    if not request.app.state.auth.requires_setup():
        raise ConflictError("Initial administrator setup is already complete")
    user = request.app.state.auth.create_bootstrap_admin(
        payload.username, payload.displayName, payload.password
    )
    request.app.state.auth.audit(
        user["id"], "bootstrap_admin_created", "user", user["id"],
        {"username": user["username"]}, client_ip(request),
    )
    return issue_session(request, user)


@router.post("/login")
def login(payload: LoginRequest, request: Request) -> JSONResponse:
    user = request.app.state.auth.authenticate(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    request.app.state.auth.audit(
        user["id"], "login_succeeded", "user", user["id"], {}, client_ip(request)
    )
    return issue_session(request, user)


@router.post("/logout")
def logout(request: Request) -> JSONResponse:
    token = request.cookies.get(COOKIE_NAME)
    session = request.app.state.auth.get_session(token)
    if session:
        request.app.state.auth.audit(
            session["user"]["id"], "logout", "user", session["user"]["id"],
            {}, client_ip(request),
        )
    request.app.state.auth.delete_session(token)
    response = JSONResponse(content={"ok": True, "authenticated": False})
    response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="strict")
    return response


@router.get("/me")
def me(request: Request) -> dict:
    return {"user": request.state.user, "expiresAt": request.state.auth_session["expiresAt"]}


@router.get("/users")
def users(request: Request) -> list[dict]:
    require_admin(request)
    return request.app.state.auth.list_users()


@router.post("/users")
def create_user(payload: UserCreateRequest, request: Request) -> dict:
    admin = require_admin(request)
    user = request.app.state.auth.create_user(
        payload.username, payload.displayName, payload.password, payload.role
    )
    request.app.state.auth.audit(
        admin["id"], "user_created", "user", user["id"],
        {"username": user["username"], "role": user["role"]}, client_ip(request),
    )
    return user


@router.patch("/users/{user_id}")
def update_user_access(user_id: str, payload: UserAccessUpdate, request: Request) -> dict:
    admin = require_admin(request)
    user = request.app.state.auth.set_user_access(user_id, payload.role, payload.active)
    request.app.state.auth.audit(
        admin["id"], "user_access_changed", "user", user_id,
        {"role": user["role"], "active": user["active"]}, client_ip(request),
    )
    return user


@router.post("/users/{user_id}/password")
def reset_password(user_id: str, payload: PasswordInput, request: Request) -> dict:
    admin = require_admin(request)
    user = request.app.state.auth.reset_password(user_id, payload.password)
    request.app.state.auth.audit(
        admin["id"], "password_reset", "user", user_id, {}, client_ip(request)
    )
    return user


@router.get("/audit")
def audit(request: Request, limit: int = Query(default=100, ge=1, le=200)) -> list[dict]:
    require_admin(request)
    return request.app.state.auth.list_audit(limit)


@router.get("/retention")
def retention(request: Request) -> dict:
    return request.app.state.repository.get_retention()


@router.put("/retention")
def update_retention(payload: RetentionUpdate, request: Request) -> dict:
    admin = require_admin(request)
    result = request.app.state.repository.update_retention(payload.transcriptDays, payload.autoDelete)
    request.app.state.auth.audit(
        admin["id"], "retention_updated", "retention_policy", "1", result, client_ip(request)
    )
    return result


@router.post("/retention/cleanup")
def cleanup_retention(request: Request) -> dict:
    admin = require_admin(request)
    deleted = request.app.state.repository.cleanup_expired()
    request.app.state.auth.audit(
        admin["id"], "retention_cleanup", "session", None,
        {"deletedSessions": deleted}, client_ip(request),
    )
    return {"deletedSessions": deleted}
