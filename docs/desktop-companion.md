# FocusForge Windows companion

The optional Windows companion adds a small always-on-top window and an app timeline that can accompany an explicit browser screen recording. It is a local development tool, launched separately from the FastAPI site.

## Start it

From the repository root, run the project's Python environment:

```powershell
.\.venv\Scripts\python.exe .\desktop_companion\focusforge_companion.py
```

Keep the companion open. Its window displays a one-run pairing code. In an active, non-Private FocusForge session, check both the screen-recording consent and the separate app-activity consent, paste the companion code into the dashboard, and click **Connect**. The code is held in that browser tab's `sessionStorage` and is not sent to the FocusForge server. A newly launched companion gets a new code.

When the user explicitly starts screen recording and grants the browser's screen-share prompt, the dashboard sends a recording ID and the selected session category to the companion at `127.0.0.1:8765`. The companion samples the foreground process about once per second. Stopping the recording or ending screen sharing stops the app timeline. Closing or navigating away from the dashboard sends a best-effort stop signal; a 90-second heartbeat timeout is the fallback if the tab disappears unexpectedly. The companion does not begin tracking on its own.

## Files and reports

After stopping, **Download recording** saves a `.webm` video and **Download app activity Excel** saves a separate `.xlsx` workbook. Both names contain the same recording ID. Where the browser supports the File System Access API, **Save video + Excel together** asks for one folder and writes both files there. Otherwise, the browser controls each download; if it asks where to save the files, choose the same folder. The companion's **Save selected Excel** action is a recovery option if the dashboard closes; it opens a save dialog so the user can choose the video folder directly.

After pairing, the dashboard's **Screen Activity** section also lists the reports saved on this device. **View app time** shows how long each foreground executable was observed and its share of the recording, and **Excel** downloads the same workbook, so the data is still retrievable after the page is reloaded. Those views read the local companion through the signed-in backend proxy; the rows are still not uploaded to account storage or added to account analytics.

The workbook has a recording summary, foreground timeline, and per-app totals. Each timeline row includes the executable name, local foreground start/end timestamps, duration, selected category, and estimated coins. It reports when an executable was observed in the foreground and when focus moved to another process; it does not report when an app was launched or closed in the background. Sampling is approximately once per second, so transition times may be off by about a second. The dashboard's **Download session-history Excel** is a separate account export and does not contain these app rows.

The companion keeps opted-in intervals in `%LOCALAPPDATA%/FocusForgeAI/app-activity.sqlite3` until the user deletes a report in the companion or dashboard. Closing the companion stops an active timeline; the next launch marks any unfinished record as interrupted and never resumes tracking. The native window stays above work windows by default and can be minimized to the taskbar.

## Privacy and reward limits

The companion stores executable basenames and foreground start/end times only. It does not read or store window titles, full executable paths, browser URLs, screen contents, keystrokes, or cursor movement. App records stay in the local companion database and are sent only back to the paired browser when the user clicks the Excel download button; they are not uploaded to the account API.

The report's **estimated app-activity coins** use the session category the user selected in FocusForge (for example, Coding or Learning) and the observed foreground duration. The estimate is not a judgment of app content or work quality and does not change the account coin balance. The existing account coins still come from completed manual session timers. No inactivity or attention score is calculated.

Private Mode never starts the companion, does not call its API, and cannot be used with recording. The companion API accepts paired requests only from the local development dashboard origins `http://127.0.0.1:8000`, `http://localhost:8000`, `http://127.0.0.1:8001`, and `http://localhost:8001`, listens on loopback only, and requires the per-run pairing code.

## If Connect cannot reach the companion

The dashboard's port must match an origin allowed by the companion. If the dashboard is using port 8001, close the companion window after stopping any active recording, then launch it again from this repository's root so it loads the current origin allowlist. The companion does not hot-reload code. Do not launch a second copy while the old one is open; only one process can listen on `127.0.0.1:8765`. Copy the newly displayed pairing code after restarting.

## Boundaries

- The companion can identify the foreground process name, but not what the user is doing in that app. A browser process may show many unrelated pages; FocusForge does not inspect them.
- This is not a browser blocker, an HR ranking tool, or proof of productivity. Foreground time is descriptive.
- The Python/Tkinter source is not packaged as an installer yet. The desktop app requires Windows and a Python installation with Tkinter.
- A website cannot read a browser-saved video path. Use **Save video + Excel together** where supported, or choose the same location in each save dialog.
- The separate browser Picture-in-Picture window remains available where supported. The native companion window is the cross-app overlay; browser PiP support and always-on-top behavior still depend on the browser and OS.
