"""
tests/test_health.py

Phase 1 — smoke test for the /api/health endpoint.

Run from the project root:
    python -m pytest tests/ -v
"""

import pytest
from httpx import ASGITransport, AsyncClient

# Import the app after the package path is available
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "backend"))

from app.main import app


@pytest.mark.asyncio
async def test_health_returns_200():
    """GET /api/health must return HTTP 200."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}"
    )


@pytest.mark.asyncio
async def test_health_payload():
    """GET /api/health must return the expected JSON fields."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "FocusForge AI"
    assert "version" in data
    assert "phase" in data


@pytest.mark.asyncio
async def test_health_content_type():
    """Response must be JSON."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
    assert "application/json" in response.headers.get("content-type", "")
