# FocusForge AI — Agent Instructions (AGENTS.md)

> This file is the authoritative guide for AI coding agents working on this repository.
> Read it in full before making any changes. Preserve all sections when editing.

## Project identity

- **Name:** FocusForge AI
- **Repo root:** `PYTHON PROJECT/`
- **Branch convention:** `master` (main branch), feature branches as `feat/<name>`
- **Language:** Python 3.13+ (backend), Vanilla JS / HTML / CSS (frontend)
- **Phase:** 2 — local accounts and manually tracked work sessions

## Tech stack

| Layer      | Technology                                      |
|------------|-------------------------------------------------|
| Backend    | Python · FastAPI · Uvicorn · python-dotenv      |
| Frontend   | HTML5 · CSS3 · Vanilla JavaScript               |
| Analytics  | Pandas · NumPy · Matplotlib · Seaborn           |
| Testing    | pytest · pytest-asyncio · httpx (ASGI client)   |

## Directory layout

```
PYTHON PROJECT/
├── .agents/                  # Agent skills and configuration
├── .contextcapsule/          # Handoff capsules (gitignored)
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py           # FastAPI app factory + protected dashboard
│   │   ├── analytics.py      # Pandas/NumPy calculations and Matplotlib/Seaborn charts
│   │   ├── database.py       # SQLite schema and connections
│   │   ├── security.py       # Password hashes and opaque cookie sessions
│   │   ├── rewards.py        # Transparent per-category session coin rates
│   │   ├── spreadsheet.py    # Account-scoped XLSX export
│   │   └── routers/
│   │       ├── auth.py       # Registration, login, logout
│   │       ├── analytics.py  # Per-user historical analytics API
│   │       └── sessions.py   # Per-user session timer and summary API
│   ├── requirements.txt      # Pinned dependencies
│   └── .env.example          # Safe env template (committed)
├── desktop_companion/        # Optional Windows app-name/timing companion
│   ├── focusforge_companion.py # Visible always-on-top window and local API
│   └── tracker.py            # Opt-in foreground intervals and local reports
├── frontend/
│   ├── index.html            # Authenticated dashboard
│   ├── login.html            # Registration and login
│   ├── style.css             # Dark-theme design system
│   ├── auth.js                # Login and registration UI
│   └── app.js                # Dashboard, manual timers, real summaries
├── scripts/
│   └── dev.mjs               # Cross-platform npm launcher for the FastAPI app
├── package.json              # `npm run dev` entry point (no Node dependencies)
├── tests/
│   ├── test_health.py        # Auth, privacy, session, and API tests
│   ├── test_rewards.py       # Reward rules and workbook structure
│   └── test_desktop_companion.py # Local tracking and app workbook tests
├── .gitignore
├── skills-lock.json
└── AGENTS.md                 # ← you are here
```

## Critical constraints — READ BEFORE EVERY CHANGE

1. **Never commit secrets.** `.env` and `.env.*` are gitignored. Use `.env.example` for templates.
2. **Never persist Private Mode sessions** to disk, database, or analytics.
3. **Private Mode** must stay in browser memory only; never send private task details to the server. Screen recording is opt-in and disabled in Private Mode. The optional Windows companion may record foreground executable names and timestamps only during a separately consented screen recording; it must never start or run for Private Mode.
4. **Analytics** are account-scoped and use only completed manual sessions plus explicit self-reported focus ratings and distraction logs. Do not infer concentration, build cross-account HR rankings, or use metrics as employment decisions.
5. **No third-party analytics SDKs** (e.g., Google Analytics, Mixpanel) without user consent.
6. **Do not claim features are implemented** until tests pass and are marked `observed`.
7. **Inspect live files** before editing. Never overwrite current work from capsule state alone.
8. **Keep `.contextcapsule/` gitignored.** Update the capsule after each session.
9. **Coins** in the account are awarded only for completed, saved manual sessions using the user's selected category and tracked timer duration. Do not claim account coins measure attention, cursor movement, or app activity. Break and Private Mode sessions earn no persisted account coins. The companion's local workbook may show clearly labeled estimated app-activity coins based on the selected session category and foreground duration; these estimates never change the account balance or claim that work was verified.
10. **Desktop companion** tracking is Windows-only, local by default, and starts only after explicit app-activity consent and a user-started screen recording. Record executable basenames and foreground times only—never window titles, paths, URLs, screen contents, keystrokes, or cursor movements. Require the per-run pairing code; stop on recording end, missing heartbeat, app exit, or Private Mode. Provide local report deletion and never upload app-level events to account analytics.

## Development setup

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Install backend dependencies
python -m pip install -r backend/requirements.txt

# 3. Copy env template
Copy-Item backend/.env.example backend/.env

# 4. Run the backend and dashboard through npm (Node.js 18+; no npm install needed)
npm run dev
# This uses the project's virtual environment and serves the dashboard at port 8000.
# To use a different port in PowerShell: $env:PORT = "8001"; npm run dev
# Optional direct equivalent: python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

# 5. Open the dashboard
# Visit: http://127.0.0.1:8000/login
# Create an account (password must contain at least 10 characters).
# SQLite data is stored in ./focusforge.sqlite3 and is gitignored.
# API docs: http://127.0.0.1:8000/docs

# 6. Run tests (from project root)
python -m pytest tests/ -v
```

## API endpoints (Phase 1)

| Method | Path          | Description                     |
|--------|---------------|---------------------------------|
| GET    | `/`           | Dashboard; redirects to login without a session |
| GET    | `/login`      | Login and registration page     |
| GET    | `/api/health` | Liveness check — JSON response  |
| POST   | `/api/auth/register` | Create account and sign in |
| POST   | `/api/auth/login` | Sign in                     |
| POST   | `/api/auth/logout` | Revoke current cookie session |
| GET    | `/api/auth/me` | Current authenticated user     |
| POST   | `/api/sessions` | Start a manual session        |
| POST   | `/api/sessions/{id}/pause` | Pause timer     |
| POST   | `/api/sessions/{id}/resume` | Resume timer   |
| POST   | `/api/sessions/{id}/checkpoint` | Save timer checkpoint |
| POST   | `/api/sessions/{id}/distractions` | Log one self-reported distraction |
| POST   | `/api/sessions/{id}/stop` | Complete session |
| GET    | `/api/sessions` | Current user's recent sessions |
| GET    | `/api/sessions/export.xlsx` | Download current user's saved session history as an Excel workbook |
| GET    | `/api/dashboard` | Current user's completed-session totals |
| GET    | `/api/analytics` | Current user's weekly, monthly, or yearly self-reported analysis |
| GET    | `/api/analytics/chart` | Current user's Matplotlib/Seaborn analytics chart |
| GET    | `/docs`       | Interactive Swagger UI          |

## Phase roadmap (DO NOT implement ahead of schedule)

| Phase | Status        | Scope                                                      |
|-------|---------------|------------------------------------------------------------|
| 1     | ✅ Complete   | Scaffold: FastAPI, health endpoint, dark dashboard UI      |
| 2     | ✅ Complete   | SQLite accounts and manual session timer API                |
| 3     | 🟡 In progress | Historical analytics and charts from actual completed records; focus ratings and distractions are self-reported |
| 4     | 🟡 In progress | Transparent category-based coins on completed manual sessions; XP, levels, achievements, and skill tracking remain planned |
| 5     | 🟡 Partial    | Private Mode is client-only; personal goals are not implemented |
| 6     | ⬜ Planned    | Optional AI productivity coach (feature-flagged)           |
| 7     | 🟡 Partial    | In-browser screen recording (explicit consent and download), browser Picture-in-Picture, and optional Windows foreground-app timeline companion; installer packaging and automatic browser control remain unimplemented |

## ContextCapsule workflow

After every work session:

1. Run `node .agents/skills/contextcapsule-handoff/scripts/contextcapsule.mjs capture --repo .`
2. Prepare semantic input JSON (see `references/coding-handoff-v1.md`).
3. Run `create` with the `--out-dir .contextcapsule` flag.
4. Verify with `resume`. Do not commit the capsule files.

## Pending decisions

- Database backend: **SQLite** for local development. Production deployment and backup strategy remain undecided.
- AI coach API: provider and key management approach — decide before Phase 6.
- Native companion installer packaging and update delivery remain undecided; the Python/Tkinter companion is available as source. See `docs/desktop-companion.md` for setup, privacy limits, report pairing, and browser download-folder constraints.
