from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.application.dto import LoginInput, RegisterUserInput
from app.application.services.auth_service import AuthService
from app.core.config import Settings
from app.core.dependencies import get_auth_service, get_current_user, get_settings_dependency
from app.core.security import REFRESH_TOKEN_COOKIE_NAME
from app.domain.entities import User
from app.presentation.schemas.auth import (
    AccessTokenResponse,
    GoogleLoginRequest,
    LoginRequest,
    RegisterRequest,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# The refresh cookie is scoped to this path so it is only ever sent to the
# auth endpoints that need it, not to every API request.
_REFRESH_COOKIE_PATH = "/api/v1/auth"


def _set_refresh_cookie(response: Response, refresh_token: str, settings: Settings) -> None:
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=settings.app_env != "development",
        samesite="lax",
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path=_REFRESH_COOKIE_PATH,
    )


@router.post("/register", response_model=AccessTokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings_dependency),
) -> AccessTokenResponse:
    tokens = await auth_service.register(RegisterUserInput(email=payload.email, password=payload.password))
    _set_refresh_cookie(response, tokens.refresh_token, settings)
    return AccessTokenResponse(access_token=tokens.access_token)


@router.post("/login", response_model=AccessTokenResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings_dependency),
) -> AccessTokenResponse:
    tokens = await auth_service.login(LoginInput(email=payload.email, password=payload.password))
    _set_refresh_cookie(response, tokens.refresh_token, settings)
    return AccessTokenResponse(access_token=tokens.access_token)


@router.post("/google/callback", response_model=AccessTokenResponse)
async def google_login(
    payload: GoogleLoginRequest,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings_dependency),
) -> AccessTokenResponse:
    tokens = await auth_service.login_with_google(payload.code, payload.redirect_uri)
    _set_refresh_cookie(response, tokens.refresh_token, settings)
    return AccessTokenResponse(access_token=tokens.access_token)


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings_dependency),
) -> AccessTokenResponse:
    refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE_NAME)
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token")
    tokens = await auth_service.refresh(refresh_token)
    _set_refresh_cookie(response, tokens.refresh_token, settings)
    return AccessTokenResponse(access_token=tokens.access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE_NAME)
    if refresh_token:
        await auth_service.logout(refresh_token)
    response.delete_cookie(REFRESH_TOKEN_COOKIE_NAME, path=_REFRESH_COOKIE_PATH)


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(id=str(current_user.id), email=current_user.email)
