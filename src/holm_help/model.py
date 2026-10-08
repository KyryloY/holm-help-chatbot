"""Chat model factory for Holm Help."""

from __future__ import annotations

import os
from typing import Any

from langchain.chat_models import init_chat_model

from holm_help.config import MODEL
from holm_help.fake_model import FakeHolmModel


def get_chat_model(*, use_fake: bool | None = None) -> Any:
    """
    Initialize the chat model from MODEL, or a fake model for tests.

    Set HOLM_FAKE_MODEL=1 or pass use_fake=True to avoid network/API use.
    """
    if use_fake is None:
        use_fake = os.getenv("HOLM_FAKE_MODEL", "").strip() in {"1", "true", "yes"}

    if use_fake or MODEL.strip().lower() in {"fake", "test", "holm_fake"}:
        return FakeHolmModel()

    # Prefer GOOGLE_API_KEY; config.py may have copied GEMINI_API_KEY.
    return init_chat_model(MODEL)
