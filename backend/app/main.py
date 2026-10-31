from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.users import router as users_router
from app.api.tickets import router as tickets_router
from app.api.ai import router as ai_router
from app.api.analytics import router as analytics_router
from app.api.knowledge import router as knowledge_router
from app.core.config import Settings, get_settings
from app.database.mongo import create_mongo_client


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = create_mongo_client(app_settings.mongodb_uri)
        app.state.mongo_client = client
        try:
            yield
        finally:
            client.close()

    app = FastAPI(
        title="NexusAI API",
        description="API for the NexusAI customer support platform.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = app_settings

    @app.middleware("http")
    async def enforce_origin_checks(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin is not None and origin not in app_settings.allowed_origins:
                return JSONResponse(status_code=403, content={"detail": "Request origin is not allowed"})
            if (
                app_settings.app_env == "production"
                and request.cookies.get("nexusai_session")
                and origin is None
            ):
                return JSONResponse(status_code=403, content={"detail": "Origin header required for authenticated requests"})
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.include_router(health_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(users_router, prefix="/api")
    app.include_router(tickets_router, prefix="/api")
    app.include_router(analytics_router, prefix="/api")
    app.include_router(knowledge_router, prefix="/api")
    app.include_router(ai_router, prefix="/api")
    return app


app = create_app()
