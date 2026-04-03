"""
Auth configuration and proxy endpoints.
All Supabase auth requests go through backend.
"""
from fastapi import APIRouter, HTTPException, Response, Request
from typing import Dict, Any
from pydantic import BaseModel
from fastapi_app.dependencies.auth import get_supabase_client
from fastapi_app.notebook_paths import _sanitize_user_id
from workflow_engine.utils import get_project_root
import logging

log = logging.getLogger(__name__)


def _should_use_secure_cookie(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    if forwarded_proto:
        return forwarded_proto == "https"
    return request.url.scheme == "https"


def _set_auth_cookies(request: Request, response: Response, access_token: str, refresh_token: str, access_max_age: int) -> None:
    secure_cookie = _should_use_secure_cookie(request)
    # Local dev over plain HTTP cannot persist `Secure` cookies.
    same_site = "lax"

    response.set_cookie(
        key="sb-access-token",
        value=access_token,
        httponly=True,
        secure=secure_cookie,
        samesite=same_site,
        max_age=access_max_age
    )
    response.set_cookie(
        key="sb-refresh-token",
        value=refresh_token,
        httponly=True,
        secure=secure_cookie,
        samesite=same_site,
        max_age=60 * 60 * 24 * 30
    )


def ensure_user_directory(user_email: str) -> None:
    """确保用户目录存在"""
    try:
        safe_user_id = _sanitize_user_id(user_email)
        user_dir = get_project_root() / "outputs" / safe_user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        log.info(f"User directory ensured: {user_dir}")
    except Exception as e:
        log.error(f"Failed to create user directory: {e}")

router = APIRouter(prefix="/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class SignupRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class VerifyOtpRequest(BaseModel):
    email: str
    token: str


class ResendOtpRequest(BaseModel):
    email: str


@router.get("/config")
async def get_auth_config() -> Dict[str, Any]:
    """
    Check if Supabase is configured.
    Frontend no longer needs Supabase credentials.
    """
    supabase = get_supabase_client()
    configured = supabase is not None

    return {
        "supabaseConfigured": configured,
        "authMode": "backend-proxy"  # 告诉前端使用后端代理模式
    }


@router.post("/login")
async def login(request: LoginRequest, response: Response, raw_request: Request) -> Dict[str, Any]:
    """Login via backend proxy"""
    log.info(f"Login attempt for email: {request.email}")
    supabase = get_supabase_client()
    if not supabase:
        log.error("Supabase client not configured")
        raise HTTPException(status_code=503, detail="Auth not configured")

    log.info(f"Supabase client: {type(supabase)}")
    try:
        log.info("Calling supabase.auth.sign_in_with_password")
        result = supabase.auth.sign_in_with_password({
            "email": request.email,
            "password": request.password
        })
        log.info(f"Login result: {result}")

        if result.session:
            # 确保用户目录存在
            ensure_user_directory(request.email)

            _set_auth_cookies(
                raw_request,
                response,
                result.session.access_token,
                result.session.refresh_token,
                result.session.expires_in,
            )

            return {
                "success": True,
                "user": {
                    "id": result.user.id,
                    "email": result.user.email
                }
            }
        else:
            raise HTTPException(status_code=401, detail="Login failed")
    except Exception as e:
        log.error(f"Login error: {e}", exc_info=True)
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/signup")
async def signup(request: SignupRequest, response: Response, raw_request: Request) -> Dict[str, Any]:
    """Signup via backend proxy"""
    supabase = get_supabase_client()
    if not supabase:
        raise HTTPException(status_code=503, detail="Auth not configured")

    try:
        result = supabase.auth.sign_up({
            "email": request.email,
            "password": request.password
        })

        if result.session:
            # 确保用户目录存在
            ensure_user_directory(request.email)

            _set_auth_cookies(
                raw_request,
                response,
                result.session.access_token,
                result.session.refresh_token,
                result.session.expires_in,
            )

            return {
                "success": True,
                "user": {
                    "id": result.user.id,
                    "email": result.user.email
                }
            }
        else:
            return {"success": True, "message": "Check your email for confirmation"}
    except Exception as e:
        log.error(f"Signup error: {e}", exc_info=True)
        error_msg = str(e)
        if "rate limit" in error_msg.lower():
            raise HTTPException(
                status_code=429,
                detail="注册请求过于频繁，请稍后再试（Rate limit exceeded, please try again later）"
            )
        raise HTTPException(status_code=400, detail=error_msg)


@router.post("/refresh")
async def refresh_token(request: Request, response: Response) -> Dict[str, Any]:
    """Refresh token via backend proxy"""
    supabase = get_supabase_client()
    if not supabase:
        raise HTTPException(status_code=503, detail="Auth not configured")

    refresh_token = request.cookies.get("sb-refresh-token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")

    try:
        result = supabase.auth.refresh_session(refresh_token)

        if result.session:
            _set_auth_cookies(
                request,
                response,
                result.session.access_token,
                result.session.refresh_token,
                result.session.expires_in,
            )

            return {
                "success": True,
                "user": {
                    "id": result.user.id,
                    "email": result.user.email
                }
            }
        else:
            raise HTTPException(status_code=401, detail="Refresh failed")
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/logout")
async def logout(response: Response) -> Dict[str, Any]:
    """Logout via backend proxy"""
    response.delete_cookie("sb-access-token")
    response.delete_cookie("sb-refresh-token")
    return {"success": True}


@router.post("/verify")
async def verify_otp(request: VerifyOtpRequest, response: Response, raw_request: Request) -> Dict[str, Any]:
    """Verify OTP token"""
    supabase = get_supabase_client()
    if not supabase:
        raise HTTPException(status_code=503, detail="Auth not configured")

    try:
        result = supabase.auth.verify_otp({
            "email": request.email,
            "token": request.token,
            "type": "email"
        })

        if result.session:
            # 确保用户目录存在
            ensure_user_directory(request.email)

            _set_auth_cookies(
                raw_request,
                response,
                result.session.access_token,
                result.session.refresh_token,
                result.session.expires_in,
            )

            return {
                "success": True,
                "user": {
                    "id": result.user.id,
                    "email": result.user.email
                }
            }
        else:
            raise HTTPException(status_code=400, detail="Verification failed")
    except Exception as e:
        log.error(f"Verify OTP error: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/resend")
async def resend_otp(request: ResendOtpRequest) -> Dict[str, Any]:
    """Resend OTP token"""
    supabase = get_supabase_client()
    if not supabase:
        raise HTTPException(status_code=503, detail="Auth not configured")

    try:
        supabase.auth.resend({
            "type": "signup",
            "email": request.email
        })
        return {"success": True, "message": "Verification email resent"}
    except Exception as e:
        log.error(f"Resend OTP error: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/session")
async def get_session(request: Request) -> Dict[str, Any]:
    """Get current session via backend proxy"""
    supabase = get_supabase_client()
    if not supabase:
        return {"user": None}

    access_token = request.cookies.get("sb-access-token")
    if not access_token:
        return {"user": None}

    try:
        result = supabase.auth.get_user(access_token)
        if result.user:
            return {
                "user": {
                    "id": result.user.id,
                    "email": result.user.email
                }
            }
        else:
            return {"user": None}
    except Exception:
        return {"user": None}
