import http.client
import json
import threading
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

from desktop_companion.tracker import COMPANION_PORT, ActivityTracker, CompanionHTTPServer


class FakeClock:
    def __init__(self):
        self.seconds = 100.0

    def monotonic(self):
        return self.seconds

    def wall(self):
        instant = datetime.fromtimestamp(1_800_000_000 + self.seconds, timezone.utc)
        return instant.astimezone().isoformat(timespec="seconds")


def test_app_intervals_pair_with_recording_and_export_a_multisheet_workbook(tmp_path: Path):
    clock = FakeClock()
    foreground = {"name": "code.exe"}
    reads = []

    def read_app():
        reads.append(foreground["name"])
        return foreground["name"]

    tracker = ActivityTracker(
        tmp_path / "activity.sqlite3",
        app_reader=read_app,
        wall_clock=clock.wall,
        monotonic=clock.monotonic,
    )
    tracker.poll()
    assert reads == []  # No active recording means no foreground-app sampling.

    recording_id = "f5a0f95a-b67e-4be2-9201-5a06f3d1a954"
    tracker.start(recording_id, "coding")
    clock.seconds = 101
    tracker.poll()
    foreground["name"] = r"C:\Program Files\Browser\browser.exe"
    clock.seconds = 102
    tracker.poll()
    tracker.heartbeat(recording_id)
    clock.seconds = 104
    tracker.poll()
    clock.seconds = 105
    result = tracker.stop(recording_id)

    assert result["status"] == "completed"
    assert tracker.status() == {"ready": True, "tracking": False}
    content = tracker.workbook(recording_id)
    with ZipFile(BytesIO(content)) as workbook:
        assert workbook.testzip() is None
        book_xml = ET.fromstring(workbook.read("xl/workbook.xml"))
        workbook_namespace = {"workbook": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        names = [sheet.attrib["name"] for sheet in book_xml.findall(".//workbook:sheet", workbook_namespace)]
        assert names == ["Recording", "App timeline", "App summary"]
        namespace = {"sheet": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        timeline = ET.fromstring(workbook.read("xl/worksheets/sheet2.xml"))
        values = [node.text for node in timeline.findall(".//sheet:t", namespace)]
        assert "code.exe" in values
        assert "browser.exe" in values
        assert "coding" in values
        assert "Foreground began at (local)" in values
        summary = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        summary_values = [node.text for node in summary.findall(".//sheet:t", namespace)]
        assert recording_id in summary_values
        assert any("does not verify work" in value for value in summary_values)

        def row_values(sheet, row_number):
            row = sheet.find(f".//sheet:row[@r='{row_number}']", namespace)
            parsed = {}
            for cell in row.findall("sheet:c", namespace):
                column = cell.attrib["r"].rstrip("0123456789")
                number = cell.find("sheet:v", namespace)
                text = cell.find(".//sheet:t", namespace)
                parsed[column] = number.text if number is not None else text.text
            return parsed

        # Timeline rows have local timestamps, duration, classification, and reward per app.
        # Columns: A app, B began, C ended, D seconds, E minutes, F selected category,
        # G productivity category, H weight, I estimated coins.
        code_interval = row_values(timeline, 2)
        browser_interval = row_values(timeline, 3)
        assert code_interval["A"] == "code.exe"
        assert code_interval["B"] and code_interval["C"]
        assert code_interval["D"] == "2"
        assert code_interval["F"] == "coding"
        assert code_interval["G"] == "Productive"
        assert code_interval["H"] == "1.0"
        assert code_interval["I"] == "0.0333"
        assert browser_interval["A"] == "browser.exe"
        assert browser_interval["B"] and browser_interval["C"]
        assert browser_interval["D"] == "3"
        assert browser_interval["G"] == "Distraction"
        assert browser_interval["I"] == "0.05"

        app_summary = ET.fromstring(workbook.read("xl/worksheets/sheet3.xml"))
        # Columns: A app, B seconds, C minutes, D productivity category, E weight, F estimated coins.
        assert row_values(app_summary, 2) == {
            "A": "browser.exe", "B": "3", "C": "0.05", "D": "Distraction", "E": "0.0", "F": "0.05",
        }
        assert row_values(app_summary, 3) == {
            "A": "code.exe", "B": "2", "C": "0.03", "D": "Productive", "E": "1.0", "F": "0.03",
        }

        # Summary confirms the actual sampled total, reward rate, and category estimate.
        assert row_values(summary, 6)["B"] == "5"
        assert row_values(summary, 15)["B"] == "15"
        assert row_values(summary, 16)["B"] == "0.08"


def test_fractional_sample_delays_do_not_lose_foreground_duration(tmp_path: Path):
    clock = FakeClock()
    tracker = ActivityTracker(
        tmp_path / "activity.sqlite3",
        app_reader=lambda: "editor.exe",
        wall_clock=clock.wall,
        monotonic=clock.monotonic,
    )
    recording_id = "f5a0f95a-b67e-4be2-9201-5a06f3d1a954"
    tracker.start(recording_id, "coding")

    # Ten normal-but-slightly-late samples span eleven seconds. Rounding each
    # sample separately would record only ten seconds.
    for sample in range(1, 11):
        clock.seconds = 100 + sample * 1.1
        tracker.poll()
    result = tracker.stop(recording_id)

    assert result["foreground_seconds"] == 11
    report = tracker.workbook(recording_id)
    with ZipFile(BytesIO(report)) as workbook:
        namespace = {"sheet": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        summary = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        row = summary.find(".//sheet:row[@r='6']", namespace)
        assert row.find("sheet:c[@r='B6']/sheet:v", namespace).text == "11"


def test_private_tracking_is_rejected_and_only_one_recording_can_run(tmp_path: Path):
    tracker = ActivityTracker(tmp_path / "activity.sqlite3", app_reader=lambda: "editor.exe")
    with pytest.raises(ValueError, match="Private Mode"):
        tracker.start("f5a0f95a-b67e-4be2-9201-5a06f3d1a954", "private")

    tracker.start("f5a0f95a-b67e-4be2-9201-5a06f3d1a954", "coding")
    with pytest.raises(RuntimeError, match="already active"):
        tracker.start("d8a7f625-30df-4f49-80d9-96a8524984fc", "assignment")


def test_lost_browser_heartbeat_interrupts_and_can_still_be_exported(tmp_path: Path):
    clock = FakeClock()
    tracker = ActivityTracker(
        tmp_path / "activity.sqlite3",
        app_reader=lambda: "editor.exe",
        wall_clock=clock.wall,
        monotonic=clock.monotonic,
        heartbeat_timeout=5,
    )
    recording_id = "f5a0f95a-b67e-4be2-9201-5a06f3d1a954"
    tracker.start(recording_id, "assignment")
    clock.seconds = 106
    tracker.poll()

    assert tracker.status() == {"ready": True, "tracking": False}
    assert tracker.recent_recordings()[0]["status"] == "interrupted"
    assert ZipFile(BytesIO(tracker.workbook(recording_id))).testzip() is None


def test_companion_lists_saved_reports_and_agrees_on_its_port(tmp_path: Path):
    assert COMPANION_PORT == 8765
    tracker = ActivityTracker(tmp_path / "activity.sqlite3", app_reader=lambda: "editor.exe")
    server = CompanionHTTPServer(("127.0.0.1", 0), tracker, "test-pairing-code")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        recording_id = "f5a0f95a-b67e-4be2-9201-5a06f3d1a954"
        tracker.start(recording_id, "research")
        tracker.stop(recording_id)
        connection = http.client.HTTPConnection(*server.server_address, timeout=3)
        try:
            connection.request(
                "GET", "/api/recordings",
                headers={"Authorization": "Bearer test-pairing-code"},
            )
            response = connection.getresponse()
            payload = json.loads(response.read())
        finally:
            connection.close()
        assert response.status == 200
        assert [row["id"] for row in payload["recordings"]] == [recording_id]
        assert payload["recordings"][0]["session_type"] == "research"
        assert payload["recordings"][0]["status"] == "completed"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_deleting_a_report_removes_its_local_timeline(tmp_path: Path):
    tracker = ActivityTracker(tmp_path / "activity.sqlite3", app_reader=lambda: "editor.exe")
    recording_id = "f5a0f95a-b67e-4be2-9201-5a06f3d1a954"
    tracker.start(recording_id, "learning")
    tracker.stop(recording_id)
    tracker.delete(recording_id)
    assert tracker.recent_recordings() == []
    with pytest.raises(KeyError, match="not found"):
        tracker.workbook(recording_id)
