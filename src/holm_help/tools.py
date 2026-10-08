"""Exactly three tools for Holm Help."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from holm_help.config import JOURNAL_DB, ORDERS_PATH, POLICY_PATH
from holm_help.exceptions import OrdersServiceUnavailable
from holm_help.journal import create_return_entry, get_existing_return, init_journal


def lookup_order(order_id: str, orders_path: Path | None = None) -> dict[str, Any]:
    """
    Look up a synthetic order by ID.

    Returns {"found": False, "order_id": ...} for unknown IDs.
    Never invents status or substitutes a nearby order.
    """
    mode = os.getenv("ORDERS_MODE", "orders").strip().lower()
    if mode == "down":
        raise OrdersServiceUnavailable()

    path = orders_path or ORDERS_PATH
    with path.open(encoding="utf-8") as fh:
        orders = json.load(fh)

    for order in orders:
        if order.get("order_id") == order_id:
            return {"found": True, "order": order}

    return {"found": False, "order_id": order_id}


def read_return_policy(policy_path: Path | None = None) -> str:
    """Return the complete contents of the return policy Markdown file."""
    path = policy_path or POLICY_PATH
    return path.read_text(encoding="utf-8")


def create_return(order_id: str, journal_db: Path | None = None) -> dict[str, Any]:
    """
    Write one idempotent simulated return journal entry.

    Returns a clearly simulated label number. Callers must enforce eligibility
    and approval before invoking this tool.
    """
    db = journal_db or JOURNAL_DB
    init_journal(db)
    existing = get_existing_return(order_id, db_path=db)
    label = create_return_entry(order_id, db_path=db)
    return {
        "order_id": order_id,
        "label_number": label,
        "simulated": True,
        "idempotent_hit": existing is not None,
    }
