"""
FocusForge AI — FastAPI backend entry point (Phase 1 scaffold).

Phase 1 scope:
  - GET /             → redirect to /docs
  - GET /api/health   → liveness check
  - Static frontend served from ../frontend/

NOT implemented in Phase 1:
  - Authentication / sessions
  - Database integration
  - Screen recording
  - Real productivity tracking
  - AI coach
  - Reward engine
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

# ── Environment ──────────────────────────────────────────
load_dotenv()                                       # reads .env if present
APP_ENV = os.getenv("APP_ENV", "development")

# ── App factory ──────────────────────────────────────────
app = FastAPI(
    title="FocusForge AI",
    description=(
        "Productivity tracking API — Phase 1 scaffold. "
        "Real tracking features are not yet implemented."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS (allow all origins during development) ───────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if APP_ENV == "development" else [],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Redirect browser root to the interactive API docs."""
    return RedirectResponse(url="/docs")


@app.get(
    "/api/health",
    summary="Health check",
    tags=["System"],
    response_description="Backend liveness status",
)
async def health() -> dict:
    """
    Returns a JSON payload confirming the backend is running.

    This endpoint is intentionally lightweight and requires no database
    or external service. Use it as a liveness / readiness probe.
    """
    return {
        "status": "ok",
        "app": "FocusForge AI",
        "version": "0.1.0",
        "phase": "1 — scaffold",
        "env": APP_ENV,
        "note": "Real productivity tracking is not yet implemented.",
    }


# ── Static frontend (served last so API routes take priority) ──
_frontend_dir = Path(__file__).parent.parent.parent / "frontend"
if _frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
