"""Small SQLite persistence layer for FocusForge accounts and work sessions."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize(path: Path) -> None:
    with connect(path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                daily_goal_minutes INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS auth_sessions_user_idx
                ON auth_sessions(user_id);
            CREATE TABLE IF NOT EXISTS work_sessions (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                session_type TEXT NOT NULL,
                title TEXT NOT NULL,
                task_description TEXT NOT NULL DEFAULT '',
                goal TEXT NOT NULL DEFAULT '',
                duration_minutes INTEGER,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                elapsed_seconds INTEGER NOT NULL DEFAULT 0,
                boot_id TEXT,
                completion_note TEXT NOT NULL DEFAULT '',
                focus_rating INTEGER,
                distraction_count INTEGER NOT NULL DEFAULT 0,
                reward_coins INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS work_sessions_user_started_idx
                ON work_sessions(user_id, started_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS one_live_session_per_user
                ON work_sessions(user_id)
                WHERE status IN ('running', 'paused');
            """
        )
        columns = {row["name"] for row in db.execute("PRAGMA table_info(work_sessions)")}
        if "completion_note" not in columns:
            db.execute("ALTER TABLE work_sessions ADD COLUMN completion_note TEXT NOT NULL DEFAULT ''")
        if "focus_rating" not in columns:
            db.execute("ALTER TABLE work_sessions ADD COLUMN focus_rating INTEGER")
        if "distraction_count" not in columns:
            db.execute("ALTER TABLE work_sessions ADD COLUMN distraction_count INTEGER NOT NULL DEFAULT 0")
        if "reward_coins" not in columns:
            db.execute("ALTER TABLE work_sessions ADD COLUMN reward_coins INTEGER NOT NULL DEFAULT 0")
