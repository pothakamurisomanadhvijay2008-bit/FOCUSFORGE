from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from backend.app.rewards import reward_coins
from backend.app.spreadsheet import sessions_workbook


def test_reward_rates_prioritize_coding_and_assignments():
    assert reward_coins("coding", 900) == 15
    assert reward_coins("assignment", 900) == 15
    assert reward_coins("creative", 900) == 12
    assert reward_coins("learning", 900) == 10
    assert reward_coins("video", 900) == 3
    assert reward_coins("break", 900) == 0
    assert reward_coins("private", 900) == 0
    assert reward_coins("coding", -20) == 0


def test_sessions_workbook_is_valid_and_contains_exported_fields():
    content = sessions_workbook([{
        "session_type": "assignment",
        "task_description": "Write a report & review it",
        "goal": "Draft one section",
        "status": "completed",
        "started_at": "2026-10-23T09:00:00+00:00",
        "ended_at": "2026-10-23T09:30:00+00:00",
        "elapsed_seconds": 1800,
        "focus_rating": 4,
        "distraction_count": 2,
        "reward_coins": 30,
    }])
    with ZipFile(BytesIO(content)) as workbook:
        assert workbook.testzip() is None
        assert "xl/workbook.xml" in workbook.namelist()
        sheet = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
    namespace = {"sheet": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    values = [node.text for node in sheet.findall(".//sheet:t", namespace)]
    assert "Session type" in values
    assert "assignment" in values
    assert "Write a report & review it" in values
    assert sheet.find("sheet:autoFilter", namespace) is not None
