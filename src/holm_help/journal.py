"""Local SQLite journal for simulated return labels (idempotent)."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from holm_help.config import JOURNAL_DB

_lock = threading.Lock()


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else JOURNAL_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_journal(db_path: Path | None = None) -> None:
    """Create the returns journal table if needed."""
    with _lock:
        conn = _connect(db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS returns (
                    order_id TEXT PRIMARY KEY,
                    label_number TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()


def get_existing_return(order_id: str, db_path: Path | None = None) -> str | None:
    """Return an existing simulated label number, or None."""
    init_journal(db_path)
    with _lock:
        conn = _connect(db_path)
        try:
            row = conn.execute(
                "SELECT label_number FROM returns WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            return None if row is None else str(row["label_number"])
        finally:
            conn.close()


def create_return_entry(order_id: str, db_path: Path | None = None) -> str:
    """
    Idempotently write a simulated return label.

    A repeat call for the same order_id returns the existing label.
    """
    init_journal(db_path)
    existing = get_existing_return(order_id, db_path=db_path)
    if existing:
        return existing

    # Clearly simulated label number (not a carrier tracking ID).
    suffix = abs(hash(order_id)) % 10_000_000
    label = f"SIM-LABEL-{suffix:07d}"
    created_at = datetime.now(timezone.utc).isoformat()

    with _lock:
        conn = _connect(db_path)
        try:
            try:
                conn.execute(
                    "INSERT INTO returns (order_id, label_number, created_at) VALUES (?, ?, ?)",
                    (order_id, label, created_at),
                )
                conn.commit()
                return label
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT label_number FROM returns WHERE order_id = ?",
                    (order_id,),
                ).fetchone()
                return str(row["label_number"])
        finally:
            conn.close()


def count_returns(db_path: Path | None = None) -> int:
    """Return the number of journal rows (for tests)."""
    init_journal(db_path)
    with _lock:
        conn = _connect(db_path)
        try:
            row = conn.execute("SELECT COUNT(*) AS n FROM returns").fetchone()
            return int(row["n"])
        finally:
            conn.close()
