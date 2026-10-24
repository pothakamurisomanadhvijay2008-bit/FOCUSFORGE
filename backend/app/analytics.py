"""Private, self-reported session analytics and chart rendering."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO
from threading import Lock
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import MaxNLocator
import pandas as pd
import seaborn as sns
from fastapi import HTTPException

from .database import connect
from .habits import streak_stats
from .security import encode_time

ANALYTIC_PERIODS = ("weekly", "monthly", "yearly")
_PLOT_LOCK = Lock()


def _bucket_definitions(period: str, anchor: date) -> list[dict]:
    if period == "weekly":
        first = anchor - timedelta(days=6)
        return [
            {"key": day.isoformat(), "start": day, "end": day,
             "label": day.strftime("%a"), "detail": day.strftime("%b %d")}
            for day in (first + timedelta(days=index) for index in range(7))
        ]
    if period == "monthly":
        first = date(anchor.year, anchor.month, 1)
        definitions = []
        current = first
        while current <= anchor:
            # Weekly buckets run Monday to Sunday, clipped to the selected month.
            days_to_sunday = 6 - current.weekday()
            end = min(anchor, current + timedelta(days=days_to_sunday))
            definitions.append({
                "key": current.isoformat(), "start": current, "end": end,
                "label": f"{current.day}–{end.day}",
                "detail": f"{current.strftime('%b %d')}–{end.strftime('%b %d')}",
            })
            current = end + timedelta(days=1)
        return definitions

    return [
        {"key": f"{anchor.year}-{month:02d}",
         "start": date(anchor.year, month, 1),
         "end": date(anchor.year, month, monthrange(anchor.year, month)[1]),
         "label": date(anchor.year, month, 1).strftime("%b"),
         "detail": date(anchor.year, month, 1).strftime("%B %Y")}
        for month in range(1, anchor.month + 1)
    ]


def _period_rows(db_path, user_id: int, start: datetime, end: datetime) -> list[dict]:
    with connect(db_path) as db:
        rows = db.execute(
            """SELECT session_type, elapsed_seconds, ended_at, started_at, focus_rating,
                      distraction_count, reward_coins
               FROM work_sessions
               WHERE user_id=? AND status='completed' AND ended_at>=? AND ended_at<?
               ORDER BY ended_at""",
            (user_id, encode_time(start), encode_time(end)),
        ).fetchall()
    return [dict(row) for row in rows]


def collect_analytics(db_path, user_id: int, period: str, anchor: date, timezone_name: str) -> dict:
    if period not in ANALYTIC_PERIODS:
        raise HTTPException(status_code=422, detail="Period must be weekly, monthly, or yearly")
    try:
        user_zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(status_code=422, detail="Unknown time zone") from None

    if period == "weekly":
        start_date = anchor - timedelta(days=6)
    elif period == "monthly":
        start_date = date(anchor.year, anchor.month, 1)
    else:
        start_date = date(anchor.year, 1, 1)
    end_date = anchor + timedelta(days=1)
    start_at = datetime.combine(start_date, time.min, user_zone).astimezone(timezone.utc)
    end_at = datetime.combine(end_date, time.min, user_zone).astimezone(timezone.utc)
    definitions = _bucket_definitions(period, anchor)
    rows = _period_rows(db_path, user_id, start_at, end_at)

    frame = pd.DataFrame(rows, columns=[
        "session_type", "elapsed_seconds", "ended_at", "started_at", "focus_rating",
        "distraction_count", "reward_coins",
    ])
    if not frame.empty:
        frame["elapsed_seconds"] = pd.to_numeric(frame["elapsed_seconds"], errors="coerce").fillna(0).clip(lower=0)
        frame["focus_rating"] = pd.to_numeric(frame["focus_rating"], errors="coerce")
        frame["distraction_count"] = pd.to_numeric(frame["distraction_count"], errors="coerce").fillna(0).clip(lower=0)
        frame["reward_coins"] = pd.to_numeric(frame["reward_coins"], errors="coerce").fillna(0).clip(lower=0)
        local_end = pd.to_datetime(frame["ended_at"], utc=True).dt.tz_convert(user_zone)
        local_start = pd.to_datetime(frame["started_at"], utc=True, errors="coerce").dt.tz_convert(user_zone)
        frame["local_start"] = local_start.fillna(local_end)
        frame["local_hour"] = frame["local_start"].dt.hour
        frame["local_weekday"] = frame["local_start"].dt.weekday
        frame["local_day"] = local_end.dt.date
        day_to_bucket = {
            day: bucket["key"]
            for bucket in definitions
            for day in (bucket["start"] + timedelta(days=index)
                        for index in range((bucket["end"] - bucket["start"]).days + 1))
        }
        frame["bucket"] = frame["local_day"].map(day_to_bucket)
        frame = frame[frame["bucket"].notna()].copy()
    else:
        frame["local_day"] = pd.Series(dtype="object")
        frame["bucket"] = pd.Series(dtype="object")
        frame["local_hour"] = pd.Series(dtype="float64")
        frame["local_weekday"] = pd.Series(dtype="float64")

    work = frame[frame["session_type"] != "break"]
    breaks = frame[frame["session_type"] == "break"]
    work_seconds = int(work["elapsed_seconds"].sum()) if not work.empty else 0
    break_seconds = int(breaks["elapsed_seconds"].sum()) if not breaks.empty else 0
    distractions = int(work["distraction_count"].sum()) if not work.empty else 0
    focus_type_seconds = (
        {str(session_type): int(seconds) for session_type, seconds in
         work.groupby("session_type")["elapsed_seconds"].sum().items()}
        if not work.empty else {}
    )
    ratings = work["focus_rating"].dropna().to_numpy(dtype=float) if not work.empty else np.array([])
    work_session_minutes = work["elapsed_seconds"].to_numpy(dtype=float) / 60 if not work.empty else np.array([])
    focus_day_totals = work.groupby("local_day")["elapsed_seconds"].sum() if not work.empty else pd.Series(dtype=float)
    focus_day_minutes = focus_day_totals.to_numpy(dtype=float) / 60
    bucket_rows = []
    for bucket in definitions:
        subset = frame[frame["bucket"] == bucket["key"]]
        bucket_work = subset[subset["session_type"] != "break"]
        bucket_breaks = subset[subset["session_type"] == "break"]
        bucket_ratings = bucket_work["focus_rating"].dropna().to_numpy(dtype=float)
        bucket_work_hours = float(bucket_work["elapsed_seconds"].sum()) / 3600
        bucket_distractions = int(bucket_work["distraction_count"].sum())
        bucket_rows.append({
            **bucket,
            "focus_seconds": int(bucket_work["elapsed_seconds"].sum()) if not bucket_work.empty else 0,
            "break_seconds": int(bucket_breaks["elapsed_seconds"].sum()) if not bucket_breaks.empty else 0,
            "focus_sessions": int(len(bucket_work)),
            "break_sessions": int(len(bucket_breaks)),
            "focus_rating_mean": round(float(np.mean(bucket_ratings)), 2) if bucket_ratings.size else None,
            "focus_rating_samples": int(bucket_ratings.size),
            "distractions": bucket_distractions,
            "distractions_per_focus_hour": round(bucket_distractions / bucket_work_hours, 2) if bucket_work_hours else 0.0,
        })

    # ── Distributions for the in-page charts and the statistical atlas ──
    duration_minutes = work["elapsed_seconds"].to_numpy(dtype=float) / 60
    duration_seconds = work["elapsed_seconds"].to_numpy(dtype=float)
    duration_edges = [0, 15, 30, 45, 60, 90, np.inf]
    duration_labels = ["0-15", "15-30", "30-45", "45-60", "60-90", "90+"]
    session_length_distribution = []
    for index, label in enumerate(duration_labels):
        mask = (duration_minutes >= duration_edges[index]) & (duration_minutes < duration_edges[index + 1])
        session_length_distribution.append({
            "label": label,
            "focus_sessions": int(mask.sum()),
            "focus_seconds": int(duration_seconds[mask].sum()),
        })

    work_hours = work["local_hour"].to_numpy(dtype=float)
    work_weekdays = work["local_weekday"].to_numpy(dtype=float)
    hour_of_day = [
        {
            "hour": hour,
            "focus_sessions": int((work_hours == hour).sum()),
            "focus_seconds": int(duration_seconds[work_hours == hour].sum()),
        }
        for hour in range(24)
    ]
    weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weekday_pattern = [
        {
            "weekday": weekday,
            "label": label,
            "focus_sessions": int((work_weekdays == weekday).sum()),
            "focus_seconds": int(duration_seconds[work_weekdays == weekday].sum()),
        }
        for weekday, label in enumerate(weekday_labels)
    ]
    rating_distribution = [
        {"rating": rating, "samples": int((ratings == rating).sum())}
        for rating in range(1, 6)
    ]

    # ── Comparison with the previous period of equal length ──
    period_days = (anchor - start_date).days + 1
    previous_start_date = start_date - timedelta(days=period_days)
    previous_end_date = start_date - timedelta(days=1)
    previous_start_at = datetime.combine(previous_start_date, time.min, user_zone).astimezone(timezone.utc)
    previous_end_at = datetime.combine(start_date, time.min, user_zone).astimezone(timezone.utc)
    previous_rows = _period_rows(db_path, user_id, previous_start_at, previous_end_at)
    previous_focus_seconds = sum(
        int(item["elapsed_seconds"] or 0) for item in previous_rows if item["session_type"] != "break"
    )
    delta_percent = (
        round((work_seconds - previous_focus_seconds) / previous_focus_seconds * 100, 1)
        if previous_focus_seconds else None
    )

    # ── All-time streak from completed work sessions ──
    with connect(db_path) as db:
        ended_rows = db.execute(
            """SELECT ended_at FROM work_sessions
               WHERE user_id=? AND status='completed' AND session_type!='break' AND ended_at IS NOT NULL""",
            (user_id,),
        ).fetchall()
    all_days = {
        pd.to_datetime(row["ended_at"], utc=True).tz_convert(user_zone).date()
        for row in ended_rows
        if row["ended_at"]
    }
    calendar_days = max(1, (anchor - start_date).days + 1)
    active_days = int(focus_day_totals.size)
    coins_earned = int(work["reward_coins"].sum()) if not work.empty else 0
    return {
        "period": period,
        "start_date": start_date.isoformat(),
        "end_date": anchor.isoformat(),
        "timezone": timezone_name,
        "summary": {
            "focus_seconds": work_seconds,
            "break_seconds": break_seconds,
            "focus_type_seconds": focus_type_seconds,
            "focus_sessions": int(len(work)),
            "break_sessions": int(len(breaks)),
            "active_focus_days": active_days,
            "calendar_days": calendar_days,
            "active_day_rate_percent": round(active_days / calendar_days * 100, 1),
            "average_focus_minutes_per_active_day": round(float(np.mean(focus_day_minutes)), 1) if focus_day_minutes.size else None,
            "focus_minutes_stddev_per_active_day": round(float(np.std(focus_day_minutes)), 1) if focus_day_minutes.size else None,
            "median_focus_session_minutes": round(float(np.median(work_session_minutes)), 1) if work_session_minutes.size else None,
            "average_focus_rating": round(float(np.mean(ratings)), 2) if ratings.size else None,
            "focus_rating_samples": int(ratings.size),
            "reported_distractions": distractions,
            "distractions_per_focus_hour": round(distractions / (work_seconds / 3600), 2) if work_seconds else 0.0,
            "coins_earned": coins_earned,
        },
        "buckets": bucket_rows,
        "session_length_distribution": session_length_distribution,
        "hour_of_day": hour_of_day,
        "weekday_pattern": weekday_pattern,
        "rating_distribution": rating_distribution,
        "streak": streak_stats(all_days, anchor),
        "coins_earned": coins_earned,
        "comparison": {
            "previous_start_date": previous_start_date.isoformat(),
            "previous_end_date": previous_end_date.isoformat(),
            "previous_focus_seconds": previous_focus_seconds,
            "delta_percent": delta_percent,
        },
    }


def render_analytics_chart(analytics: dict, theme: str = "light") -> bytes:
    if theme not in {"light", "dark"}:
        theme = "light"
    dark = theme == "dark"
    palette = {
        "paper": "#182320" if dark else "#fffefa",
        "ink": "#e9eee8" if dark else "#253431",
        "muted": "#a9b6ad" if dark else "#78847c",
        "grid": "#34443e" if dark else "#e8e4d9",
        "focus": "#83a7ff" if dark else "#3159c9",
        "break": "#e9a170" if dark else "#df784b",
        "rating": "#8cbea0" if dark else "#4d8066",
        "distraction": "#e28b83" if dark else "#b94640",
        "gold": "#e9c46a" if dark else "#b78a2f",
    }
    buckets = analytics["buckets"]
    labels = [bucket["label"] for bucket in buckets]
    period_title = {"weekly": "weekly", "monthly": "monthly", "yearly": "yearly"}[analytics["period"]]
    with _PLOT_LOCK, plt.rc_context({
        "figure.facecolor": palette["paper"],
        "axes.facecolor": palette["paper"],
        "axes.edgecolor": palette["grid"],
        "axes.labelcolor": palette["muted"],
        "xtick.color": palette["muted"],
        "ytick.color": palette["muted"],
        "text.color": palette["ink"],
        "grid.color": palette["grid"],
        "savefig.facecolor": palette["paper"],
    }):
        sns.set_theme(style="whitegrid", context="notebook", rc={
            "figure.facecolor": palette["paper"], "axes.facecolor": palette["paper"],
            "axes.labelcolor": palette["muted"], "text.color": palette["ink"],
            "xtick.color": palette["muted"], "ytick.color": palette["muted"],
            "grid.color": palette["grid"],
        })
        figure = plt.figure(figsize=(13, 13.4))
        grid = figure.add_gridspec(3, 6, height_ratios=[1.0, 1.0, 1.0], hspace=.58, wspace=.55)
        focus_mix, type_mix = figure.add_subplot(grid[0, :3]), figure.add_subplot(grid[0, 3:])
        trend_axis, rating_axis, distraction_axis = (
            figure.add_subplot(grid[1, index * 2:(index + 1) * 2]) for index in range(3)
        )
        length_axis, hour_axis, weekday_axis = (
            figure.add_subplot(grid[2, index * 2:(index + 1) * 2]) for index in range(3)
        )
        trend_axes = [trend_axis, rating_axis, distraction_axis]
        pattern_axes = [length_axis, hour_axis, weekday_axis]
        figure.subplots_adjust(left=.07, right=.97, top=.86, bottom=.07)
        figure.suptitle(f"Your {period_title} rhythm",
                        x=.1, ha="left", y=.965, fontsize=17, fontweight="bold", color=palette["ink"])
        figure.text(.1, .915, f"{analytics['start_date']} — {analytics['end_date']} · manual sessions only",
                    ha="left", fontsize=9.5, color=palette["muted"])

        frame = pd.DataFrame(buckets)
        has_sessions = not frame.empty and (frame["focus_sessions"].sum() + frame["break_sessions"].sum()) > 0
        if not has_sessions:
            for axis in [focus_mix, type_mix, *trend_axes, *pattern_axes]:
                axis.set_axis_off()
            focus_mix.text(.5, .5, "Start logging sessions to see your trends.",
                           ha="center", va="center", transform=focus_mix.transAxes,
                           fontsize=13, color=palette["muted"])
        else:
            # ── Row 1 · time composition ──────────────────────────────────
            focus_mix.set_title("Your time · focus and breaks", loc="left", fontsize=11,
                                color=palette["ink"], pad=10)
            focus_values = [analytics["summary"].get("focus_seconds", 0),
                            analytics["summary"].get("break_seconds", 0)]
            if sum(focus_values):
                wedges, _, _ = focus_mix.pie(
                    focus_values, labels=None, colors=[palette["focus"], palette["break"]],
                    startangle=90, counterclock=False,
                    autopct=lambda value: f"{value:.0f}%" if value >= 4 else "",
                    pctdistance=.76, wedgeprops={"width": .34, "edgecolor": palette["paper"]},
                    textprops={"color": palette["ink"], "fontsize": 9},
                )
                focus_mix.legend(wedges, ["Focus", "Break"], loc="lower center", ncols=2,
                                 bbox_to_anchor=(.5, -.05), frameon=False, fontsize=9)
                focus_mix.text(0, 0, "Tracked\ntime", ha="center", va="center",
                               fontsize=9, color=palette["muted"])
            else:
                focus_mix.text(.5, .5, "No time recorded", ha="center", va="center",
                               transform=focus_mix.transAxes, color=palette["muted"])
                focus_mix.set_axis_off()

            type_seconds = analytics["summary"].get("focus_type_seconds", {})
            type_labels = {
                "coding": "Coding", "learning": "Learning", "research": "Research",
                "assignment": "Assignment", "creative": "Creative", "video": "Learning video",
                "special_focus": "Special Focus",
            }
            type_items = [(type_labels.get(key, key.replace("_", " ").title()), value)
                          for key, value in type_seconds.items() if value > 0]
            type_mix.set_title("Where your focus time went", loc="left", fontsize=11,
                               color=palette["ink"], pad=10)
            if type_items:
                wedges, _, _ = type_mix.pie(
                    [value for _, value in type_items], labels=None,
                    colors=sns.color_palette("crest", n_colors=len(type_items)),
                    startangle=90, counterclock=False,
                    autopct=lambda value: f"{value:.0f}%" if value >= 5 else "",
                    pctdistance=.76, wedgeprops={"width": .34, "edgecolor": palette["paper"]},
                    textprops={"color": palette["ink"], "fontsize": 9},
                )
                type_mix.legend(wedges, [label for label, _ in type_items], loc="lower center",
                                ncols=min(3, len(type_items)), bbox_to_anchor=(.5, -.05),
                                frameon=False, fontsize=8)
                type_mix.text(0, 0, "Focus\ntypes", ha="center", va="center",
                              fontsize=9, color=palette["muted"])
            else:
                type_mix.text(.5, .5, "No focus time yet", ha="center", va="center",
                              transform=type_mix.transAxes, color=palette["muted"])
                type_mix.set_axis_off()

            # ── Row 2 · rhythm and self-reports ───────────────────────────
            frame["label"] = pd.Categorical(frame["label"], categories=labels, ordered=True)
            usage = frame.melt(id_vars=["label"], value_vars=["focus_seconds", "break_seconds"],
                               var_name="kind", value_name="seconds")
            usage["minutes"] = usage["seconds"] / 60
            sns.barplot(data=usage, x="label", y="minutes", hue="kind", ax=trend_axis,
                        palette={"focus_seconds": palette["focus"], "break_seconds": palette["break"]},
                        errorbar=None, order=labels)
            trend_axis.set_title("Tracked time · focus and breaks", loc="left", fontsize=11,
                                 color=palette["ink"])
            trend_axis.set_ylabel("Minutes")
            trend_axis.set_xlabel("")
            trend_axis.legend(title="", labels=["Focus", "Break"], frameon=False, ncols=2,
                              loc="upper right")

            rating_rows = frame.dropna(subset=["focus_rating_mean"])
            if rating_rows.empty:
                rating_axis.text(.5, .5, "Add a self-rating when you end a focus session to see this trend.",
                                 ha="center", va="center", transform=rating_axis.transAxes,
                                 fontsize=10, color=palette["muted"])
                rating_axis.set_xticks(range(len(labels)), labels)
                rating_axis.set_ylim(1, 5)
            else:
                sns.lineplot(data=rating_rows, x="label", y="focus_rating_mean", marker="o",
                             color=palette["rating"], linewidth=2.4, ax=rating_axis, errorbar=None)
                rating_axis.set_ylim(1, 5)
                rating_axis.set_yticks([1, 2, 3, 4, 5])
            rating_axis.set_title("Self-rated concentration · 1 to 5", loc="left", fontsize=11,
                                  color=palette["ink"])
            rating_axis.set_ylabel("Rating")
            rating_axis.set_xlabel("")

            sns.barplot(data=frame, x="label", y="distractions_per_focus_hour", ax=distraction_axis,
                        color=palette["distraction"], errorbar=None, order=labels)
            distraction_axis.set_title("Distractions you logged per focus hour", loc="left",
                                       fontsize=11, color=palette["ink"])
            distraction_axis.set_ylabel("Events / hour")
            distraction_axis.set_xlabel("")
            distraction_axis.set_xticks(range(len(labels)), labels, rotation=0)

            # ── Row 3 · distributions ─────────────────────────────────────
            length_rows = pd.DataFrame(analytics.get("session_length_distribution", []))
            if not length_rows.empty and int(length_rows["focus_sessions"].sum()) > 0:
                sns.barplot(data=length_rows, x="label", y="focus_sessions", ax=length_axis,
                            color=palette["focus"], errorbar=None)
                length_axis.set_title("Work block lengths", loc="left", fontsize=11,
                                      color=palette["ink"])
                length_axis.set_ylabel("Sessions")
                length_axis.set_xlabel("Session length · minutes")
                length_axis.yaxis.set_major_locator(MaxNLocator(integer=True))
            else:
                length_axis.text(.5, .5, "No completed work blocks yet.", ha="center", va="center",
                                 transform=length_axis.transAxes, fontsize=10, color=palette["muted"])
                length_axis.set_axis_off()

            hour_rows = pd.DataFrame(analytics.get("hour_of_day", []))
            if not hour_rows.empty and int(hour_rows["focus_sessions"].sum()) > 0:
                hour_rows["minutes"] = hour_rows["focus_seconds"] / 60
                sns.barplot(data=hour_rows, x="hour", y="minutes", ax=hour_axis,
                            color=palette["gold"], errorbar=None)
                hour_axis.set_xticks(range(0, 24, 3), [f"{hour:02d}" for hour in range(0, 24, 3)])
                hour_axis.set_title("When sessions start · local hour", loc="left", fontsize=11,
                                    color=palette["ink"])
                hour_axis.set_ylabel("Minutes")
                hour_axis.set_xlabel("")
            else:
                hour_axis.text(.5, .5, "No sessions in this period.", ha="center", va="center",
                               transform=hour_axis.transAxes, fontsize=10, color=palette["muted"])
                hour_axis.set_axis_off()

            weekday_rows = pd.DataFrame(analytics.get("weekday_pattern", []))
            if not weekday_rows.empty and int(weekday_rows["focus_sessions"].sum()) > 0:
                weekday_rows["minutes"] = weekday_rows["focus_seconds"] / 60
                sns.barplot(data=weekday_rows, x="label", y="minutes", ax=weekday_axis,
                            color=palette["rating"], errorbar=None)
                weekday_axis.set_title("Weekday rhythm", loc="left", fontsize=11,
                                       color=palette["ink"])
                weekday_axis.set_ylabel("Minutes")
                weekday_axis.set_xlabel("")
            else:
                weekday_axis.text(.5, .5, "No sessions in this period.", ha="center", va="center",
                                  transform=weekday_axis.transAxes, fontsize=10, color=palette["muted"])
                weekday_axis.set_axis_off()

            for axis in [*trend_axes, *pattern_axes]:
                axis.grid(axis="y", alpha=.35)
                axis.grid(axis="x", visible=False)
                axis.spines[["top", "right", "left"]].set_visible(False)
                axis.spines["bottom"].set_color(palette["grid"])
                axis.tick_params(length=0)
        image = BytesIO()
        figure.savefig(image, format="png", dpi=150, bbox_inches="tight")
        plt.close(figure)
    return image.getvalue()
