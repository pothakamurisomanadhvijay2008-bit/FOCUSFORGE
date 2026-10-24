"""Local-day helpers for goals, streaks, and activity patterns.

Only completed, manually tracked work sessions are considered. Break sessions
never count towards a streak, and Private Mode is never stored at all.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable


def streak_stats(days: Iterable[date], today: date) -> dict:
    """Return the current and longest run of consecutive active local days.

    A streak that has not been extended yet today still counts from yesterday,
    so opening the dashboard in the morning never resets it to zero.
    """
    active = set(days)
    if not active:
        return {"current": 0, "longest": 0, "active_today": False}

    cursor = today if today in active else today - timedelta(days=1)
    current = 0
    while cursor in active:
        current += 1
        cursor -= timedelta(days=1)

    longest = run = 0
    previous: date | None = None
    for day in sorted(active):
        run = run + 1 if previous and (day - previous).days == 1 else 1
        longest = max(longest, run)
        previous = day

    return {"current": current, "longest": longest, "active_today": today in active}
