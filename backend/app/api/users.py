from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo import ReturnDocument

from app.api.deps import get_current_user, get_users_collection, require_role
from app.api.auth import serialize_user
from app.schemas.auth import UserResponse, UserRole
from app.schemas.users import UserUpdateRequest

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
def list_users(
    collection: Any = Depends(get_users_collection),
    _admin: dict[str, Any] = Depends(require_role(UserRole.ADMIN)),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[UserResponse]:
    users = collection.find({}, {"password_hash": 0}).sort("created_at", -1).skip(skip).limit(limit)
    return [serialize_user(user) for user in users]


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: str,
    collection: Any = Depends(get_users_collection),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> UserResponse:
    if current_user["role"] != UserRole.ADMIN and str(current_user["_id"]) != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted")

    try:
        object_id = ObjectId(user_id)
    except (InvalidId, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc

    user = collection.find_one({"_id": object_id})
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return serialize_user(user)


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    collection: Any = Depends(get_users_collection),
    _admin: dict[str, Any] = Depends(require_role(UserRole.ADMIN)),
) -> UserResponse:
    try:
        object_id = ObjectId(user_id)
    except (InvalidId, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc

    updates = payload.model_dump(exclude_unset=True)
    if updates.get("role") is not None:
        updates["role"] = updates["role"].value
    updates["updated_at"] = datetime.now(timezone.utc)

    user = collection.find_one_and_update(
        {"_id": object_id},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return serialize_user(user)
