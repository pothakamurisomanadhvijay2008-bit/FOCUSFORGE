"""Backend and dashboard integration regression tests."""

import json
import sqlite3
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path / "focusforge-test.sqlite3")


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        yield test_client


async def register(client, email="vijay@example.com", password="correct horse battery"):
    return await client.post("/api/auth/register", json={"email": email, "password": password})


async def start_coding(client):
    return await client.post("/api/sessions", json={
        "session_type": "coding",
        "title": "Coding session",
        "task_description": "Implement the login flow",
        "goal": "Add account protection",
        "duration_minutes": 25,
    })


@pytest.mark.asyncio
async def test_health_and_docs_remain_public(client):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    docs = await client.get("/docs")
    assert docs.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_requires_login_and_frontend_assets_load(client):
    root = await client.get("/", follow_redirects=False)
    assert root.status_code == 303
    assert root.headers["location"] == "/login"
    login = await client.get("/login")
    assert login.status_code == 200
    assert "Create an account" in login.text
    css = await client.get("/assets/style.css")
    auth_js = await client.get("/assets/auth.js")
    icon = await client.get("/assets/favicon.svg")
    browser_icon = await client.get("/favicon.ico")
    assert css.status_code == 200 and "text/css" in css.headers["content-type"]
    assert auth_js.status_code == 200 and "javascript" in auth_js.headers["content-type"]
    assert icon.status_code == 200 and "image/svg+xml" in icon.headers["content-type"]
    assert browser_icon.status_code == 200 and "image/svg+xml" in browser_icon.headers["content-type"]
    assert (await client.get("/index.html")).status_code == 404
    assert (await client.get("/assets/index.html")).status_code == 404
    assert (await client.get("/api/dashboard")).status_code == 401


@pytest.mark.asyncio
async def test_registration_hashes_password_and_sets_http_only_cookie(client):
    response = await register(client)
    assert response.status_code == 201
    assert response.json()["email"] == "vijay@example.com"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert (await client.get("/api/auth/me")).json()["email"] == "vijay@example.com"
    assert (await client.get("/", follow_redirects=False)).status_code == 200
    assert (await client.get("/login", follow_redirects=False)).status_code == 303

    row = sqlite3.connect(client._transport.app.state.db_path).execute(
        "SELECT password_hash FROM users"
    ).fetchone()
    assert row[0].startswith("scrypt$")
    assert "correct horse battery" not in row[0]


@pytest.mark.asyncio
async def test_auth_validation_and_generic_bad_credentials(client):
    invalid = await client.post("/api/auth/register", json={"email": "not-an-email", "password": "short"})
    assert invalid.status_code == 422
    assert (await register(client)).status_code == 201
    duplicate = await register(client)
    assert duplicate.status_code == 409
    bad_login = await client.post("/api/auth/login", json={
        "email": "vijay@example.com", "password": "wrong password value",
    })
    assert bad_login.status_code == 401
    assert bad_login.json()["detail"] == "Invalid email or password"

    logged_in = AsyncClient(transport=ASGITransport(app=client._transport.app), base_url="http://test")
    success = await logged_in.post("/api/auth/login", json={
        "email": "VIJAY@example.com", "password": "correct horse battery",
    })
    assert success.status_code == 200
    assert (await logged_in.get("/api/auth/me")).status_code == 200
    await logged_in.post("/api/auth/logout")
    assert (await logged_in.get("/api/auth/me")).status_code == 401
    await logged_in.aclose()


@pytest.mark.asyncio
async def test_session_lifecycle_is_idempotent_and_blocks_second_timer(client):
    assert (await register(client)).status_code == 201
    started = await start_coding(client)
    assert started.status_code == 201
    session = started.json()
    duplicate = await start_coding(client)
    assert duplicate.status_code == 409

    paused = await client.post(f"/api/sessions/{session['id']}/pause")
    assert paused.status_code == 200 and paused.json()["status"] == "paused"
    assert (await client.post(f"/api/sessions/{session['id']}/pause")).json()["status"] == "paused"
    resumed = await client.post(f"/api/sessions/{session['id']}/resume")
    assert resumed.status_code == 200 and resumed.json()["status"] == "running"
    assert (await client.post(f"/api/sessions/{session['id']}/resume")).json()["status"] == "running"
    completed = await client.post(f"/api/sessions/{session['id']}/stop", json={"completion_note": "Login flow added"})
    repeated = await client.post(f"/api/sessions/{session['id']}/stop", json={"completion_note": "duplicate click"})
    assert completed.json()["status"] == repeated.json()["status"] == "completed"
    records = await client.get("/api/sessions")
    assert len(records.json()) == 1
    assert records.json()[0]["id"] == session["id"]
    assert records.json()[0]["completion_note"] == "Login flow added"


@pytest.mark.asyncio
async def test_every_persisted_session_category_uses_backend_contract(client):
    await register(client)
    for category in ("coding", "learning", "research", "assignment", "creative", "video", "break"):
        response = await client.post("/api/sessions", json={
            "session_type": category,
            "title": f"{category.title()} session",
            "task_description": f"Work on {category}",
            "goal": "Complete one step",
            "duration_minutes": 25,
        })
        assert response.status_code == 201, response.text
        session = response.json()
        assert session["type"] == category
        assert session["task_description"] == f"Work on {category}"
        assert (await client.post(f"/api/sessions/{session['id']}/stop")).status_code == 200


@pytest.mark.asyncio
async def test_private_session_is_rejected_and_never_persisted(client):
    await register(client)
    response = await client.post("/api/sessions", json={
        "session_type": "private", "title": "Private", "task_description": "sensitive details",
    })
    assert response.status_code == 400
    with sqlite3.connect(client._transport.app.state.db_path) as db:
        count = db.execute("SELECT COUNT(*) FROM work_sessions").fetchone()[0]
    assert count == 0


@pytest.mark.asyncio
async def test_user_data_isolation_and_empty_dashboard(client):
    await register(client)
    summary = await client.get("/api/dashboard?local_date=2026-10-23&offset_minutes=-330")
    body = summary.json()
    assert body["completed_sessions"] == 0
    assert body["productive_seconds"] == 0
    assert body["coin_balance"] == 0
    assert body["coin_rates_per_15_minutes"] == {
        "coding": 15, "assignment": 15, "creative": 12,
        "research": 10, "learning": 10, "video": 3,
    }
    assert body["goal"] == {
        "daily_goal_minutes": 0, "today_focus_seconds": 0, "percent": None, "met": False,
    }
    assert body["streak"] == {"current": 0, "longest": 0, "active_today": False}
    assert body["totals"] == {
        "completed_sessions": 0, "focus_seconds": 0, "distractions": 0, "coins": 0,
    }
    started = await start_coding(client)
    session_id = started.json()["id"]
    token = client.cookies.get("focusforge_session")

    other = AsyncClient(transport=ASGITransport(app=client._transport.app), base_url="http://test")
    await register(other, "other@example.com")
    assert other.cookies.get("focusforge_session") != token
    assert (await other.post(f"/api/sessions/{session_id}/pause")).status_code == 404
    assert (await other.get("/api/sessions")).json() == []
    await other.aclose()


@pytest.mark.asyncio
async def test_coin_balance_and_excel_export_are_account_scoped(client):
    assert (await client.get("/api/sessions/export.xlsx")).status_code == 401
    await register(client)
    started = await client.post("/api/sessions", json={
        "session_type": "assignment", "title": "Writing assignment",
        "task_description": "Write the report", "duration_minutes": 25,
    })
    assert started.status_code == 201
    await client.post(f"/api/sessions/{started.json()['id']}/stop")
    with sqlite3.connect(client._transport.app.state.db_path) as db:
        db.execute(
            "UPDATE work_sessions SET elapsed_seconds=900, reward_coins=15 WHERE id=?",
            (started.json()["id"],),
        )
    summary = await client.get("/api/dashboard?local_date=2026-10-23&offset_minutes=-330")
    assert summary.json()["coin_balance"] == 15
    export = await client.get("/api/sessions/export.xlsx")
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with ZipFile(BytesIO(export.content)) as workbook:
        assert workbook.testzip() is None
        owner_sheet = workbook.read("xl/worksheets/sheet1.xml")
        assert b"Write the report" in owner_sheet

    other = AsyncClient(transport=ASGITransport(app=client._transport.app), base_url="http://test")
    await register(other, "other@example.com")
    other_export = await other.get("/api/sessions/export.xlsx")
    with ZipFile(BytesIO(other_export.content)) as workbook:
        other_sheet = workbook.read("xl/worksheets/sheet1.xml")
    assert b"Write the report" not in other_sheet
    await other.aclose()


@pytest.mark.asyncio
async def test_restart_marks_timer_interrupted_at_last_checkpoint(app, client, tmp_path):
    await register(client)
    started = (await start_coding(client)).json()
    session_id = started["id"]
    app.state.active_since[session_id] = time.monotonic() - 22
    checkpoint = await client.post(f"/api/sessions/{session_id}/checkpoint")
    assert checkpoint.json()["elapsed_seconds"] >= 21
    checkpointed_seconds = checkpoint.json()["elapsed_seconds"]

    restarted_app = create_app(tmp_path / "focusforge-test.sqlite3")
    restarted_client = AsyncClient(transport=ASGITransport(app=restarted_app), base_url="http://test")
    restarted_client.cookies.set("focusforge_session", client.cookies.get("focusforge_session"))
    resumed_state = await restarted_client.get("/api/sessions/active")
    assert resumed_state.json()["status"] == "interrupted"
    assert resumed_state.json()["elapsed_seconds"] == checkpointed_seconds
    assert (await restarted_client.post(f"/api/sessions/{session_id}/stop")).json()["status"] == "abandoned"
    await restarted_client.aclose()


@pytest.mark.asyncio
async def test_dashboard_counts_only_completed_work_and_excludes_breaks(client):
    await register(client)
    work = (await start_coding(client)).json()
    await client.post(f"/api/sessions/{work['id']}/stop")
    break_session = await client.post("/api/sessions", json={
        "session_type": "break", "title": "Break", "duration_minutes": 25,
    })
    assert break_session.status_code == 201
    await client.post(f"/api/sessions/{break_session.json()['id']}/stop")
    learning = await client.post("/api/sessions", json={
        "session_type": "learning", "title": "Learning", "duration_minutes": 25,
    })
    assert learning.status_code == 201
    await client.post(f"/api/sessions/{learning.json()['id']}/stop")
    with sqlite3.connect(client._transport.app.state.db_path) as db:
        db.execute("UPDATE work_sessions SET ended_at='2026-10-22T20:00:00+00:00', elapsed_seconds=120 WHERE session_type='coding'")
        db.execute("UPDATE work_sessions SET ended_at='2026-10-23T10:00:00+00:00', elapsed_seconds=300 WHERE session_type='break'")
        db.execute("UPDATE work_sessions SET ended_at='2026-10-23T19:00:00+00:00', elapsed_seconds=600 WHERE session_type='learning'")
    summary = await client.get("/api/dashboard?local_date=2026-10-23&offset_minutes=-330")
    assert summary.json()["completed_sessions"] == 1
    assert summary.json()["productive_seconds"] == 120


@pytest.mark.asyncio
async def test_frontend_uses_real_session_rewards_without_fabricated_stats(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/assets/app.js")
    source = response.text
    assert "SAMPLE_STATS" not in source
    assert "Math.random" not in source
    assert "3h 42m" not in source
    assert "No assessments" not in source
    assert "localStorage" not in source
    assert "focusforge_companion_code" in source
    private_branch = source[source.index("if (type === 'private')"):source.index("} else {", source.index("if (type === 'private')"))]
    assert "sessionStorage" not in private_branch
    assert "session_type: type" in source
    assert "coinBalance" in source
    assert "coinRatesPer15Minutes" in source
    assert "reward_coins" in source
    assert "Array.isArray(detail)" in source
    assert "new Error(apiErrorMessage(data, response.status))" in source
    assert "data.detail ||" not in source
    assert "[object Object]" not in source
    assert "sessionFloater" in source and "floaterOpenBtn" in source
    assert "getDisplayMedia" in source and "new MediaRecorder" in source
    consent_check = source.index("if (!$('#recordingConsent').checked)")
    permission_request = source.index("navigator.mediaDevices.getDisplayMedia")
    assert consent_check < permission_request
    assert "if (!currentSession || currentSession.type === 'private')" in source
    dashboard = Path(__file__).parent.parent / "frontend" / "index.html"
    markup = dashboard.read_text(encoding="utf-8")
    for element_id in (
        "sessionFloater", "floaterType", "floaterTime", "floaterState",
        "floaterPauseBtn", "floaterResumeBtn", "floaterStopBtn", "floaterOpenBtn",
        "recordingConsent", "recordingStartBtn", "recordingStopBtn",
        "recordingDownloadBtn", "recordingDiscardBtn", "recordingAppActivityConsent",
        "recordingReportDownloadBtn", "recordingBundleSaveBtn", "recordingReportDeleteBtn",
        "coinBalance", "coinBalanceCard", "activityReportsRefreshBtn", "activityReportList",
        "activityReportsEmpty", "activityReportStatus",
    ):
        assert f'id="{element_id}"' in markup
    assert "A browser process may show many unrelated pages; FocusForge does not inspect them." in (
        Path(__file__).parent.parent / "docs" / "desktop-companion.md"
    ).read_text(encoding="utf-8")


RECORDING_ID = "f5a0f95a-b67e-4be2-9201-5a06f3d1a954"


@pytest.mark.asyncio
async def test_app_activity_proxy_lists_reports_and_returns_per_app_time(client, monkeypatch):
    seen = []

    class StubCompanion(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def _reply(self, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            seen.append((self.path, self.headers.get("Authorization")))
            if self.path == "/api/recordings":
                self._reply({"recordings": [{
                    "id": RECORDING_ID,
                    "session_type": "coding",
                    "status": "completed",
                    "started_at": "2026-10-24T09:00:00+05:30",
                    "ended_at": "2026-10-24T09:05:00+05:30",
                    "foreground_seconds": 300,
                }]})
                return
            if self.path == f"/api/recordings/{RECORDING_ID}/intervals":
                self._reply({
                    "recording_id": RECORDING_ID,
                    "session_type": "coding",
                    "status": "completed",
                    "intervals": [
                        {"app_name": "chrome.exe", "elapsed_seconds": 60},
                        {"app_name": "code.exe", "elapsed_seconds": 240},
                    ],
                })
                return
            self.send_response(404)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), StubCompanion)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        from backend.app.routers import activity

        monkeypatch.setattr(activity, "COMPANION_BASE", f"http://127.0.0.1:{server.server_address[1]}")
        assert (await client.get("/api/activity/reports?companion_token=pair-code")).status_code == 401
        await register(client)

        listed = await client.get("/api/activity/reports?companion_token=pair-code")
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()["recordings"]] == [RECORDING_ID]

        detail = await client.get(
            f"/api/activity/reports/{RECORDING_ID}?companion_token=pair-code&session_type=coding"
        )
        assert detail.status_code == 200
        report = detail.json()
        assert report["status"] == "completed"
        assert report["total_seconds"] == 300 and report["total_minutes"] == 5.0
        assert [app["app_name"] for app in report["apps"]] == ["code.exe", "chrome.exe"]
        code_app, chrome_app = report["apps"]
        assert code_app["elapsed_seconds"] == 240
        assert code_app["minutes"] == 4.0
        assert code_app["percent"] == 80.0
        assert code_app["category"] == "productive" and code_app["weight"] == 1.0
        assert chrome_app["elapsed_seconds"] == 60
        assert chrome_app["percent"] == 20.0
        assert chrome_app["category"] == "productive" and chrome_app["weight"] == 0.5
        assert report["score"] == 90
        assert report["label"] == "Deep Work"
        assert report["coin_multiplier"] == 1.5
        assert seen and all(auth == "Bearer pair-code" for _, auth in seen)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.asyncio
async def test_dashboard_navigation_targets_exist(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = await client.get("/login")
    # Read the dashboard shell directly from its source in this test, while the route remains protected.
    dashboard = Path(__file__).parent.parent / "frontend" / "index.html"
    source = dashboard.read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', source))
    anchors = re.findall(r'href="#([^"]+)"', source)
    assert anchors
    assert all(target in ids for target in anchors)
    assert page.status_code == 200
