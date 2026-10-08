"""Deterministic fake chat model for automated tests (no API key / network)."""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def _extract_text(messages: list[BaseMessage]) -> str:
    parts: list[str] = []
    for msg in messages:
        content = msg.content
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                else:
                    parts.append(str(block))
    return "\n".join(parts)


def classify_intent_heuristic(text: str) -> dict[str, Any]:
    """Rule-based intent used by the fake model and as a safe fallback."""
    lower = text.lower()
    order_match = re.search(r"\bH-\d{4}\b", text, re.I)
    order_id = order_match.group(0).upper() if order_match else None

    if any(w in lower for w in ("handoff", "human agent", "speak to a person", "real person")):
        return {"route": "handoff", "order_id": order_id}

    if any(w in lower for w in ("return", "send back", "take back")):
        return {"route": "return", "order_id": order_id}

    if any(w in lower for w in ("policy", "how long", "return window", "refund policy")):
        return {"route": "policy", "order_id": order_id}

    if order_id or any(w in lower for w in ("where is", "status", "track", "shipment", "order")):
        return {"route": "orders", "order_id": order_id}

    if any(w in lower for w in ("hello", "hi ", "thanks", "thank you", "good morning")):
        return {"route": "smalltalk", "order_id": None}

    return {"route": "smalltalk", "order_id": order_id}


class FakeHolmModel(BaseChatModel):
    """Minimal chat model that returns JSON intents or canned replies."""

    @property
    def _llm_type(self) -> str:
        return "fake-holm"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = _extract_text(messages)
        lower = text.lower()

        if "classify the customer message" in lower or "intent classification" in lower:
            # User message is usually last.
            user = ""
            for msg in reversed(messages):
                if msg.type == "human":
                    user = str(msg.content)
                    break
            if not user:
                user = text
            payload = classify_intent_heuristic(user)
            content = json.dumps(payload)
        elif "write a short customer-support reply" in lower:
            content = (
                "Thank you for contacting Holm Help. "
                "I have reviewed your request and summarized the outcome above."
            )
        else:
            content = "Holm Help fake-model response."

        message = AIMessage(content=content)
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
