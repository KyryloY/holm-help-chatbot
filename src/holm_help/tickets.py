"""Local SQLite ticket store for simulated human handoff."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from holm_help.config import TICKETS_DB as DEFAULT_TICKETS_DB

TICKETS_DB = DEFAULT_TICKETS_DB

_lock = threading.Lock()


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else TICKETS_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_tickets(db_path: Path | None = None) -> None:
    with _lock:
        conn = _connect(db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    order_id TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()


def create_ticket(
    *,
    thread_id: str,
    summary: str,
    order_id: str | None = None,
    db_path: Path | None = None,
) -> dict:
    """Create a simulated support ticket and return its fields."""
    init_tickets(db_path)
    created_at = datetime.now(timezone.utc).isoformat()
    # Deterministic-looking simulated ticket id.
    suffix = abs(hash(f"{thread_id}:{created_at}:{summary}")) % 10_000_000
    ticket_id = f"TICKET-{suffix:07d}"

    with _lock:
        conn = _connect(db_path)
        try:
            conn.execute(
                """
                INSERT INTO tickets (id, thread_id, summary, order_id, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (ticket_id, thread_id, summary, order_id, "open", created_at),
            )
            conn.commit()
        finally:
            conn.close()

    return {
        "id": ticket_id,
        "thread_id": thread_id,
        "summary": summary,
        "order_id": order_id,
        "status": "open",
        "created_at": created_at,
        "simulated": True,
    }


def count_tickets(db_path: Path | None = None) -> int:
    init_tickets(db_path)
    with _lock:
        conn = _connect(db_path)
        try:
            row = conn.execute("SELECT COUNT(*) AS n FROM tickets").fetchone()
            return int(row["n"])
        finally:
            conn.close()
