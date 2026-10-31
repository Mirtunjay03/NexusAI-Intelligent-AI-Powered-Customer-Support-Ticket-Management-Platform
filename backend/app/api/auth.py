from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pymongo.errors import DuplicateKeyError

from app.api.deps import get_current_user, get_users_collection
from app.core.config import Settings
from app.core.security import create_access_token, hash_password, verify_password
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, UserResponse, UserRole

router = APIRouter(prefix="/auth", tags=["authentication"])
SESSION_COOKIE = "nexusai_session"


def serialize_user(user: dict[str, Any]) -> UserResponse:
    return UserResponse(
        id=str(user["_id"]),
        name=user["name"],
        email=user["email"],
        role=user["role"],
        is_active=user["is_active"],
        created_at=user["created_at"],
    )


def set_session_cookie(response: Response, user_id: str, settings: Settings) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=create_access_token(user_id, settings),
        max_age=settings.jwt_access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.secure_cookie,
        samesite=settings.cookie_samesite,
        path="/",
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    response: Response,
    request: Request,
    collection: Any = Depends(get_users_collection),
) -> AuthResponse:
    normalized_email = str(payload.email).strip().lower()
    collection.create_index("email", unique=True)
    user = {
        "name": payload.name.strip(),
        "email": normalized_email,
        "password_hash": hash_password(payload.password),
        "role": UserRole.CUSTOMER.value,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    try:
        result = collection.insert_one(user)
    except DuplicateKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from exc

    user["_id"] = result.inserted_id
    settings: Settings = request.app.state.settings
    set_session_cookie(response, str(result.inserted_id), settings)
    return AuthResponse(user=serialize_user(user))


@router.post("/login", response_model=AuthResponse)
def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    collection: Any = Depends(get_users_collection),
) -> AuthResponse:
    normalized_email = str(payload.email).strip().lower()
    user = collection.find_one({"email": normalized_email})
    if (
        user is None
        or not user.get("is_active", False)
        or not verify_password(payload.password, user["password_hash"])
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect",
            headers={"WWW-Authenticate": "Cookie"},
        )

    settings: Settings = request.app.state.settings
    set_session_cookie(response, str(user["_id"]), settings)
    return AuthResponse(user=serialize_user(user))


@router.get("/me", response_model=UserResponse)
def get_me(user: dict[str, Any] = Depends(get_current_user)) -> UserResponse:
    return serialize_user(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, request: Request) -> Response:
    settings: Settings = request.app.state.settings
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=settings.secure_cookie,
        samesite=settings.cookie_samesite,
    )
    return response
