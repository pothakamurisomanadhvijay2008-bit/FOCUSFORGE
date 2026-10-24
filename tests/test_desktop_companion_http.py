"""HTTP-level coverage for the local companion connection and recording flow."""

from __future__ import annotations

import http.client
import json
import threading
import uuid
from pathlib import Path

from desktop_companion.tracker import ActivityTracker, CompanionHTTPServer


def _request(
    server: CompanionHTTPServer,
    method: str,
    path: str,
    *,
    origin: str = "http://127.0.0.1:8001",
    token: str = "test-pairing-code",
    body: dict | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, http.client.HTTPMessage, bytes]:
    connection = http.client.HTTPConnection(*server.server_address, timeout=3)
    headers = {"Origin": origin}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
    headers.update(extra_headers or {})
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    try:
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        return response.status, response.headers, response.read()
    finally:
        connection.close()


def test_dashboard_on_8001_can_pair_start_stop_and_export(tmp_path: Path):
    tracker = ActivityTracker(tmp_path / "activity.sqlite3", app_reader=lambda: "editor.exe")
    server = CompanionHTTPServer(("127.0.0.1", 0), tracker, "test-pairing-code")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, headers, _ = _request(
            server,
            "OPTIONS",
            "/api/status",
            token="",
            extra_headers={
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
                "Access-Control-Request-Private-Network": "true",
            },
        )
        assert status == 204
        assert headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:8001"
        assert "GET" in headers["Access-Control-Allow-Methods"]
        assert "Authorization" in headers["Access-Control-Allow-Headers"]
        assert headers["Access-Control-Allow-Private-Network"] == "true"

        status, headers, payload = _request(server, "GET", "/api/status")
        assert status == 200
        assert headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:8001"
        assert json.loads(payload) == {"ready": True, "tracking": False}

        recording_id = str(uuid.uuid4())
        status, _, payload = _request(
            server,
            "POST",
            "/api/recordings/start",
            body={"recording_id": recording_id, "session_type": "coding"},
        )
        assert status == 201
        assert json.loads(payload)["status"] == "recording"

        status, _, payload = _request(
            server,
            "POST",
            f"/api/recordings/{recording_id}/heartbeat",
        )
        assert status == 200
        assert json.loads(payload)["status"] == "recording"

        status, _, payload = _request(
            server,
            "POST",
            f"/api/recordings/{recording_id}/stop",
        )
        assert status == 200
        assert json.loads(payload)["status"] == "completed"

        status, headers, payload = _request(
            server,
            "GET",
            f"/api/recordings/{recording_id}/export.xlsx",
        )
        assert status == 200
        assert headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:8001"
        assert headers["Content-Type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert payload.startswith(b"PK")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_companion_preflight_rejects_unlisted_dashboard_origin(tmp_path: Path):
    tracker = ActivityTracker(tmp_path / "activity.sqlite3", app_reader=lambda: "editor.exe")
    server = CompanionHTTPServer(("127.0.0.1", 0), tracker, "test-pairing-code")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, headers, _ = _request(
            server,
            "OPTIONS",
            "/api/status",
            origin="http://127.0.0.1:8002",
            token="",
            extra_headers={"Access-Control-Request-Method": "GET"},
        )
        assert status == 403
        assert headers.get("Access-Control-Allow-Origin") is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
