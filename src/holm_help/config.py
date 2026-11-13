"""Application configuration for Holm Help."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Ensure LangChain Google GenAI can authenticate when only GEMINI_API_KEY is set.
if not os.getenv("GOOGLE_API_KEY") and os.getenv("GEMINI_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
ORDERS_PATH = DATA_DIR / "orders.json"
POLICY_PATH = DATA_DIR / "policy.md"

# Amounts above this threshold (EUR) require simulated staff approval.
RETURN_APPROVAL_EUR = 150
RETURN_APPROVAL_CENTS = RETURN_APPROVAL_EUR * 100

# Fixed demo clock for reproducible scenarios and screenshots.
_DEFAULT_DEMO_TODAY = date.fromisoformat(os.getenv("DEMO_TODAY", "2026-10-08"))
_demo_today_override: date | None = None


def get_demo_today() -> date:
    """Return the active demo calendar date (injectable for tests)."""
    if _demo_today_override is not None:
        return _demo_today_override
    return _DEFAULT_DEMO_TODAY


def set_demo_today(value: date | None) -> None:
    """Override DEMO_TODAY for tests. Pass None to restore the default."""
    global _demo_today_override
    _demo_today_override = value


MODEL = os.getenv("MODEL", "google_genai:gemini-3.7-flash")
ORDERS_MODE = os.getenv("ORDERS_MODE", "orders").strip().lower()
CHECKPOINT_DB = Path(os.getenv("CHECKPOINT_DB", str(DATA_DIR / "checkpoints.db")))
JOURNAL_DB = Path(os.getenv("JOURNAL_DB", str(DATA_DIR / "returns_journal.db")))
TICKETS_DB = Path(os.getenv("TICKETS_DB", str(DATA_DIR / "tickets.db")))
CHAINLIT_DB = Path(os.getenv("CHAINLIT_DB", str(DATA_DIR / "chainlit.db")))

BOT_NAME = "Holm Help"
STORE_NAME = "Holm Home Textiles"
