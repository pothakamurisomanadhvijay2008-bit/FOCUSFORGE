"""Minimal XLSX export using Python's standard library."""

from __future__ import annotations

from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from .rewards import COINS_PER_15_MINUTES
from .app_classifier import classify_app, work_score, score_label

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("", _MAIN)
ET.register_namespace("r", _REL_DOC)


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def sessions_workbook(rows: list[dict]) -> bytes:
    """Build a single-sheet workbook from sessions belonging to one user."""
    headers = [
        "Session type", "Task", "Outcome", "Status", "Started at (UTC)",
        "Ended at (UTC)", "Tracked seconds", "Tracked minutes",
        "Self-rated focus (1-5)", "Logged distractions", "Coins earned",
    ]
    data = [headers]
    for session in rows:
        seconds = max(0, int(session.get("elapsed_seconds") or 0))
        data.append([
            session.get("session_type") or "",
            session.get("task_description") or "",
            session.get("goal") or "",
            session.get("status") or "",
            session.get("started_at") or "",
            session.get("ended_at") or "",
            seconds,
            round(seconds / 60, 2),
            session.get("focus_rating"),
            int(session.get("distraction_count") or 0),
            int(session.get("reward_coins") or 0),
        ])

    sheet = ET.Element(f"{{{_MAIN}}}worksheet")
    sheet_data = ET.SubElement(sheet, f"{{{_MAIN}}}sheetData")
    for row_number, values in enumerate(data, 1):
        row_element = ET.SubElement(sheet_data, f"{{{_MAIN}}}row", {"r": str(row_number)})
        for column_index, value in enumerate(values, 1):
            if value is None:
                continue
            cell = ET.SubElement(row_element, f"{{{_MAIN}}}c", {"r": f"{_column_name(column_index)}{row_number}"})
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                ET.SubElement(cell, f"{{{_MAIN}}}v").text = str(value)
            else:
                cell.set("t", "inlineStr")
                inline = ET.SubElement(cell, f"{{{_MAIN}}}is")
                text = ET.SubElement(inline, f"{{{_MAIN}}}t")
                text.text = str(value)

    if len(data) > 1:
        ET.SubElement(sheet, f"{{{_MAIN}}}autoFilter", {"ref": f"A1:K{len(data)}"})
    workbook = ET.Element(f"{{{_MAIN}}}workbook")
    sheets = ET.SubElement(workbook, f"{{{_MAIN}}}sheets")
    ET.SubElement(sheets, f"{{{_MAIN}}}sheet", {"name": "Sessions", "sheetId": "1", f"{{{_REL_DOC}}}id": "rId1"})

    package_rels = ET.Element(f"{{{_REL_PKG}}}Relationships")
    ET.SubElement(package_rels, f"{{{_REL_PKG}}}Relationship", {
        "Id": "rId1", "Type": f"{_REL_DOC}/officeDocument", "Target": "xl/workbook.xml",
    })
    workbook_rels = ET.Element(f"{{{_REL_PKG}}}Relationships")
    ET.SubElement(workbook_rels, f"{{{_REL_PKG}}}Relationship", {
        "Id": "rId1", "Type": f"{_REL_DOC}/worksheet", "Target": "worksheets/sheet1.xml",
    })

    content_types = ET.Element("{http://schemas.openxmlformats.org/package/2006/content-types}Types")
    ET.SubElement(content_types, "{http://schemas.openxmlformats.org/package/2006/content-types}Default", {
        "Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml",
    })
    ET.SubElement(content_types, "{http://schemas.openxmlformats.org/package/2006/content-types}Default", {
        "Extension": "xml", "ContentType": "application/xml",
    })
    ET.SubElement(content_types, "{http://schemas.openxmlformats.org/package/2006/content-types}Override", {
        "PartName": "/xl/workbook.xml",
        "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    })
    ET.SubElement(content_types, "{http://schemas.openxmlformats.org/package/2006/content-types}Override", {
        "PartName": "/xl/worksheets/sheet1.xml",
        "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml",
    })

    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", ET.tostring(content_types, encoding="utf-8", xml_declaration=True))
        archive.writestr("_rels/.rels", ET.tostring(package_rels, encoding="utf-8", xml_declaration=True))
        archive.writestr("xl/workbook.xml", ET.tostring(workbook, encoding="utf-8", xml_declaration=True))
        archive.writestr("xl/_rels/workbook.xml.rels", ET.tostring(workbook_rels, encoding="utf-8", xml_declaration=True))
        archive.writestr("xl/worksheets/sheet1.xml", ET.tostring(sheet, encoding="utf-8", xml_declaration=True))
    return output.getvalue()


def app_activity_workbook(recording: dict, events: list[dict]) -> bytes:
    """Build a local companion report for foreground-app intervals in one recording.

    Includes app classification (productive / distraction / neutral), productivity
    weight, and an overall work-score summary so the downloaded file is a complete
    self-contained activity report.
    """
    session_type = str(recording.get("session_type") or "")
    rate = int(COINS_PER_15_MINUTES.get(session_type, 0))
    normalized = []
    totals: dict[str, dict] = {}
    total_seconds = 0

    for event in events:
        seconds = max(0, int(event.get("elapsed_seconds") or 0))
        app_name = str(event.get("app_name") or "Unknown app")
        estimated_coins = round(seconds * rate / 900, 4)
        classification = classify_app(app_name, session_type)
        category = classification["category"]
        weight = classification["weight"]
        normalized.append({
            "app_name": app_name,
            "started_at": str(event.get("foreground_started_at") or ""),
            "ended_at": str(event.get("foreground_ended_at") or ""),
            "seconds": seconds,
            "coins": estimated_coins,
            "category": category,
            "weight": weight,
        })
        group = totals.setdefault(app_name, {
            "seconds": 0, "coins": 0.0, "category": category, "weight": weight,
        })
        group["seconds"] = int(group["seconds"]) + seconds
        group["coins"] = float(group["coins"]) + seconds * rate / 900
        total_seconds += seconds

    # Work-score calculation over all aggregated intervals
    score_intervals = [
        {"app_name": name, "elapsed_seconds": int(v["seconds"])}
        for name, v in totals.items()
    ]
    score_data = work_score(score_intervals, session_type) if score_intervals else {
        "score": 0, "productive_seconds": 0, "distraction_seconds": 0, "neutral_seconds": 0,
    }
    score = score_data["score"]
    label = score_label(score)
    productive_pct = (
        round(score_data["productive_seconds"] / total_seconds * 100, 1) if total_seconds else 0
    )
    distraction_pct = (
        round(score_data["distraction_seconds"] / total_seconds * 100, 1) if total_seconds else 0
    )

    summary = [
        ["Recording ID", recording.get("id", "")],
        ["Selected session category", session_type],
        ["Tracking started (local time)", recording.get("started_at", "")],
        ["Tracking ended (local time)", recording.get("ended_at", "")],
        ["Foreground app time (seconds)", total_seconds],
        ["Foreground app time (minutes)", round(total_seconds / 60, 2)],
        # Work-score block
        ["Work score (0-100)", score],
        ["Work score label", label],
        ["Productive time (seconds)", score_data["productive_seconds"]],
        ["Productive time (%)", productive_pct],
        ["Distraction time (seconds)", score_data["distraction_seconds"]],
        ["Distraction time (%)", distraction_pct],
        ["Neutral / system time (seconds)", score_data["neutral_seconds"]],
        # Coins block
        ["Estimated reward rate (coins per 15 minutes)", rate],
        ["Estimated app-activity coins", round(total_seconds * rate / 900, 2)],
        # Transparency block
        ["Tracking precision", "Foreground app sampled about once per second"],
        ["Privacy", "Executable names and foreground times only; no window titles, screen content, keystrokes, or upload"],
        ["Reward note", "Estimate uses the session category selected by the user. It does not verify work or change account coins."],
        ["Score note", "Work score reflects app-category weights relative to the selected session type. It does not verify actual work."],
    ]

    timeline_rows = [[
        event["app_name"],
        event["started_at"],
        event["ended_at"],
        event["seconds"],
        round(event["seconds"] / 60, 2),
        session_type,
        event["category"].title(),
        event["weight"],
        event["coins"],
    ] for event in normalized]

    app_summary_rows = []
    for app_name, values in sorted(
        totals.items(), key=lambda item: (-int(item[1]["seconds"]), item[0].casefold())
    ):
        seconds = int(values["seconds"])
        app_summary_rows.append([
            app_name,
            seconds,
            round(seconds / 60, 2),
            values["category"].title(),
            values["weight"],
            round(float(values["coins"]), 2),
        ])

    sheets = [
        ("Recording", ["Field", "Value"], summary),
        ("App timeline", [
            "Foreground app",
            "Foreground began at (local)",
            "Foreground ended at (local)",
            "Foreground seconds",
            "Foreground minutes",
            "Selected category",
            "Productivity category",
            "Productivity weight",
            "Estimated coins",
        ], timeline_rows),
        ("App summary", [
            "Foreground app",
            "Foreground seconds",
            "Foreground minutes",
            "Productivity category",
            "Productivity weight",
            "Estimated coins",
        ], app_summary_rows),
    ]
    return _multi_sheet_workbook(sheets)


def _multi_sheet_workbook(sheets: list[tuple[str, list[str], list[list]]]) -> bytes:
    """Serialize a small, dependency-free XLSX workbook with inline strings."""
    _CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
    relationships = ET.Element(f"{{{_REL_PKG}}}Relationships")
    workbook_rels = ET.Element(f"{{{_REL_PKG}}}Relationships")
    content_types = ET.Element(f"{{{_CONTENT_TYPES}}}Types")
    ET.SubElement(content_types, f"{{{_CONTENT_TYPES}}}Default", {
        "Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml",
    })
    ET.SubElement(content_types, f"{{{_CONTENT_TYPES}}}Default", {
        "Extension": "xml", "ContentType": "application/xml",
    })
    ET.SubElement(content_types, f"{{{_CONTENT_TYPES}}}Override", {
        "PartName": "/xl/workbook.xml",
        "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    })
    workbook = ET.Element(f"{{{_MAIN}}}workbook")
    workbook_sheets = ET.SubElement(workbook, f"{{{_MAIN}}}sheets")
    ET.SubElement(relationships, f"{{{_REL_PKG}}}Relationship", {
        "Id": "rId1", "Type": f"{_REL_DOC}/officeDocument", "Target": "xl/workbook.xml",
    })

    worksheet_xml: list[tuple[str, bytes]] = []
    for sheet_index, (sheet_name, headers, rows) in enumerate(sheets, 1):
        relation_id = f"rId{sheet_index}"
        ET.SubElement(workbook_sheets, f"{{{_MAIN}}}sheet", {
            "name": sheet_name, "sheetId": str(sheet_index), f"{{{_REL_DOC}}}id": relation_id,
        })
        ET.SubElement(workbook_rels, f"{{{_REL_PKG}}}Relationship", {
            "Id": relation_id, "Type": f"{_REL_DOC}/worksheet",
            "Target": f"worksheets/sheet{sheet_index}.xml",
        })
        ET.SubElement(content_types, f"{{{_CONTENT_TYPES}}}Override", {
            "PartName": f"/xl/worksheets/sheet{sheet_index}.xml",
            "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml",
        })
        sheet = ET.Element(f"{{{_MAIN}}}worksheet")
        sheet_data = ET.SubElement(sheet, f"{{{_MAIN}}}sheetData")
        for row_number, values in enumerate([headers, *rows], 1):
            row_element = ET.SubElement(sheet_data, f"{{{_MAIN}}}row", {"r": str(row_number)})
            for column_index, value in enumerate(values, 1):
                if value is None:
                    continue
                cell = ET.SubElement(row_element, f"{{{_MAIN}}}c", {
                    "r": f"{_column_name(column_index)}{row_number}",
                })
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    ET.SubElement(cell, f"{{{_MAIN}}}v").text = str(value)
                else:
                    cell.set("t", "inlineStr")
                    inline = ET.SubElement(cell, f"{{{_MAIN}}}is")
                    ET.SubElement(inline, f"{{{_MAIN}}}t").text = str(value)
        if rows:
            ET.SubElement(sheet, f"{{{_MAIN}}}autoFilter", {
                "ref": f"A1:{_column_name(len(headers))}{len(rows) + 1}",
            })
        worksheet_xml.append((f"xl/worksheets/sheet{sheet_index}.xml", ET.tostring(sheet, encoding="utf-8", xml_declaration=True)))

    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", ET.tostring(content_types, encoding="utf-8", xml_declaration=True))
        archive.writestr("_rels/.rels", ET.tostring(relationships, encoding="utf-8", xml_declaration=True))
        archive.writestr("xl/workbook.xml", ET.tostring(workbook, encoding="utf-8", xml_declaration=True))
        archive.writestr("xl/_rels/workbook.xml.rels", ET.tostring(workbook_rels, encoding="utf-8", xml_declaration=True))
        for path, contents in worksheet_xml:
            archive.writestr(path, contents)
    return output.getvalue()
