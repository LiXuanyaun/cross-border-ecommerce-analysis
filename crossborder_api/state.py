from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
import json
import sqlite3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateStore:
    """Private-mode operational state. Provider credentials never enter this store."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS work_items (
                    item_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    session_id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES agent_sessions(session_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS agent_runs (
                    run_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY(session_id) REFERENCES agent_sessions(session_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS agent_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, sequence),
                    FOREIGN KEY(run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
                );
                """
            )

    def load_work_items(self) -> dict[str, dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT item_id, payload_json FROM work_items").fetchall()
        return {str(row["item_id"]): json.loads(row["payload_json"]) for row in rows}

    def save_work_item(self, item_id: str, payload: dict[str, Any]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO work_items(item_id, payload_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at
                """,
                (item_id, json.dumps(payload, ensure_ascii=False), _now()),
            )

    def load_sessions(self) -> dict[str, dict[str, Any]]:
        with self._lock, self._connect() as connection:
            sessions = connection.execute(
                "SELECT session_id, dataset_id, created_at FROM agent_sessions"
            ).fetchall()
            messages = connection.execute(
                "SELECT session_id, role, content FROM agent_messages ORDER BY id"
            ).fetchall()
        result = {
            str(row["session_id"]): {
                "session_id": str(row["session_id"]),
                "dataset_id": str(row["dataset_id"]),
                "created_at": str(row["created_at"]),
                "messages": [],
            }
            for row in sessions
        }
        for row in messages:
            if row["session_id"] in result:
                result[row["session_id"]]["messages"].append(
                    {"role": str(row["role"]), "content": str(row["content"])}
                )
        return result

    def save_session(self, session: dict[str, Any]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO agent_sessions(session_id, dataset_id, created_at) VALUES (?, ?, ?)",
                (session["session_id"], session["dataset_id"], session["created_at"]),
            )

    def save_run(self, run_id: str, session_id: str, dataset_id: str, question: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO agent_runs VALUES (?, ?, ?, ?, 'RUNNING', ?, NULL)",
                (run_id, session_id, dataset_id, question, _now()),
            )

    def save_event(self, run_id: str, sequence: int, event: dict[str, Any]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO agent_events(run_id, sequence, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    run_id,
                    sequence,
                    event["type"],
                    json.dumps(event["payload"], ensure_ascii=False),
                    _now(),
                ),
            )

    def save_messages(self, session_id: str, messages: list[dict[str, str]]) -> None:
        with self._lock, self._connect() as connection:
            connection.executemany(
                "INSERT INTO agent_messages(session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                [(session_id, item["role"], item["content"], _now()) for item in messages],
            )

    def finish_run(self, run_id: str, status: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE agent_runs SET status=?, completed_at=? WHERE run_id=?",
                (status, _now(), run_id),
            )
