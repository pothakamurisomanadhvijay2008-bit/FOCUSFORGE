"""Per-user manual work-session timer and dashboard summary endpoints."""

import time
import uuid
from datetime import date, datetime, time as day_time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from fastapi.responses import Response

from ..database import connect
from ..habits import streak_stats
from ..security import current_user, encode_time, utc_now
from ..rewards import COINS_PER_15_MINUTES, reward_coins
from ..spreadsheet import sessions_workbook

router = APIRouter(prefix="/api", tags=["Work sessions"])
SessionType = Literal["coding", "learning", "research", "assignment", "creative", "video", "break", "private"]


def require_user(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


class SessionStart(BaseModel):
    session_type: SessionType
    title: str = Field(min_length=1, max_length=80)
    task_description: str = Field(default="", max_length=500)
    goal: str = Field(default="", max_length=240)
    duration_minutes: int | None = Field(default=None, ge=1, le=240)

    @field_validator("title", "task_description", "goal")
    @classmethod
    def strip_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned and value:
            raise ValueError("Text cannot contain only whitespace")
        return cleaned


class SessionFinish(BaseModel):
    completion_note: str = Field(default="", max_length=500)
    focus_rating: int | None = Field(default=None, ge=1, le=5)

    @field_validator("completion_note")
    @classmethod
    def strip_completion(cls, value: str) -> str:
        return value.strip()


def _reconcile(request: Request, db, row):
    if row and row["status"] == "running" and row["boot_id"] != request.app.state.boot_id:
        db.execute(
            "UPDATE work_sessions SET status='interrupted', ended_at=?, boot_id=NULL WHERE id=?",
            (encode_time(utc_now()), row["id"]),
        )
        row = db.execute("SELECT * FROM work_sessions WHERE id=?", (row["id"],)).fetchone()
    return row


def _session_json(request: Request, db, row) -> dict:
    row = _reconcile(request, db, row)
    elapsed = int(row["elapsed_seconds"])
    started = request.app.state.active_since.get(row["id"])
    if row["status"] == "running" and row["boot_id"] == request.app.state.boot_id and started is not None:
        elapsed += max(0, int(time.monotonic() - started))
    return {
        "id": row["id"],
        "type": row["session_type"],
        "title": row["title"],
        "task_description": row["task_description"],
        "goal": row["goal"],
        "duration_minutes": row["duration_minutes"],
        "status": row["status"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "elapsed_seconds": elapsed,
        "completion_note": row["completion_note"],
        "focus_rating": row["focus_rating"],
        "distraction_count": row["distraction_count"],
        "reward_coins": row["reward_coins"],
    }


def _local_day(value: str | None, offset_minutes: int) -> date | None:
    """Convert a stored UTC timestamp to the browser's local calendar day."""
    if not value:
        return None
    try:
        instant = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return (instant.astimezone(timezone.utc) - timedelta(minutes=offset_minutes)).date()


def _get_owned(request: Request, db, user_id: int, session_id: str):
    row = db.execute("SELECT * FROM work_sessions WHERE id=? AND user_id=?", (session_id, user_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    return _reconcile(request, db, row)


@router.post("/sessions", status_code=201)
def start_session(payload: SessionStart, request: Request, user: dict = Depends(require_user)) -> dict:
    # Private sessions are deliberately client-only; reject any attempt to persist one.
    if payload.session_type == "private":
        raise HTTPException(status_code=400, detail="Private sessions are not sent to or stored by the server")
    now = encode_time(utc_now())
    session_id = str(uuid.uuid4())
    with connect(request.app.state.db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        live = db.execute(
            "SELECT * FROM work_sessions WHERE user_id=? AND status IN ('running','paused') ORDER BY started_at DESC, rowid DESC LIMIT 1",
            (user["id"],),
        ).fetchone()
        live = _reconcile(request, db, live) if live else None
        if live and live["status"] in {"running", "paused"}:
            raise HTTPException(status_code=409, detail="A session is already active")
        try:
            db.execute(
                """INSERT INTO work_sessions
                   (id,user_id,session_type,title,task_description,goal,duration_minutes,status,started_at,boot_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (session_id, user["id"], payload.session_type, payload.title, payload.task_description,
                 payload.goal, payload.duration_minutes, "running", now, request.app.state.boot_id),
            )
        except Exception as exc:
            if "one_live_session_per_user" in str(exc) or "UNIQUE constraint failed" in str(exc):
                raise HTTPException(status_code=409, detail="A session is already active") from exc
            raise
        row = db.execute("SELECT * FROM work_sessions WHERE id=?", (session_id,)).fetchone()
        request.app.state.active_since[session_id] = time.monotonic()
        return _session_json(request, db, row)


@router.get("/sessions/active")
def active_session(request: Request, user: dict = Depends(require_user)) -> dict | None:
    with connect(request.app.state.db_path) as db:
        row = db.execute(
            "SELECT * FROM work_sessions WHERE user_id=? AND status IN ('running','paused','interrupted') ORDER BY started_at DESC, rowid DESC LIMIT 1",
            (user["id"],),
        ).fetchone()
        return _session_json(request, db, row) if row else None


@router.get("/sessions")
def list_sessions(request: Request, limit: int = 10, user: dict = Depends(require_user)) -> list[dict]:
    if not 1 <= limit <= 50:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 50")
    with connect(request.app.state.db_path) as db:
        rows = db.execute(
            "SELECT * FROM work_sessions WHERE user_id=? ORDER BY started_at DESC, rowid DESC LIMIT ?",
            (user["id"], limit),
        ).fetchall()
        return [_session_json(request, db, row) for row in rows]


@router.get("/sessions/export.xlsx", include_in_schema=True)
def export_sessions(request: Request, user: dict = Depends(require_user)) -> Response:
    """Download this account's saved manual session history as an Excel workbook."""
    with connect(request.app.state.db_path) as db:
        rows = db.execute(
            """SELECT session_type, task_description, goal, status, started_at, ended_at,
                      elapsed_seconds, focus_rating, distraction_count, reward_coins
               FROM work_sessions WHERE user_id=? ORDER BY started_at DESC""",
            (user["id"],),
        ).fetchall()
    payload = sessions_workbook([dict(row) for row in rows])
    return Response(
        payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="focusforge-sessions.xlsx"', "Cache-Control": "no-store"},
    )


@router.get("/dashboard")
def dashboard_summary(
    request: Request,
    offset_minutes: int = 0,
    local_date: date = Query(default_factory=date.today),
    user: dict = Depends(require_user),
) -> dict:
    if not -840 <= offset_minutes <= 840:
        raise HTTPException(status_code=422, detail="Invalid timezone offset")
    local_day = datetime.combine(local_date, day_time.min, timezone.utc)
    start = local_day + timedelta(minutes=offset_minutes)
    end = start + timedelta(days=1)
    with connect(request.app.state.db_path) as db:
        row = db.execute(
            """SELECT COUNT(*) AS sessions, COALESCE(SUM(elapsed_seconds),0) AS seconds
               FROM work_sessions WHERE user_id=? AND status='completed' AND session_type!='break'
               AND ended_at>=? AND ended_at<?""",
            (user["id"], encode_time(start), encode_time(end)),
        ).fetchone()
        coins = db.execute(
            "SELECT COALESCE(SUM(reward_coins),0) FROM work_sessions WHERE user_id=? AND status='completed'",
            (user["id"],),
        ).fetchone()[0]
        totals = db.execute(
            """SELECT COUNT(*) AS sessions, COALESCE(SUM(elapsed_seconds),0) AS seconds,
                      COALESCE(SUM(distraction_count),0) AS distractions
               FROM work_sessions WHERE user_id=? AND status='completed' AND session_type!='break'""",
            (user["id"],),
        ).fetchone()
        goal_row = db.execute(
            "SELECT daily_goal_minutes FROM user_settings WHERE user_id=?", (user["id"],)
        ).fetchone()
        ended_rows = db.execute(
            """SELECT ended_at FROM work_sessions
               WHERE user_id=? AND status='completed' AND session_type!='break' AND ended_at IS NOT NULL""",
            (user["id"],),
        ).fetchall()

    goal_minutes = int(goal_row["daily_goal_minutes"]) if goal_row else 0
    today_seconds = int(row["seconds"])
    goal_percent = round(today_seconds / (goal_minutes * 60) * 100, 1) if goal_minutes else None
    active_days = {
        day for day in (_local_day(entry["ended_at"], offset_minutes) for entry in ended_rows) if day
    }
    return {
        "completed_sessions": row["sessions"],
        "productive_seconds": today_seconds,
        "coin_balance": int(coins),
        "coin_rates_per_15_minutes": COINS_PER_15_MINUTES,
        "goal": {
            "daily_goal_minutes": goal_minutes,
            "today_focus_seconds": today_seconds,
            "percent": goal_percent,
            "met": bool(goal_minutes and today_seconds >= goal_minutes * 60),
        },
        "streak": streak_stats(active_days, local_date),
        "totals": {
            "completed_sessions": int(totals["sessions"]),
            "focus_seconds": int(totals["seconds"]),
            "distractions": int(totals["distractions"]),
            "coins": int(coins),
        },
    }


class GoalUpdate(BaseModel):
    daily_goal_minutes: int = Field(ge=0, le=720)


@router.put("/goals")
def update_goal(payload: GoalUpdate, request: Request, user: dict = Depends(require_user)) -> dict:
    """Save the account's daily focus goal in minutes (0 clears the goal)."""
    with connect(request.app.state.db_path) as db:
        db.execute(
            """INSERT INTO user_settings(user_id, daily_goal_minutes, updated_at) VALUES(?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 daily_goal_minutes=excluded.daily_goal_minutes,
                 updated_at=excluded.updated_at""",
            (user["id"], payload.daily_goal_minutes, encode_time(utc_now())),
        )
    return {"daily_goal_minutes": payload.daily_goal_minutes}


def _transition(
    request: Request,
    session_id: str,
    user: dict,
    action: str,
    completion_note: str = "",
    focus_rating: int | None = None,
) -> dict:
    with connect(request.app.state.db_path) as db:
        row = _get_owned(request, db, user["id"], session_id)
        status_now = row["status"]
        elapsed = int(row["elapsed_seconds"])
        started = request.app.state.active_since.get(session_id)
        if status_now == "running" and row["boot_id"] == request.app.state.boot_id and started is not None:
            elapsed += max(0, int(time.monotonic() - started))

        if action == "pause":
            if status_now == "running":
                db.execute("UPDATE work_sessions SET status='paused', elapsed_seconds=?, boot_id=NULL WHERE id=?", (elapsed, session_id))
                request.app.state.active_since.pop(session_id, None)
        elif action == "resume":
            if status_now == "paused":
                db.execute("UPDATE work_sessions SET status='running', boot_id=? WHERE id=?", (request.app.state.boot_id, session_id))
                request.app.state.active_since[session_id] = time.monotonic()
            elif status_now != "running":
                raise HTTPException(status_code=409, detail="Only a paused session can resume")
        elif action == "checkpoint":
            if status_now == "running":
                db.execute("UPDATE work_sessions SET elapsed_seconds=? WHERE id=?", (elapsed, session_id))
                request.app.state.active_since[session_id] = time.monotonic()
        elif action == "stop":
            if status_now in {"running", "paused"}:
                coins = reward_coins(row["session_type"], elapsed)
                db.execute(
                    "UPDATE work_sessions SET status='completed', elapsed_seconds=?, ended_at=?, boot_id=NULL, completion_note=?, focus_rating=?, reward_coins=? WHERE id=?",
                    (elapsed, encode_time(utc_now()), completion_note, focus_rating, coins, session_id),
                )
                request.app.state.active_since.pop(session_id, None)
            elif status_now == "interrupted":
                db.execute("UPDATE work_sessions SET status='abandoned', boot_id=NULL WHERE id=?", (session_id,))
        updated = db.execute("SELECT * FROM work_sessions WHERE id=?", (session_id,)).fetchone()
        return _session_json(request, db, updated)


@router.post("/sessions/{session_id}/pause")
def pause_session(session_id: str, request: Request, user: dict = Depends(require_user)) -> dict:
    return _transition(request, session_id, user, "pause")


@router.post("/sessions/{session_id}/resume")
def resume_session(session_id: str, request: Request, user: dict = Depends(require_user)) -> dict:
    return _transition(request, session_id, user, "resume")


@router.post("/sessions/{session_id}/checkpoint")
def checkpoint_session(session_id: str, request: Request, user: dict = Depends(require_user)) -> dict:
    return _transition(request, session_id, user, "checkpoint")


@router.post("/sessions/{session_id}/distractions")
def log_distraction(session_id: str, request: Request, user: dict = Depends(require_user)) -> dict:
    with connect(request.app.state.db_path) as db:
        row = _get_owned(request, db, user["id"], session_id)
        if row["status"] not in {"running", "paused"}:
            raise HTTPException(status_code=409, detail="Distractions can only be logged during an active session")
        db.execute("UPDATE work_sessions SET distraction_count=distraction_count+1 WHERE id=?", (session_id,))
        updated = db.execute("SELECT * FROM work_sessions WHERE id=?", (session_id,)).fetchone()
        return _session_json(request, db, updated)


@router.post("/sessions/{session_id}/stop")
def stop_session(
    session_id: str,
    request: Request,
    payload: SessionFinish | None = None,
    user: dict = Depends(require_user),
) -> dict:
    return _transition(
        request,
        session_id,
        user,
        "stop",
        payload.completion_note if payload else "",
        payload.focus_rating if payload else None,
    )
