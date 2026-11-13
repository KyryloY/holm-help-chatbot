"""Deterministic fake chat model for automated tests (no API key / network)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from holm_help.slots import classify_intent_heuristic, extract_order_id, is_list_orders_request


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


def _last_human(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage) or getattr(msg, "type", None) == "human":
            return str(msg.content)
    return _extract_text(messages)


def _has_tool_results(messages: list[BaseMessage]) -> bool:
    return any(isinstance(m, ToolMessage) or getattr(m, "type", None) == "tool" for m in messages)


class FakeHolmModel(BaseChatModel):
    """Minimal chat model that returns JSON intents, tool calls, or canned replies."""

    @property
    def _llm_type(self) -> str:
        return "fake-holm"

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> FakeHolmModel:
        # Tools are chosen heuristically; binding is a no-op for the fake model.
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = _extract_text(messages)
        lower = text.lower()
        user = _last_human(messages)

        if "classify the customer message" in lower or "intent classification" in lower:
            payload = classify_intent_heuristic(user)
            # Keep legacy "route" key for older prompts.
            payload = {"route": payload["intent"], "intent": payload["intent"], "order_id": payload.get("order_id")}
            content = json.dumps(payload)
            message = AIMessage(content=content)
            return ChatResult(generations=[ChatGeneration(message=message)])

        if "write a short customer-support reply" in lower:
            content = (
                "Thank you for contacting Holm Help. "
                "I have reviewed your request and summarized the outcome above."
            )
            message = AIMessage(content=content)
            return ChatResult(generations=[ChatGeneration(message=message)])

        # Assistant-loop behaviour.
        if _has_tool_results(messages):
            # Produce a final reply from tool results already in the transcript.
            tool_blobs = []
            for msg in messages:
                if isinstance(msg, ToolMessage) or getattr(msg, "type", None) == "tool":
                    tool_blobs.append(str(msg.content))
            joined = "\n".join(tool_blobs)
            if "demo_only" in joined or '"orders"' in joined:
                content = (
                    "Here are the synthetic demo orders available in this portfolio app. "
                    "This is not a real customer list — anonymous demo data only. "
                    f"Details: {joined[:800]}"
                )
            elif '"found": true' in joined or '"found":true' in joined:
                content = f"Here is the order information I found: {joined[:800]}"
            elif '"found": false' in joined or '"found":false' in joined:
                content = (
                    "No matching order was found for that ID (found: false). "
                    "I will not invent a shipment status."
                )
            elif "14th calendar day" in joined or "Return Policy" in joined:
                content = (
                    "Returns are accepted through the 14th calendar day after delivery "
                    "(inclusive). Returns over EUR 150 need simulated staff approval. "
                    "Holm Help does not issue refunds."
                )
            elif "orders_unavailable" in joined:
                content = "Order information is temporarily unavailable."
            else:
                content = "I have reviewed the tool results for your request."
            message = AIMessage(content=content)
            return ChatResult(generations=[ChatGeneration(message=message)])

        intent = classify_intent_heuristic(user)
        order_id = intent.get("order_id") or extract_order_id(user)

        if intent["intent"] == "list_orders" or is_list_orders_request(user):
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "list_demo_orders",
                        "args": {},
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                        "type": "tool_call",
                    }
                ],
            )
            return ChatResult(generations=[ChatGeneration(message=message)])

        if intent["intent"] == "policy":
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_return_policy",
                        "args": {},
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                        "type": "tool_call",
                    }
                ],
            )
            return ChatResult(generations=[ChatGeneration(message=message)])

        if intent["intent"] == "orders" and order_id:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "lookup_order",
                        "args": {"order_id": order_id},
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                        "type": "tool_call",
                    }
                ],
            )
            return ChatResult(generations=[ChatGeneration(message=message)])

        if intent["intent"] == "return":
            # Return path is handled by graph routing once slots are ready.
            content = json.dumps({"intent": "return", "order_id": order_id, "ready_for_return": True})
            message = AIMessage(content=content)
            return ChatResult(generations=[ChatGeneration(message=message)])

        if intent["intent"] == "handoff":
            content = json.dumps({"intent": "handoff", "ready_for_handoff": True})
            message = AIMessage(content=content)
            return ChatResult(generations=[ChatGeneration(message=message)])

        if intent["intent"] == "smalltalk":
            content = (
                "Hello! I am Holm Help, the support assistant for Holm Home Textiles. "
                "I can list demo orders, check a status by order ID, explain the return "
                "policy, start a simulated return, or create a simulated handoff ticket."
            )
            message = AIMessage(content=content)
            return ChatResult(generations=[ChatGeneration(message=message)])

        message = AIMessage(content="Holm Help fake-model response.")
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
