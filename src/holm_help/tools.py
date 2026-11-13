"""Tools for Holm Help (create_return is gated — not bound to the free tool loop)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from holm_help.config import JOURNAL_DB, ORDERS_PATH, POLICY_PATH
from holm_help.decide import format_eur_cents
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


def list_demo_orders(orders_path: Path | None = None) -> dict[str, Any]:
    """
    List synthetic demo orders (ID, product, status, amount).

    This is not a real customer order book — anonymous demo data only.
    """
    mode = os.getenv("ORDERS_MODE", "orders").strip().lower()
    if mode == "down":
        raise OrdersServiceUnavailable()

    path = orders_path or ORDERS_PATH
    with path.open(encoding="utf-8") as fh:
        orders = json.load(fh)

    summaries = []
    for order in orders:
        summaries.append(
            {
                "order_id": order["order_id"],
                "product": order["product"],
                "status": order["status"],
                "amount": format_eur_cents(int(order["amount_eur_cents"])),
                "delivered_date": order.get("delivered_date"),
                "shipped_date": order.get("shipped_date"),
            }
        )
    return {
        "demo_only": True,
        "disclaimer": (
            "Synthetic demo orders for Holm Help. Anonymous access — "
            "order ownership is not verified."
        ),
        "orders": summaries,
    }


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


@tool("lookup_order")
def lookup_order_tool(order_id: str) -> str:
    """Look up a synthetic Holm Home Textiles order by ID (for example H-1042)."""
    try:
        result = lookup_order(order_id.upper())
    except OrdersServiceUnavailable as exc:
        return json.dumps({"error": "orders_unavailable", "message": str(exc)})
    return json.dumps(result, default=str)


@tool("read_return_policy")
def read_return_policy_tool() -> str:
    """Read the full Holm Home Textiles return policy (demo Markdown)."""
    return read_return_policy()


@tool("list_demo_orders")
def list_demo_orders_tool() -> str:
    """List synthetic demo order IDs available in this portfolio demo (not a real customer list)."""
    try:
        result = list_demo_orders()
    except OrdersServiceUnavailable as exc:
        return json.dumps({"error": "orders_unavailable", "message": str(exc)})
    return json.dumps(result, default=str)


ASSISTANT_TOOLS = [lookup_order_tool, read_return_policy_tool, list_demo_orders_tool]
TOOLS_BY_NAME = {t.name: t for t in ASSISTANT_TOOLS}
