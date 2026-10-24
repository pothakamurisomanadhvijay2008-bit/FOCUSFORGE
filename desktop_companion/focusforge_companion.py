"""Launch the visible, opt-in Windows foreground-app companion."""

from __future__ import annotations

import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from desktop_companion.tracker import (  # noqa: E402
    ActivityTracker,
    COMPANION_PORT,
    CompanionHTTPServer,
    companion_data_path,
    new_pairing_token,
)

COMPANION_HOST = "127.0.0.1"


class CompanionWindow:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("FocusForge · Desktop Companion")
        self.root.geometry("440x390")
        self.root.minsize(440, 360)
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#f4f1e8")
        self.tracker = ActivityTracker(companion_data_path())
        self.pairing_token = new_pairing_token()
        self.server: CompanionHTTPServer | None = None
        self.server_thread: threading.Thread | None = None
        self.status_text = tk.StringVar(value="Starting local companion…")
        self.current_app_text = tk.StringVar(value="No app tracking is active")
        self._build_ui()
        self._start_server()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(1000, self.refresh)

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f1e8")
        style.configure("TLabel", background="#f4f1e8", foreground="#283a34", font=("Segoe UI", 9))
        style.configure("Title.TLabel", font=("Georgia", 17), foreground="#183b34")
        style.configure("Small.TLabel", font=("Segoe UI", 8), foreground="#64716a")
        style.configure("Treeview", rowheight=24, font=("Segoe UI", 8))
        style.configure("Treeview.Heading", font=("Segoe UI", 8, "bold"))

        frame = ttk.Frame(self.root, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="FocusForge · desktop activity", style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame, textvariable=self.status_text).pack(anchor="w", pady=(4, 0))

        active = ttk.LabelFrame(frame, text="Visible tracking status", padding=9)
        active.pack(fill="x", pady=(10, 8))
        ttk.Label(active, textvariable=self.current_app_text, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(
            active,
            text="The overlay stays above other windows. Minimize it to the taskbar while you work.",
            style="Small.TLabel", wraplength=385,
        ).pack(anchor="w", pady=(4, 0))
        buttons = ttk.Frame(active)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Stop app tracking", command=self.stop_tracking).pack(side="left")
        ttk.Button(buttons, text="Minimize", command=self.root.iconify).pack(side="right")

        pairing = ttk.LabelFrame(frame, text="Dashboard pairing code", padding=9)
        pairing.pack(fill="x", pady=(0, 8))
        self.code_label = ttk.Label(pairing, text=self.pairing_token, font=("Consolas", 8), wraplength=385)
        self.code_label.pack(anchor="w")
        pairing_buttons = ttk.Frame(pairing)
        pairing_buttons.pack(fill="x", pady=(5, 0))
        ttk.Button(pairing_buttons, text="Copy code", command=self.copy_code).pack(side="left")
        ttk.Label(pairing_buttons, text=f"Local only · 127.0.0.1:{COMPANION_PORT}", style="Small.TLabel").pack(side="right")

        reports = ttk.LabelFrame(frame, text="Recent app reports (saved on this device)", padding=7)
        reports.pack(fill="both", expand=True)
        columns = ("started", "category", "state", "time")
        self.report_tree = ttk.Treeview(reports, columns=columns, show="headings", height=5, selectmode="browse")
        for key, title, width in (
            ("started", "Started", 130), ("category", "Category", 85),
            ("state", "State", 82), ("time", "App min", 70),
        ):
            self.report_tree.heading(key, text=title)
            self.report_tree.column(key, width=width, anchor="w" if key != "time" else "e")
        self.report_tree.pack(fill="both", expand=True)
        footer = ttk.Frame(reports)
        footer.pack(fill="x", pady=(5, 0))
        ttk.Button(footer, text="Refresh", command=self.refresh_reports).pack(side="left")
        ttk.Button(footer, text="Save selected Excel", command=self.save_selected).pack(side="right", padx=(5, 0))
        ttk.Button(footer, text="Delete", command=self.delete_selected).pack(side="right")

        ttk.Label(
            frame,
            text="Collects executable names and foreground times only. No titles, screen data, keys, or uploads. "
            "Private Mode is not supported.",
            style="Small.TLabel", wraplength=405,
        ).pack(anchor="w", pady=(8, 0))

    def _start_server(self) -> None:
        try:
            self.server = CompanionHTTPServer((COMPANION_HOST, COMPANION_PORT), self.tracker, self.pairing_token)
        except OSError as error:
            self.status_text.set(f"Local service could not start: {error}")
            return
        self.server_thread = threading.Thread(target=self.server.serve_forever, name="focusforge-companion-api", daemon=True)
        self.server_thread.start()
        self.status_text.set("Ready · tracking starts only when you opt in from a screen-recording action.")

    def copy_code(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.pairing_token)
        self.status_text.set("Pairing code copied. Paste it into the dashboard for this browser tab.")

    def refresh_reports(self) -> None:
        for item in self.report_tree.get_children():
            self.report_tree.delete(item)
        for row in self.tracker.recent_recordings():
            minutes = round(int(row["foreground_seconds"]) / 60, 1)
            self.report_tree.insert(
                "", "end", iid=row["id"],
                values=(row["started_at"].replace("T", " ")[:16], row["session_type"], row["status"], minutes),
            )

    def delete_selected(self) -> None:
        selected = self.report_tree.selection()
        if not selected:
            self.status_text.set("Select a stopped report to delete its local app timeline.")
            return
        recording_id = selected[0]
        if not messagebox.askyesno("Delete app report", "Permanently delete this app timeline from this device?", parent=self.root):
            return
        try:
            self.tracker.delete(recording_id)
            self.status_text.set("The selected local report was deleted.")
            self.refresh_reports()
        except (KeyError, RuntimeError) as error:
            self.status_text.set(str(error))

    def save_selected(self) -> None:
        selected = self.report_tree.selection()
        if not selected:
            self.status_text.set("Select a stopped report to save its Excel workbook.")
            return
        recording_id = selected[0]
        try:
            workbook = self.tracker.workbook(recording_id)
        except (KeyError, RuntimeError) as error:
            self.status_text.set(str(error))
            return
        downloads = Path.home() / "Downloads"
        destination = filedialog.asksaveasfilename(
            parent=self.root,
            initialdir=downloads if downloads.exists() else Path.home(),
            initialfile=f"focusforge-{recording_id}-app-activity.xlsx",
            defaultextension=".xlsx",
            filetypes=[("Excel workbook", "*.xlsx")],
            title="Save app activity report",
        )
        if not destination:
            return
        try:
            Path(destination).write_bytes(workbook)
            self.status_text.set("Excel report saved. Choose the screen recording's folder to keep both files together.")
        except OSError as error:
            self.status_text.set(f"Could not save the Excel report: {error}")

    def stop_tracking(self) -> None:
        result = self.tracker.stop_active()
        if result:
            self.status_text.set("App tracking stopped. The recording report is ready to download from the dashboard.")
        else:
            self.status_text.set("No app tracking is active.")
        self.refresh()

    def refresh(self) -> None:
        self.tracker.poll()
        state = self.tracker.status()
        if state["tracking"]:
            seconds = int(state["foreground_seconds"])
            elapsed = f"{seconds // 3600:02}:{(seconds % 3600) // 60:02}:{seconds % 60:02}"
            self.current_app_text.set(f"{state['session_type'].title()} · {elapsed} · Foreground: {state['current_app']}")
        else:
            self.current_app_text.set("No app tracking is active")
        self.refresh_reports()
        self.root.after(1000, self.refresh)

    def close(self) -> None:
        active = self.tracker.stop_active()
        if active:
            self.status_text.set("Active app tracking was stopped; its report is saved locally.")
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("FocusForge Desktop Companion is currently Windows-only.")
    CompanionWindow().run()
