"""Deterministic return eligibility — model is never the authority."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from holm_help.config import RETURN_APPROVAL_CENTS, get_demo_today
from holm_help.journal import get_existing_return
from holm_help.state import DecisionCode


def days_since_delivery(delivered: date, today: date | None = None) -> int:
    """Calendar days elapsed since delivery (delivery day = 0)."""
    today = today or get_demo_today()
    return (today - delivered).days


def is_within_return_window(delivered: date, today: date | None = None) -> bool:
    """
    Returns are accepted through the 14th calendar day after delivery, inclusive.

    Inclusive window: delivered + 14 days is still eligible.
    Example: delivered 2026-09-24, today 2026-10-08 → 14 days → eligible.
    """
    today = today or get_demo_today()
    last_day = delivered + timedelta(days=14)
    return today <= last_day


def format_eur_cents(cents: int) -> str:
    euros = cents // 100
    rem = cents % 100
    return f"EUR {euros}.{rem:02d}"


def evaluate_return(
    order: dict[str, Any] | None,
    *,
    found: bool,
    today: date | None = None,
    journal_db=None,
) -> tuple[DecisionCode, str]:
    """
    Decide return eligibility without using the model.

    Returns (decision_code, human-readable reason).
    """
    today = today or get_demo_today()

    if not found or order is None:
        return "unknown_order", "No matching order was found for that ID."

    order_id = str(order["order_id"])
    existing = get_existing_return(order_id, db_path=journal_db)
    if existing:
        return (
            "already_returned",
            f"A simulated return label already exists for {order_id}: {existing}.",
        )

    status = order.get("status")
    if status != "delivered" or not order.get("delivered_date"):
        if status == "in_transit":
            return (
                "not_delivered",
                "This order is still in transit and has not been delivered yet, so a return label cannot be created.",
            )
        if status == "payment_failed":
            return (
                "not_delivered",
                "Payment for this order failed and it was never shipped, so a return label cannot be created.",
            )
        return (
            "not_delivered",
            "This order is not in a delivered state, so a return label cannot be created.",
        )

    delivered = date.fromisoformat(order["delivered_date"])
    if not is_within_return_window(delivered, today=today):
        last_day = delivered + timedelta(days=14)
        return (
            "window_closed",
            (
                f"Delivered on {delivered.isoformat()}. "
                f"The return window closed after {last_day.isoformat()} "
                f"(14 calendar days after delivery, inclusive)."
            ),
        )

    amount = int(order["amount_eur_cents"])
    if amount > RETURN_APPROVAL_CENTS:
        return (
            "needs_approval",
            (
                f"Order total {format_eur_cents(amount)} is over EUR 150, "
                "so simulated staff approval is required before a simulated label is created."
            ),
        )

    return (
        "eligible",
        (
            f"Order {order_id} is within the 14-day return window "
            f"(delivered {delivered.isoformat()}) and does not require staff approval."
        ),
    )
