# FocusForge AI — Agent Instructions (AGENTS.md)

> This file is the authoritative guide for AI coding agents working on this repository.
> Read it in full before making any changes. Preserve all sections when editing.

## Project identity

- **Name:** FocusForge AI
- **Repo root:** `PYTHON PROJECT/`
- **Branch convention:** `master` (main branch), feature branches as `feat/<name>`
- **Language:** Python 3.13+ (backend), Vanilla JS / HTML / CSS (frontend)
- **Phase:** 1 — initial scaffold

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
│   │   ├── main.py           # FastAPI app factory + routes
│   │   └── routers/
│   │       └── __init__.py   # Router sub-package (expand per feature)
│   ├── requirements.txt      # Pinned dependencies
│   └── .env.example          # Safe env template (committed)
├── frontend/
│   ├── index.html            # Dashboard SPA shell
│   ├── style.css             # Dark-theme design system
│   └── app.js                # UI logic, health polling, sample data
├── tests/
│   └── test_health.py        # Pytest async health endpoint tests
├── .gitignore
├── skills-lock.json
└── AGENTS.md                 # ← you are here
```

## Critical constraints — READ BEFORE EVERY CHANGE

1. **Never commit secrets.** `.env` and `.env.*` are gitignored. Use `.env.example` for templates.
2. **Never persist Private Mode sessions** to disk, database, or analytics.
3. **Screen recording** requires explicit per-session user consent (browser `MediaDevices` API). Do not add recording code without a consent gate.
4. **No third-party analytics SDKs** (e.g., Google Analytics, Mixpanel) without user consent.
5. **Do not claim features are implemented** until tests pass and are marked `observed`.
6. **Inspect live files** before editing. Never overwrite current work from capsule state alone.
7. **Keep `.contextcapsule/` gitignored.** Update the capsule after each session.

## Development setup

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Install backend dependencies
python -m pip install -r backend/requirements.txt

# 3. Copy env template
Copy-Item backend/.env.example backend/.env

# 4. Run the backend server
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000

# 5. Open the dashboard
# Visit: http://127.0.0.1:8000
# API docs: http://127.0.0.1:8000/docs

# 6. Run tests (from project root)
python -m pytest tests/ -v
```

## API endpoints (Phase 1)

| Method | Path          | Description                     |
|--------|---------------|---------------------------------|
| GET    | `/`           | Redirect to `/docs`             |
| GET    | `/api/health` | Liveness check — JSON response  |
| GET    | `/docs`       | Interactive Swagger UI          |

## Phase roadmap (DO NOT implement ahead of schedule)

| Phase | Status        | Scope                                                      |
|-------|---------------|------------------------------------------------------------|
| 1     | ✅ Complete   | Scaffold: FastAPI, health endpoint, dark dashboard UI      |
| 2     | ⬜ Planned    | Work-session timer API, basic session storage (SQLite)     |
| 3     | ⬜ Planned    | Analytics: Pandas/NumPy processing, Matplotlib/Seaborn charts |
| 4     | ⬜ Planned    | XP engine, levels, achievements, skill tracking            |
| 5     | ⬜ Planned    | Personal goals, Private Mode enforcement                   |
| 6     | ⬜ Planned    | Optional AI productivity coach (feature-flagged)           |
| 7     | ⬜ Planned    | Screen recording (explicit consent gate, opt-in only)      |

## ContextCapsule workflow

After every work session:

1. Run `node .agents/skills/contextcapsule-handoff/scripts/contextcapsule.mjs capture --repo .`
2. Prepare semantic input JSON (see `references/coding-handoff-v1.md`).
3. Run `create` with the `--out-dir .contextcapsule` flag.
4. Verify with `resume`. Do not commit the capsule files.

## Pending decisions

- Database backend: **SQLite** (simple) vs **PostgreSQL** (scalable) — decide before Phase 2.
- AI coach API: provider and key management approach — decide before Phase 6.
- Screen-recording consent UX design — required before Phase 7.
