from collections.abc import Callable
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, HTTPException, Request, status
from jwt import InvalidTokenError

from app.core.config import Settings
from app.core.security import decode_access_token
from app.schemas.auth import UserRole


def get_users_collection(request: Request) -> Any:
    settings: Settings = request.app.state.settings
    return request.app.state.mongo_client[settings.mongodb_database]["users"]


def get_current_user(
    request: Request,
    collection: Any = Depends(get_users_collection),
) -> dict[str, Any]:
    token = request.cookies.get("nexusai_session")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Cookie"},
        )

    settings: Settings = request.app.state.settings
    try:
        payload = decode_access_token(token, settings)
        user_id = ObjectId(payload["sub"])
    except (InvalidTokenError, KeyError, TypeError, InvalidId) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Cookie"},
        ) from exc

    user = collection.find_one({"_id": user_id, "is_active": True})
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Cookie"},
        )
    return user


def require_role(*allowed_roles: UserRole) -> Callable[..., dict[str, Any]]:
    def check_role(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        if user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource",
            )
        return user

    return check_role

