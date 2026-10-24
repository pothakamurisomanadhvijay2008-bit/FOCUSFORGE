"""Authenticated, user-scoped analytics endpoints."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from ..analytics import collect_analytics, render_analytics_chart
from ..security import current_user

router = APIRouter(prefix="/api/analytics", tags=["Personal analytics"])
Period = Literal["weekly", "monthly", "yearly"]


def require_user(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def get_analytics(
    request: Request,
    period: Period,
    anchor_date: date,
    timezone_name: str,
    user: dict,
) -> dict:
    return collect_analytics(request.app.state.db_path, user["id"], period, anchor_date, timezone_name)


@router.get("")
def analytics_summary(
    request: Request,
    period: Period = "weekly",
    anchor_date: date = Query(default_factory=date.today),
    timezone_name: str = Query(default="UTC", alias="time_zone", min_length=1, max_length=80),
    user: dict = Depends(require_user),
) -> dict:
    return get_analytics(request, period, anchor_date, timezone_name, user)


@router.get("/chart")
def analytics_chart(
    request: Request,
    period: Period = "weekly",
    anchor_date: date = Query(default_factory=date.today),
    timezone_name: str = Query(default="UTC", alias="time_zone", min_length=1, max_length=80),
    theme: Literal["light", "dark"] = "light",
    user: dict = Depends(require_user),
) -> Response:
    data = get_analytics(request, period, anchor_date, timezone_name, user)
    return Response(render_analytics_chart(data, theme), media_type="image/png",
                    headers={"Cache-Control": "no-store"})
