"""Tests for deterministic return eligibility."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from holm_help.config import RETURN_APPROVAL_CENTS, RETURN_APPROVAL_EUR
from holm_help.decide import evaluate_return, is_within_return_window
from holm_help.journal import create_return_entry, init_journal


def test_return_approval_threshold_is_150_eur():
    assert RETURN_APPROVAL_EUR == 150
    assert RETURN_APPROVAL_CENTS == 15000


def test_14_day_boundary_inclusive():
    delivered = date(2026, 9, 24)
    assert is_within_return_window(delivered, today=date(2026, 10, 8)) is True
    assert is_within_return_window(delivered, today=date(2026, 10, 9)) is False


def test_eligible_under_threshold(tmp_path: Path):
    db = tmp_path / "empty.db"
    order = {
        "order_id": "H-1048",
        "status": "delivered",
        "delivered_date": "2026-10-06",
        "amount_eur_cents": 12900,
    }
    code, _ = evaluate_return(order, found=True, today=date(2026, 10, 8), journal_db=db)
    assert code == "eligible"


def test_needs_approval_over_threshold(tmp_path: Path):
    db = tmp_path / "empty.db"
    order = {
        "order_id": "H-1107",
        "status": "delivered",
        "delivered_date": "2026-10-03",
        "amount_eur_cents": 89000,
    }
    code, reason = evaluate_return(
        order, found=True, today=date(2026, 10, 8), journal_db=db
    )
    assert code == "needs_approval"
    assert "150" in reason


def test_window_closed(tmp_path: Path):
    db = tmp_path / "empty.db"
    order = {
        "order_id": "H-0991",
        "status": "delivered",
        "delivered_date": "2026-08-29",
        "amount_eur_cents": 21000,
    }
    code, reason = evaluate_return(
        order, found=True, today=date(2026, 10, 8), journal_db=db
    )
    assert code == "window_closed"
    assert "2026-08-29" in reason


def test_unknown_order():
    code, _ = evaluate_return(None, found=False)
    assert code == "unknown_order"


def test_already_returned(tmp_path: Path):
    db = tmp_path / "j.db"
    init_journal(db)
    create_return_entry("H-1048", db_path=db)
    order = {
        "order_id": "H-1048",
        "status": "delivered",
        "delivered_date": "2026-10-06",
        "amount_eur_cents": 12900,
    }
    code, reason = evaluate_return(order, found=True, journal_db=db)
    assert code == "already_returned"
    assert "SIM-LABEL" in reason
