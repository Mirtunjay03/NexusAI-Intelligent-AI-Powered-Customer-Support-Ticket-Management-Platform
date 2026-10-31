import asyncio

from fastapi import APIRouter, HTTPException, Request, status
from pymongo.errors import PyMongoError

router = APIRouter()


@router.get("/live")
async def liveness_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health")
async def health_check(request: Request) -> dict[str, str]:
    client = request.app.state.mongo_client
    try:
        await asyncio.to_thread(client.admin.command, "ping")
    except PyMongoError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "degraded", "database": "unavailable"},
        ) from exc

    return {"status": "ok", "database": "connected"}
