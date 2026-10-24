"""FocusForge AI FastAPI application."""

import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse

from .database import initialize
from .routers.auth import router as auth_router
from .routers.analytics import router as analytics_router
from .routers.sessions import router as sessions_router
from .routers.activity import router as activity_router
from .security import current_user

load_dotenv()
APP_ENV = os.getenv("APP_ENV", "development")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DEFAULT_DB_PATH = PROJECT_ROOT / "focusforge.sqlite3"


def create_app(database_path: Path | None = None) -> FastAPI:
    app = FastAPI(
        title="FocusForge AI",
        description="Manual focus-session tracking with per-user accounts.",
        version="0.2.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.db_path = Path(database_path or os.getenv("DATABASE_PATH", DEFAULT_DB_PATH))
    app.state.cookie_secure = APP_ENV == "production"
    app.state.boot_id = secrets.token_hex(16)
    app.state.active_since = {}
    app.state.db_initialized = False
    app.state.db_init_lock = threading.Lock()
    app.state.now = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")

    # The app is same-origin by design; no wildcard cross-origin access is needed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def ensure_database(request: Request, call_next):
        if not request.app.state.db_initialized:
            with request.app.state.db_init_lock:
                if not request.app.state.db_initialized:
                    initialize(request.app.state.db_path)
                    request.app.state.db_initialized = True
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
    app.include_router(auth_router)
    app.include_router(sessions_router)
    app.include_router(analytics_router)
    app.include_router(activity_router)

    @app.get("/", include_in_schema=False)
    def root(request: Request):
        if not current_user(request):
            return RedirectResponse(url="/login", status_code=303)
        return FileResponse(FRONTEND_DIR / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/login", include_in_schema=False)
    def login_page(request: Request):
        if current_user(request):
            return RedirectResponse(url="/", status_code=303)
        return FileResponse(FRONTEND_DIR / "login.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/health", summary="Health check", tags=["System"])
    def health() -> dict:
        return {"status": "ok", "app": "FocusForge AI", "version": "0.2.0"}

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(FRONTEND_DIR / "favicon.svg", media_type="image/svg+xml")

    @app.get("/assets/{asset_name}", include_in_schema=False)
    def frontend_asset(asset_name: str):
        if asset_name not in {"style.css", "app.js", "auth.js", "favicon.svg"}:
            raise HTTPException(status_code=404, detail="Asset not found")
        return FileResponse(FRONTEND_DIR / asset_name)

    return app


app = create_app()
