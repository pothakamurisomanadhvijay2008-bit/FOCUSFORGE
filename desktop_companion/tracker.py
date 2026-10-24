"""Opt-in foreground-app intervals and localhost companion API.

Only executable basenames and foreground timestamps are collected. Window titles,
screenshots, keystrokes, file paths, and browser URLs are never read or stored.
"""

from __future__ import annotations

import ctypes
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlsplit

from backend.app.spreadsheet import app_activity_workbook

SESSION_TYPES = {"coding", "learning", "research", "assignment", "creative", "video", "break"}
ALLOWED_ORIGINS = {
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:8001",
    "http://localhost:8001",
}
HEARTBEAT_TIMEOUT_SECONDS = 90
MAX_REQUEST_BYTES = 4096
COMPANION_PORT = 8765


def local_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def foreground_application() -> str:
    """Return only the foreground process executable basename on Windows."""
    if os.name != "nt":
        raise OSError("Foreground app tracking is available only on Windows.")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_wchar), ctypes.POINTER(ctypes.c_ulong),
    ]
    kernel32.QueryFullProcessImageNameW.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "Desktop"

    process_id = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(process_id))
    if not process_id.value:
        return "Unavailable app"

    # PROCESS_QUERY_LIMITED_INFORMATION is sufficient to read the executable path.
    process = kernel32.OpenProcess(0x1000, False, process_id.value)
    if not process:
        return "Unavailable app"
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.c_ulong(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(length)):
            return "Unavailable app"
        return Path(buffer.value[:length.value]).name or "Unavailable app"
    finally:
        kernel32.CloseHandle(process)


class ActivityTracker:
    """Thread-safe local recording store; tracking starts only through the paired API."""

    def __init__(
        self,
        database_path: Path,
        *,
        app_reader: Callable[[], str] = foreground_application,
        wall_clock: Callable[[], str] = local_timestamp,
        monotonic: Callable[[], float] = time.monotonic,
        heartbeat_timeout: int = HEARTBEAT_TIMEOUT_SECONDS,
    ) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.app_reader = app_reader
        self.wall_clock = wall_clock
        self.monotonic = monotonic
        self.heartbeat_timeout = heartbeat_timeout
        self.lock = threading.RLock()
        self._active: dict[str, dict] = {}
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize_database(self) -> None:
        now = self.wall_clock()
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS recordings (
                    id TEXT PRIMARY KEY,
                    session_type TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('recording','completed','interrupted')),
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    foreground_seconds INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS app_intervals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
                    app_name TEXT NOT NULL,
                    foreground_started_at TEXT NOT NULL,
                    foreground_ended_at TEXT,
                    elapsed_seconds INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS app_intervals_recording
                    ON app_intervals(recording_id, id);
            """)
            # A companion restart never resumes collection. Close stale records explicitly.
            db.execute(
                "UPDATE app_intervals SET foreground_ended_at=? "
                "WHERE foreground_ended_at IS NULL AND recording_id IN "
                "(SELECT id FROM recordings WHERE status='recording')",
                (now,),
            )
            db.execute(
                "UPDATE recordings SET status='interrupted', ended_at=? WHERE status='recording'",
                (now,),
            )
            db.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_recording
                ON recordings(status) WHERE status='recording'
            """)

    def _read_app(self) -> str:
        try:
            value = str(self.app_reader()).strip()
        except Exception:
            value = "Unavailable app"
        # Retain only a short executable-like basename even for an injected reader.
        return Path(value.replace("\\", "/")).name[:120] or "Unknown app"

    def start(self, recording_id: str, session_type: str) -> dict:
        if session_type not in SESSION_TYPES:
            if session_type == "private":
                raise ValueError("Desktop app tracking is disabled for Private Mode.")
            raise ValueError("Choose a supported FocusForge session category first.")
        app_name = self._read_app()
        now = self.wall_clock()
        tick = self.monotonic()
        with self.lock, self._connect() as db:
            active = db.execute("SELECT id FROM recordings WHERE status='recording'").fetchone()
            if active:
                raise RuntimeError("A companion recording is already active.")
            try:
                db.execute(
                    "INSERT INTO recordings(id,session_type,status,started_at) VALUES(?,?,'recording',?)",
                    (recording_id, session_type, now),
                )
            except sqlite3.IntegrityError as error:
                raise RuntimeError("This recording already has an app activity report.") from error
            cursor = db.execute(
                "INSERT INTO app_intervals(recording_id,app_name,foreground_started_at) VALUES(?,?,?)",
                (recording_id, app_name, now),
            )
            self._active[recording_id] = {
                "app_name": app_name,
                "interval_id": cursor.lastrowid,
                "last_sample": tick,
                "fractional_elapsed": 0.0,
                "last_heartbeat": tick,
            }
        return {"recording_id": recording_id, "status": "recording", "current_app": app_name}

    def heartbeat(self, recording_id: str) -> dict:
        with self.lock:
            state = self._active.get(recording_id)
            if not state:
                raise KeyError("The companion is not tracking this recording.")
            state["last_heartbeat"] = self.monotonic()
            return {"recording_id": recording_id, "status": "recording"}

    def _finish_locked(self, db: sqlite3.Connection, recording_id: str, status: str) -> dict:
        state = self._active.pop(recording_id, None)
        if not state:
            row = db.execute("SELECT * FROM recordings WHERE id=?", (recording_id,)).fetchone()
            if row and row["status"] != "recording":
                return dict(row)
            raise KeyError("Recording not found or already stopped.")
        end_tick = self.monotonic()
        sample_delta = max(0.0, min(2.0, end_tick - state["last_sample"]))
        elapsed = max(0, min(2, int(sample_delta + state["fractional_elapsed"] + 0.5)))
        ended = self.wall_clock()
        db.execute(
            "UPDATE app_intervals SET foreground_ended_at=?, elapsed_seconds=elapsed_seconds+? WHERE id=?",
            (ended, elapsed, state["interval_id"]),
        )
        db.execute(
            "UPDATE recordings SET status=?, ended_at=?, foreground_seconds="
            "(SELECT COALESCE(SUM(elapsed_seconds),0) FROM app_intervals WHERE recording_id=?) WHERE id=?",
            (status, ended, recording_id, recording_id),
        )
        row = db.execute("SELECT * FROM recordings WHERE id=?", (recording_id,)).fetchone()
        return dict(row)

    def stop(self, recording_id: str) -> dict:
        with self.lock, self._connect() as db:
            return self._finish_locked(db, recording_id, "completed")

    def stop_active(self) -> dict | None:
        with self.lock, self._connect() as db:
            recording_id = next(iter(self._active), None)
            return self._finish_locked(db, recording_id, "interrupted") if recording_id else None

    def poll(self) -> None:
        with self.lock:
            if not self._active:
                return
            app_name = self._read_app()
            tick = self.monotonic()
            now = self.wall_clock()
            with self._connect() as db:
                for recording_id, state in list(self._active.items()):
                    if tick - state["last_heartbeat"] > self.heartbeat_timeout:
                        self._finish_locked(db, recording_id, "interrupted")
                        continue
                    sample_delta = max(0.0, min(2.0, tick - state["last_sample"]))
                    if state["app_name"] != app_name:
                        # Attribute time since the previous sample to the app that
                        # was foreground during that interval, keeping its fraction.
                        delta = max(0, int(sample_delta + state["fractional_elapsed"] + 0.5))
                        state["fractional_elapsed"] = 0.0
                        db.execute(
                            "UPDATE app_intervals SET foreground_ended_at=?, elapsed_seconds=elapsed_seconds+? WHERE id=?",
                            (now, delta, state["interval_id"]),
                        )
                        cursor = db.execute(
                            "INSERT INTO app_intervals(recording_id,app_name,foreground_started_at) VALUES(?,?,?)",
                            (recording_id, app_name, now),
                        )
                        state["app_name"] = app_name
                        state["interval_id"] = cursor.lastrowid
                    else:
                        accumulated = sample_delta + state["fractional_elapsed"]
                        delta = int(accumulated + 1e-9)
                        state["fractional_elapsed"] = accumulated - delta
                        if delta:
                            db.execute(
                                "UPDATE app_intervals SET foreground_ended_at=?, elapsed_seconds=elapsed_seconds+? WHERE id=?",
                                (now, delta, state["interval_id"]),
                            )
                    if delta:
                        db.execute(
                            "UPDATE recordings SET foreground_seconds=foreground_seconds+? WHERE id=?",
                            (delta, recording_id),
                        )
                    state["last_sample"] = tick

    def status(self) -> dict:
        with self.lock, self._connect() as db:
            recording_id = next(iter(self._active), None)
            if not recording_id:
                return {"ready": True, "tracking": False}
            state = self._active[recording_id]
            row = db.execute("SELECT session_type,started_at,foreground_seconds FROM recordings WHERE id=?", (recording_id,)).fetchone()
            return {
                "ready": True,
                "tracking": True,
                "recording_id": recording_id,
                "session_type": row["session_type"],
                "started_at": row["started_at"],
                "foreground_seconds": row["foreground_seconds"],
                "current_app": state["app_name"],
            }

    def workbook(self, recording_id: str) -> bytes:
        with self.lock, self._connect() as db:
            recording = db.execute("SELECT * FROM recordings WHERE id=?", (recording_id,)).fetchone()
            if not recording:
                raise KeyError("App activity report not found.")
            if recording["status"] == "recording":
                raise RuntimeError("Stop the screen recording before downloading its app report.")
            events = db.execute(
                "SELECT app_name,foreground_started_at,foreground_ended_at,elapsed_seconds "
                "FROM app_intervals WHERE recording_id=? ORDER BY id",
                (recording_id,),
            ).fetchall()
        return app_activity_workbook(dict(recording), [dict(event) for event in events])

    def intervals(self, recording_id: str) -> dict:
        """Return aggregated app intervals for a *completed* recording.

        Used by the backend work-score endpoint and by the history view.
        Intervals are grouped by app_name and their elapsed_seconds summed.
        """
        with self.lock, self._connect() as db:
            recording = db.execute("SELECT * FROM recordings WHERE id=?", (recording_id,)).fetchone()
            if not recording:
                raise KeyError("App activity report not found.")
            if recording["status"] == "recording":
                raise RuntimeError("Stop the recording before fetching its interval report.")
            rows = db.execute(
                "SELECT app_name, SUM(elapsed_seconds) AS elapsed_seconds "
                "FROM app_intervals WHERE recording_id=? GROUP BY app_name ORDER BY elapsed_seconds DESC",
                (recording_id,),
            ).fetchall()
        return {
            "recording_id": recording_id,
            "session_type": recording["session_type"],
            "status": recording["status"],
            "intervals": [{"app_name": r["app_name"], "elapsed_seconds": r["elapsed_seconds"]} for r in rows],
        }

    def intervals_live(self, recording_id: str) -> dict:
        """Return aggregated app intervals for an *active* recording (live polling).

        Used by the dashboard timeline chart, polled every 5 seconds.
        Includes the current foreground app with its in-progress elapsed estimate.
        """
        with self.lock:
            state = self._active.get(recording_id)
        with self._connect() as db:
            recording = db.execute("SELECT * FROM recordings WHERE id=?", (recording_id,)).fetchone()
            if not recording:
                raise KeyError("Recording not found.")
            rows = db.execute(
                "SELECT app_name, SUM(elapsed_seconds) AS elapsed_seconds "
                "FROM app_intervals WHERE recording_id=? GROUP BY app_name ORDER BY elapsed_seconds DESC",
                (recording_id,),
            ).fetchall()
        aggregated = {r["app_name"]: r["elapsed_seconds"] for r in rows}
        # Add live fractional seconds for the currently active interval
        if state:
            live_app = state["app_name"]
            live_delta = max(0, int(self.monotonic() - state["last_sample"] + state["fractional_elapsed"]))
            aggregated[live_app] = aggregated.get(live_app, 0) + live_delta
        intervals = sorted(
            [{"app_name": app, "elapsed_seconds": secs} for app, secs in aggregated.items()],
            key=lambda x: x["elapsed_seconds"],
            reverse=True,
        )
        return {
            "recording_id": recording_id,
            "session_type": recording["session_type"],
            "status": recording["status"],
            "current_app": state["app_name"] if state else None,
            "intervals": intervals,
        }

    def delete(self, recording_id: str) -> None:
        with self.lock, self._connect() as db:
            if recording_id in self._active:
                raise RuntimeError("Stop app tracking before deleting this report.")
            cursor = db.execute("DELETE FROM recordings WHERE id=?", (recording_id,))
            if not cursor.rowcount:
                raise KeyError("App activity report not found.")

    def recent_recordings(self, limit: int = 8) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id,session_type,status,started_at,ended_at,foreground_seconds "
                "FROM recordings ORDER BY started_at DESC LIMIT ?", (limit,),
            ).fetchall()
        return [dict(row) for row in rows]


class CompanionHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], tracker: ActivityTracker, pairing_token: str):
        self.tracker = tracker
        self.pairing_token = pairing_token
        super().__init__(address, CompanionRequestHandler)


class CompanionRequestHandler(BaseHTTPRequestHandler):
    server: CompanionHTTPServer

    def log_message(self, _format: str, *_args) -> None:
        # Never write request headers or tokens to logs.
        return

    def _cors_origin(self) -> str | None:
        origin = self.headers.get("Origin")
        return origin if origin in ALLOWED_ORIGINS else None

    def _send(self, status: int, data: bytes, content_type: str, filename: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status: int, value: dict) -> None:
        self._send(status, json.dumps(value).encode("utf-8"), "application/json; charset=utf-8")

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.pairing_token}"
        return secrets.compare_digest(supplied, expected)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("Request body is empty or too large.")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("Request body must be an object.")
        return value

    def do_OPTIONS(self) -> None:
        origin = self._cors_origin()
        if not origin:
            self._json(403, {"detail": "This website origin is not allowed to pair with the companion."})
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        if self.headers.get("Access-Control-Request-Private-Network", "").lower() == "true":
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "300")
        self.send_header("Vary", "Origin")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle(self, method: str) -> None:
        origin = self.headers.get("Origin")
        if origin and not self._cors_origin():
            self._json(403, {"detail": "This website origin is not allowed to pair with the companion."})
            return
        path = urlsplit(self.path).path
        segments = [unquote(part) for part in path.strip("/").split("/") if part]
        if method == "POST" and len(segments) == 4 and segments[:2] == ["api", "recordings"] and segments[3] == "stop-beacon":
            try:
                body = self._body()
                supplied = str(body.get("pairing_code", ""))
                if not secrets.compare_digest(supplied, self.server.pairing_token):
                    self._json(401, {"detail": "Companion pairing code is invalid."})
                    return
                result = self.server.tracker.stop(segments[2])
                self._json(200, result)
            except KeyError as error:
                self._json(404, {"detail": str(error)})
            except (ValueError, json.JSONDecodeError) as error:
                self._json(400, {"detail": str(error)})
            return
        if not self._authorized():
            self._json(401, {"detail": "Pair this dashboard with the code shown in the Windows companion."})
            return

        try:
            if method == "GET" and segments == ["api", "status"]:
                self._json(200, self.server.tracker.status())
                return
            if method == "GET" and segments == ["api", "recordings"]:
                self._json(200, {"recordings": self.server.tracker.recent_recordings(limit=25)})
                return
            if method == "POST" and segments == ["api", "recordings", "start"]:
                body = self._body()
                recording_id = str(body.get("recording_id", ""))
                try:
                    if str(uuid.UUID(recording_id)) != recording_id.lower():
                        raise ValueError
                except (ValueError, AttributeError):
                    raise ValueError("Recording ID is invalid.")
                result = self.server.tracker.start(recording_id, str(body.get("session_type", "")))
                self._json(201, result)
                return
            if len(segments) == 4 and segments[:2] == ["api", "recordings"]:
                recording_id, action = segments[2], segments[3]
                if method == "POST" and action == "heartbeat":
                    self._json(200, self.server.tracker.heartbeat(recording_id))
                    return
                if method == "POST" and action == "stop":
                    self._json(200, self.server.tracker.stop(recording_id))
                    return
                if method == "GET" and action == "export.xlsx":
                    payload = self.server.tracker.workbook(recording_id)
                    self._send(
                        200, payload,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        f"focusforge-{recording_id}-app-activity.xlsx",
                    )
                    return
                if method == "GET" and action == "intervals":
                    self._json(200, self.server.tracker.intervals(recording_id))
                    return
                if method == "GET" and action == "intervals-live":
                    self._json(200, self.server.tracker.intervals_live(recording_id))
                    return
                if method == "DELETE" and action == "delete":
                    self.server.tracker.delete(recording_id)
                    self._json(200, {"deleted": True})
                    return
            self._json(404, {"detail": "Companion endpoint not found."})
        except KeyError as error:
            self._json(404, {"detail": str(error)})
        except RuntimeError as error:
            self._json(409, {"detail": str(error)})
        except (ValueError, json.JSONDecodeError) as error:
            self._json(400, {"detail": str(error)})

    def do_GET(self) -> None:
        if urlsplit(self.path).path == "/health":
            self._json(200, {"status": "ok", "service": "FocusForge Windows Companion"})
            return
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_DELETE(self) -> None:
        self._handle("DELETE")


def companion_data_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return base / "FocusForgeAI" / "app-activity.sqlite3"


def new_pairing_token() -> str:
    return secrets.token_urlsafe(32)
