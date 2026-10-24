"""App-name classifier and work-score calculator.

Maps foreground executable basenames to productivity categories
and computes a 0-100 focus score for a completed companion recording.

Privacy guarantee: only executable basenames are analysed -- never
window titles, file paths, URLs, or screen contents.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Per-session-type productive app lists
# ---------------------------------------------------------------------------
# Keys are executable basenames (lowercase, no path).
# "weight" is 1.0 for primary tools, 0.5 for supporting tools.
# Any app NOT in the productive list for the current session type is treated
# as a distraction with weight 0.0 for scoring purposes.

_PRODUCTIVE: dict[str, dict[str, dict[str, float]]] = {
    "coding": {
        "code.exe": {"weight": 1.0},
        "code - insiders.exe": {"weight": 1.0},
        "pycharm64.exe": {"weight": 1.0},
        "idea64.exe": {"weight": 1.0},
        "webstorm64.exe": {"weight": 1.0},
        "clion64.exe": {"weight": 1.0},
        "rider64.exe": {"weight": 1.0},
        "goland64.exe": {"weight": 1.0},
        "devenv.exe": {"weight": 1.0},
        "atom.exe": {"weight": 1.0},
        "sublime_text.exe": {"weight": 1.0},
        "notepad++.exe": {"weight": 1.0},
        "vim.exe": {"weight": 1.0},
        "nvim.exe": {"weight": 1.0},
        "gvim.exe": {"weight": 1.0},
        "emacs.exe": {"weight": 1.0},
        "windowsterminal.exe": {"weight": 0.9},
        "cmd.exe": {"weight": 0.9},
        "powershell.exe": {"weight": 0.9},
        "pwsh.exe": {"weight": 0.9},
        "bash.exe": {"weight": 0.9},
        "wsl.exe": {"weight": 0.9},
        "conhost.exe": {"weight": 0.9},
        "alacritty.exe": {"weight": 0.9},
        "wezterm.exe": {"weight": 0.9},
        "mintty.exe": {"weight": 0.9},
        "git.exe": {"weight": 0.8},
        "gitkraken.exe": {"weight": 0.8},
        "fork.exe": {"weight": 0.8},
        "sourcetreeapp.exe": {"weight": 0.8},
        "insomnia.exe": {"weight": 0.7},
        "postman.exe": {"weight": 0.7},
        "tableplus.exe": {"weight": 0.7},
        "dbeaver.exe": {"weight": 0.7},
        "dbeaverlauncher.exe": {"weight": 0.7},
        "chrome.exe": {"weight": 0.5},
        "firefox.exe": {"weight": 0.5},
        "msedge.exe": {"weight": 0.5},
        "brave.exe": {"weight": 0.5},
        "opera.exe": {"weight": 0.5},
    },
    "learning": {
        "chrome.exe": {"weight": 1.0},
        "firefox.exe": {"weight": 1.0},
        "msedge.exe": {"weight": 1.0},
        "brave.exe": {"weight": 1.0},
        "acrord32.exe": {"weight": 1.0},
        "acrobat.exe": {"weight": 1.0},
        "sumatrapdf.exe": {"weight": 1.0},
        "foxitpdfeditor.exe": {"weight": 1.0},
        "notion.exe": {"weight": 0.9},
        "obsidian.exe": {"weight": 0.9},
        "onenote.exe": {"weight": 0.9},
        "joplin.exe": {"weight": 0.9},
        "logseq.exe": {"weight": 0.9},
        "kindle.exe": {"weight": 0.9},
        "winword.exe": {"weight": 0.6},
        "powerpnt.exe": {"weight": 0.5},
        "vlc.exe": {"weight": 0.7},
        "mpc-hc64.exe": {"weight": 0.7},
        "mpv.exe": {"weight": 0.7},
        "code.exe": {"weight": 0.7},
        "pycharm64.exe": {"weight": 0.7},
    },
    "research": {
        "chrome.exe": {"weight": 1.0},
        "firefox.exe": {"weight": 1.0},
        "msedge.exe": {"weight": 1.0},
        "brave.exe": {"weight": 1.0},
        "opera.exe": {"weight": 1.0},
        "acrord32.exe": {"weight": 1.0},
        "acrobat.exe": {"weight": 1.0},
        "sumatrapdf.exe": {"weight": 1.0},
        "foxitpdfeditor.exe": {"weight": 1.0},
        "zotero.exe": {"weight": 1.0},
        "mendeley desktop.exe": {"weight": 1.0},
        "jabref.exe": {"weight": 1.0},
        "obsidian.exe": {"weight": 0.9},
        "notion.exe": {"weight": 0.9},
        "onenote.exe": {"weight": 0.9},
        "winword.exe": {"weight": 0.8},
        "excel.exe": {"weight": 0.7},
        "rstudio.exe": {"weight": 0.9},
        "spss.exe": {"weight": 0.8},
        "stata.exe": {"weight": 0.8},
        "code.exe": {"weight": 0.6},
    },
    "assignment": {
        "winword.exe": {"weight": 1.0},
        "libreoffice.exe": {"weight": 1.0},
        "soffice.exe": {"weight": 1.0},
        "wordpad.exe": {"weight": 0.8},
        "excel.exe": {"weight": 0.9},
        "powerpnt.exe": {"weight": 0.9},
        "acrord32.exe": {"weight": 0.9},
        "acrobat.exe": {"weight": 0.9},
        "sumatrapdf.exe": {"weight": 0.8},
        "chrome.exe": {"weight": 0.6},
        "firefox.exe": {"weight": 0.6},
        "msedge.exe": {"weight": 0.6},
        "brave.exe": {"weight": 0.6},
        "obsidian.exe": {"weight": 0.7},
        "notion.exe": {"weight": 0.7},
        "onenote.exe": {"weight": 0.7},
    },
    "creative": {
        "photoshop.exe": {"weight": 1.0},
        "illustrator.exe": {"weight": 1.0},
        "xd.exe": {"weight": 1.0},
        "figma.exe": {"weight": 1.0},
        "sketch.exe": {"weight": 1.0},
        "inkscape.exe": {"weight": 1.0},
        "gimp-2.10.exe": {"weight": 1.0},
        "krita.exe": {"weight": 1.0},
        "affdesigner.exe": {"weight": 1.0},
        "affinitydesigner.exe": {"weight": 1.0},
        "affphoto.exe": {"weight": 1.0},
        "premierepro.exe": {"weight": 1.0},
        "afterfx.exe": {"weight": 1.0},
        "resolve.exe": {"weight": 1.0},
        "davinciresolvepanel.exe": {"weight": 1.0},
        "kdenlive.exe": {"weight": 0.9},
        "shotcut.exe": {"weight": 0.9},
        "fl64.exe": {"weight": 1.0},
        "audacity.exe": {"weight": 0.9},
        "reaper64.exe": {"weight": 0.9},
        "blender.exe": {"weight": 1.0},
        "maya.exe": {"weight": 1.0},
        "3dsmax.exe": {"weight": 1.0},
        "scrivener.exe": {"weight": 0.9},
        "winword.exe": {"weight": 0.7},
        "code.exe": {"weight": 0.5},
    },
    "video": {
        "vlc.exe": {"weight": 1.0},
        "mpc-hc64.exe": {"weight": 1.0},
        "mpv.exe": {"weight": 1.0},
        "windowsmediaplayer.exe": {"weight": 0.8},
        "chrome.exe": {"weight": 0.8},
        "firefox.exe": {"weight": 0.8},
        "msedge.exe": {"weight": 0.8},
        "brave.exe": {"weight": 0.8},
    },
}

# Neutral apps -- system overhead excluded from score denominator
_NEUTRAL: set[str] = {
    "explorer.exe",
    "searchapp.exe",
    "searchhost.exe",
    "lockapp.exe",
    "logonui.exe",
    "dwm.exe",
    "desktop",
    "unavailable app",
    "unknown app",
    "systemsettings.exe",
    "settingssynchost.exe",
    "taskmgr.exe",
    "perfmon.exe",
}

# Always distracting regardless of session type
_ALWAYS_DISTRACTION: set[str] = {
    "discord.exe",
    "telegram.exe",
    "whatsapp.exe",
    "spotify.exe",
    "steam.exe",
    "epicgameslauncher.exe",
    "battle.net.exe",
    "origin.exe",
    "leagueclient.exe",
    "csgo.exe",
    "valorant.exe",
}


def classify_app(app_name: str, session_type: str) -> dict:
    """Classify a single foreground app for the given session type.

    Returns a dict with keys: app_name, category, weight.
    """
    key = app_name.lower().strip()
    if key in _NEUTRAL:
        return {"app_name": app_name, "category": "neutral", "weight": 0.0}
    if key in _ALWAYS_DISTRACTION:
        return {"app_name": app_name, "category": "distraction", "weight": 0.0}
    productive = _PRODUCTIVE.get(session_type, {})
    if key in productive:
        return {
            "app_name": app_name,
            "category": "productive",
            "weight": productive[key]["weight"],
        }
    return {"app_name": app_name, "category": "distraction", "weight": 0.0}


def work_score(app_intervals: list[dict], session_type: str) -> dict:
    """Compute a 0-100 work score from app_intervals for a companion recording.

    Each interval dict must have keys: app_name, elapsed_seconds.

    Returns a dict with score, breakdown, and second-level stats.
    """
    productive_weighted = 0.0
    productive_seconds = 0
    distraction_seconds = 0
    neutral_seconds = 0
    breakdown: list[dict] = []

    for interval in app_intervals:
        name = str(interval.get("app_name", ""))
        seconds = max(0, int(interval.get("elapsed_seconds", 0)))
        info = classify_app(name, session_type)
        breakdown.append({
            "app_name": name,
            "elapsed_seconds": seconds,
            "category": info["category"],
            "weight": info["weight"],
        })
        if info["category"] == "productive":
            productive_weighted += seconds * info["weight"]
            productive_seconds += seconds
        elif info["category"] == "neutral":
            neutral_seconds += seconds
        else:
            distraction_seconds += seconds

    scorable = productive_seconds + distraction_seconds
    score = int(round(productive_weighted / scorable * 100)) if scorable > 0 else 0
    score = max(0, min(100, score))

    breakdown.sort(key=lambda x: x["elapsed_seconds"], reverse=True)

    return {
        "score": score,
        "productive_seconds": productive_seconds,
        "distraction_seconds": distraction_seconds,
        "neutral_seconds": neutral_seconds,
        "total_seconds": productive_seconds + distraction_seconds + neutral_seconds,
        "app_breakdown": breakdown,
    }


def score_label(score: int) -> str:
    """Human-readable label for a 0-100 work score."""
    if score >= 90:
        return "Deep Work"
    if score >= 75:
        return "Focused"
    if score >= 55:
        return "Moderate"
    if score >= 35:
        return "Distracted"
    return "Off Task"


def score_coin_multiplier(score: int) -> float:
    """Return a 0.5-1.5x coin multiplier based on the work score.

    Applied on top of the base category coin rate when a companion
    recording is paired with a completed manual session.
    Note: this only affects the companion's local estimated display,
    not the verified account coin balance.
    """
    if score >= 90:
        return 1.5
    if score >= 75:
        return 1.25
    if score >= 55:
        return 1.0
    if score >= 35:
        return 0.75
    return 0.5
