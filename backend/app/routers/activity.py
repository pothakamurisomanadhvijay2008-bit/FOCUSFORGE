"""App-activity and work-score API endpoints.

These endpoints let the frontend:
  - Poll the companion for live app status during a session
  - Retrieve the computed work score + app breakdown after a session ends
  - Get the app-classification rules so the UI can show what counts as productive

All data originates from the local Windows companion; nothing here touches
screen content, window titles, or keystrokes.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from ..app_classifier import (
    _PRODUCTIVE,
    classify_app,
    score_coin_multiplier,
    score_label,
    work_score,
)
from ..security import current_user

router = APIRouter(prefix="/api/activity", tags=["App activity"])

# The companion listens on 8765 (see desktop_companion/tracker.py COMPANION_PORT).
COMPANION_BASE = os.getenv("COMPANION_URL", "http://127.0.0.1:8765").rstrip("/")
COMPANION_TIMEOUT = 3  # seconds

SessionType = Literal["coding", "learning", "research", "assignment", "creative", "video"]


def require_user(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _companion_get(path: str, token: str) -> dict:
    """Fetch JSON from the local companion over loopback."""
    url = f"{COMPANION_BASE}{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=COMPANION_TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("detail", body)
        except Exception:
            detail = body
        raise HTTPException(status_code=exc.code, detail=detail)
    except (urllib.error.URLError, OSError):
        raise HTTPException(
            status_code=503,
            detail="Windows companion is not running. Start focusforge_companion.py first.",
        )


def _companion_post(path: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        f"{COMPANION_BASE}{path}",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=COMPANION_TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body_bytes = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body_bytes).get("detail", body_bytes)
        except Exception:
            detail = body_bytes
        raise HTTPException(status_code=exc.code, detail=detail)
    except (urllib.error.URLError, OSError):
        raise HTTPException(
            status_code=503,
            detail="Windows companion is not running.",
        )


def _companion_get_bytes(path: str, token: str) -> bytes:
    """Fetch raw bytes from the companion (e.g. for the XLSX export)."""
    url = f"{COMPANION_BASE}{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("detail", body)
        except Exception:
            detail = body
        raise HTTPException(status_code=exc.code, detail=detail)
    except (urllib.error.URLError, OSError):
        raise HTTPException(
            status_code=503,
            detail="Windows companion is not running. Start focusforge_companion.py first.",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
def companion_status(
    companion_token: str = Query(..., description="Pairing token shown in the companion window"),
    _user: dict = Depends(require_user),
) -> dict:
    """Proxy the companion's live status (current foreground app, elapsed seconds)."""
    return _companion_get("/api/status", companion_token)


@router.get("/rules")
def classification_rules(
    session_type: SessionType = Query(...),
    _user: dict = Depends(require_user),
) -> dict:
    """Return the productive-app list for the given session type.

    The frontend uses this to show which apps count towards the work score.
    """
    rules = _PRODUCTIVE.get(session_type, {})
    return {
        "session_type": session_type,
        "productive_apps": [
            {"app_name": name, "weight": info["weight"]}
            for name, info in sorted(rules.items())
        ],
    }


def _report_detail(recording_id: str, companion_token: str, session_type: str | None) -> dict:
    """Combine a completed recording's intervals with classification and score.

    This is the server-side source of truth for "which app ran for how long":
    every app gets seconds, minutes, share of tracked time, productivity
    category, and weight for the selected session type.
    """
    raw = _companion_get(
        f"/api/recordings/{quote(recording_id, safe='')}/intervals",
        companion_token,
    )
    intervals = raw.get("intervals", [])
    chosen = session_type or raw.get("session_type") or "coding"
    total_seconds = sum(max(0, int(item.get("elapsed_seconds") or 0)) for item in intervals)

    apps = []
    for interval in intervals:
        name = str(interval.get("app_name") or "Unknown app")
        seconds = max(0, int(interval.get("elapsed_seconds") or 0))
        info = classify_app(name, chosen)
        apps.append({
            "app_name": name,
            "elapsed_seconds": seconds,
            "minutes": round(seconds / 60, 2),
            "percent": round(seconds / total_seconds * 100, 1) if total_seconds else 0.0,
            "category": info["category"],
            "weight": info["weight"],
        })
    apps.sort(key=lambda item: item["elapsed_seconds"], reverse=True)

    scored = work_score(intervals, chosen)
    return {
        "recording_id": recording_id,
        "session_type": chosen,
        "status": raw.get("status"),
        "total_seconds": total_seconds,
        "total_minutes": round(total_seconds / 60, 2),
        "apps": apps,
        "score": scored["score"],
        "label": score_label(scored["score"]),
        "coin_multiplier": score_coin_multiplier(scored["score"]),
        "productive_seconds": scored["productive_seconds"],
        "distraction_seconds": scored["distraction_seconds"],
        "neutral_seconds": scored["neutral_seconds"],
    }


@router.get("/reports")
def list_activity_reports(
    companion_token: str = Query(..., description="Pairing token shown in the companion window"),
    _user: dict = Depends(require_user),
) -> dict:
    """List the app-activity recordings saved by the local companion."""
    return _companion_get("/api/recordings", companion_token)


@router.get("/reports/{recording_id}")
def activity_report_detail(
    recording_id: str,
    companion_token: str = Query(..., description="Pairing token shown in the companion window"),
    session_type: SessionType | None = Query(default=None),
    _user: dict = Depends(require_user),
) -> dict:
    """Return per-app durations, categories, and the work score for one recording."""
    return _report_detail(recording_id, companion_token, session_type)


class ScoreRequest(BaseModel):
    recording_id: str
    session_type: SessionType
    companion_token: str


@router.post("/score")
def compute_score(payload: ScoreRequest, _user: dict = Depends(require_user)) -> dict:
    """Fetch a completed companion recording's app intervals and compute work score.

    The frontend calls this after stopping a session to show the focus score card.
    """
    detail = _report_detail(payload.recording_id, payload.companion_token, payload.session_type)
    return {
        "recording_id": detail["recording_id"],
        "score": detail["score"],
        "label": detail["label"],
        "coin_multiplier": detail["coin_multiplier"],
        "productive_seconds": detail["productive_seconds"],
        "distraction_seconds": detail["distraction_seconds"],
        "neutral_seconds": detail["neutral_seconds"],
        "total_seconds": detail["total_seconds"],
        "app_breakdown": detail["apps"],
    }


@router.get("/score/{recording_id}")
def get_recording_score(
    recording_id: str,
    session_type: SessionType,
    companion_token: str = Query(...),
    _user: dict = Depends(require_user),
) -> dict:
    """GET variant for fetching a work score by recording ID (for history views)."""
    detail = _report_detail(recording_id, companion_token, session_type)
    return {
        "recording_id": detail["recording_id"],
        "score": detail["score"],
        "label": detail["label"],
        "coin_multiplier": detail["coin_multiplier"],
        "productive_seconds": detail["productive_seconds"],
        "distraction_seconds": detail["distraction_seconds"],
        "neutral_seconds": detail["neutral_seconds"],
        "total_seconds": detail["total_seconds"],
        "app_breakdown": detail["apps"],
    }


@router.get("/live-timeline")
def live_timeline(
    recording_id: str = Query(...),
    companion_token: str = Query(...),
    _user: dict = Depends(require_user),
) -> dict:
    """Return the current app intervals for a live (still-recording) session.

    Used by the dashboard's live timeline chart — polled every 5 s.
    The companion exposes this via /api/recordings/{id}/intervals-live.
    """
    raw = _companion_get(
        f"/api/recordings/{recording_id}/intervals-live",
        companion_token,
    )
    return raw


@router.get(
    "/export/{recording_id}",
    summary="Download enriched app-activity Excel report",
    response_class=Response,
)
def export_activity_report(
    recording_id: str,
    companion_token: str = Query(..., description="Pairing token shown in the companion window"),
    _user: dict = Depends(require_user),
) -> Response:
    """Proxy the companion's XLSX workbook through the authenticated FastAPI server.

    The workbook contains:
    - **Recording** sheet: session metadata, work score, productive/distraction %, coins estimate
    - **App timeline** sheet: every foreground-app interval with start/end times, category, weight
    - **App summary** sheet: per-app totals sorted by time spent, with category and productivity weight

    The file is returned as an attachment so the browser downloads it immediately.
    Only executable basenames are included — no window titles, keystrokes, or screen content.
    """
    xlsx_bytes = _companion_get_bytes(
        f"/api/recordings/{recording_id}/export.xlsx",
        companion_token,
    )
    filename = f"focusforge-{recording_id}-app-activity.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
