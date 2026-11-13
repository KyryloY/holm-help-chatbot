"""Explicit LangGraph StateGraph for Holm Help (capable multi-turn assistant)."""

from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from holm_help.config import TICKETS_DB
from holm_help.decide import evaluate_return, format_eur_cents
from holm_help.exceptions import OrdersServiceUnavailable
from holm_help.guard import guard_message
from holm_help.model import get_chat_model
from holm_help.slots import (
    clarify_order_id_message,
    classify_intent_heuristic,
    extract_order_id,
    is_list_orders_request,
    needs_order_id,
)
from holm_help.state import SupportState
from holm_help.tickets import create_ticket
from holm_help.tools import (
    ASSISTANT_TOOLS,
    TOOLS_BY_NAME,
    create_return,
    list_demo_orders,
    lookup_order,
    read_return_policy,
)

ASSISTANT_SYSTEM = (
    "You are Holm Help, customer support for Holm Home Textiles (Hamburg). "
    "Use tools for order lookup, demo order lists, and return policy. "
    "Never invent order status. Never issue refunds. "
    "Demo orders are synthetic and anonymous — do not claim real ownership checks. "
    "For returns, once you know the order ID, signal readiness rather than creating labels yourself. "
    "For human handoff requests, signal handoff readiness."
)


def _append_visit(state: SupportState, node: str) -> list[str]:
    visited = list(state.get("visited_nodes") or [])
    visited.append(node)
    return visited


def _append_tool(state: SupportState, tool: str) -> list[str]:
    tools = list(state.get("tool_calls") or [])
    tools.append(tool)
    return tools


def _parse_intent_payload(content: Any) -> dict[str, Any] | None:
    if not isinstance(content, str):
        return None
    text = content.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


async def _classify_intent(model: Any, message: str) -> dict[str, Any]:
    prompt = [
        SystemMessage(
            content=(
                "You are an intent classifier for Holm Help. Reply with ONLY compact JSON: "
                '{"intent":"orders|policy|return|list_orders|smalltalk|handoff",'
                '"order_id":"H-####"|null}. '
                "Use list_orders when the user asks to list existing/demo orders. "
                "Use return when they want to return an item. "
                "Use orders for shipment/status. Use policy for policy questions. "
                "Use handoff for a human agent."
            )
        ),
        HumanMessage(content=f"Customer message:\n{message}\n\nIntent classification:"),
    ]
    try:
        result = await model.ainvoke(prompt)
        raw = result.content if hasattr(result, "content") else str(result)
        if isinstance(raw, list):
            raw = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block) for block in raw
            )
        text = str(raw).strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)
        intent = str(data.get("intent") or data.get("route") or "smalltalk").lower()
        if intent == "route":
            intent = "smalltalk"
        if intent not in {"orders", "policy", "return", "list_orders", "smalltalk", "handoff"}:
            intent = "smalltalk"
        order_id = data.get("order_id")
        order_id = extract_order_id(message, str(order_id) if order_id else None)
        return {"intent": intent, "order_id": order_id}
    except Exception:
        return classify_intent_heuristic(message)


def node_guard(state: SupportState) -> dict[str, Any]:
    """Runs before any tool call or model call. Resets per-turn visit lists."""
    result = guard_message(state["user_message"])
    sanitized = result["sanitized_message"]
    update: dict[str, Any] = {
        "sanitized_message": sanitized,
        "messages": [HumanMessage(content=sanitized)],
        "visited_nodes": ["guard"],
        "tool_calls": [],
        "card_masked": result.get("card_masked"),
        "blocked_reason": result.get("blocked_reason"),
        "pending_approval": False,
        "next_action": None,
        "reply": None,
        "label_number": None,
        "decision": None,
        "decision_reason": None,
        "approval_status": None,
        "error": None,
        "demo_orders_summary": None,
        "ticket_id": None,
    }
    if result["blocked"]:
        update["route"] = "blocked"
        update["reply"] = result["reply"]
        update["next_action"] = "blocked"
    return update


def route_after_guard(state: SupportState) -> Literal["blocked", "assistant"]:
    if state.get("route") == "blocked" or state.get("blocked_reason"):
        return "blocked"
    return "assistant"


async def node_assistant(state: SupportState, *, model: Any | None = None) -> dict[str, Any]:
    """Model + tool-calling turn, or slot / return / handoff routing."""
    model = model or get_chat_model()
    visited = _append_visit(state, "assistant")
    sanitized = state.get("sanitized_message") or state.get("user_message") or ""

    # Resume a pending slot fill from a previous turn (checkpointed).
    awaiting = state.get("awaiting_slot")
    last_intent = state.get("last_intent")
    filled_id = extract_order_id(sanitized, state.get("active_order_id") or state.get("order_id"))

    if awaiting == "order_id":
        if filled_id:
            intent = last_intent or "orders"
            update: dict[str, Any] = {
                "awaiting_slot": None,
                "active_order_id": filled_id,
                "order_id": filled_id,
                "last_intent": intent,
                "route": intent,
                "visited_nodes": visited,
            }
            if intent == "return":
                update["next_action"] = "prepare_return"
            elif intent == "orders":
                update["next_action"] = "lookup_status"
            else:
                update["next_action"] = "chat"
            return update
        # Still waiting — ask again.
        return {
            "route": "ask_slot",
            "next_action": "ask_slot",
            "reply": clarify_order_id_message(last_intent),
            "visited_nodes": visited,
        }

    # Deterministic short-circuit: never send list-orders through lookup_order.
    if is_list_orders_request(sanitized):
        try:
            listed = list_demo_orders()
            lines = [listed.get("disclaimer", "Synthetic demo orders:")]
            for item in listed.get("orders") or []:
                lines.append(
                    f"- {item.get('order_id')}: {item.get('product')} "
                    f"({item.get('amount')}), status={item.get('status')}"
                )
            reply = "\n".join(lines)
            return {
                "route": "list_orders",
                "last_intent": "list_orders",
                "demo_orders_summary": reply,
                "reply": reply,
                "tool_calls": _append_tool(state, "list_demo_orders"),
                "next_action": "answer",
                "awaiting_slot": None,
                "visited_nodes": visited,
            }
        except OrdersServiceUnavailable as exc:
            return {
                "route": "handoff",
                "last_intent": "list_orders",
                "error": "orders_unavailable",
                "decision": "service_unavailable",
                "decision_reason": str(exc),
                "tool_calls": _append_tool(state, "list_demo_orders"),
                "next_action": "handoff",
                "visited_nodes": visited,
            }

    classified = await _classify_intent(model, sanitized)
    intent = classified["intent"]
    order_id = classified.get("order_id") or filled_id

    # Prefer heuristic list_orders even if the model says "orders".
    if is_list_orders_request(sanitized):
        intent = "list_orders"

    if needs_order_id(intent, order_id):
        return {
            "route": "ask_slot",
            "last_intent": intent,
            "awaiting_slot": "order_id",
            "order_id": None,
            "active_order_id": None,
            "next_action": "ask_slot",
            "reply": clarify_order_id_message(intent),
            "visited_nodes": visited,
        }

    if intent == "return" and order_id:
        return {
            "route": "return",
            "last_intent": "return",
            "order_id": order_id,
            "active_order_id": order_id,
            "awaiting_slot": None,
            "next_action": "prepare_return",
            "visited_nodes": visited,
        }

    if intent == "handoff":
        return {
            "route": "handoff",
            "last_intent": "handoff",
            "next_action": "handoff",
            "visited_nodes": visited,
        }

    # Free chat / tools via bound model.
    bound = model.bind_tools(ASSISTANT_TOOLS)
    history = list(state.get("messages") or [])
    # Ensure system + latest context.
    prompt_messages = [SystemMessage(content=ASSISTANT_SYSTEM), *history]
    ai = await bound.ainvoke(prompt_messages)

    tool_calls = getattr(ai, "tool_calls", None) or []
    payload = _parse_intent_payload(ai.content)

    update = {
        "messages": [ai],
        "last_intent": intent,
        "order_id": order_id,
        "active_order_id": order_id or state.get("active_order_id"),
        "route": intent,
        "awaiting_slot": None,
        "visited_nodes": visited,
    }

    if payload and payload.get("ready_for_return") and (payload.get("order_id") or order_id):
        oid = extract_order_id("", payload.get("order_id")) or order_id
        update.update(
            {
                "order_id": oid,
                "active_order_id": oid,
                "route": "return",
                "next_action": "prepare_return",
            }
        )
        return update

    if payload and payload.get("ready_for_handoff"):
        update["next_action"] = "handoff"
        update["route"] = "handoff"
        return update

    if tool_calls:
        update["next_action"] = "tools"
        return update

    # Final natural-language reply from the model.
    content = ai.content
    if isinstance(content, list):
        content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block) for block in content
        )
    update["reply"] = str(content or "").strip() or (
        "How else can Holm Help assist you today?"
    )
    update["next_action"] = "answer"
    return update


def route_after_assistant(
    state: SupportState,
) -> Literal["ask_slot", "tools", "prepare_return", "handoff", "answer", "lookup_status"]:
    action = state.get("next_action") or "answer"
    if action == "ask_slot":
        return "ask_slot"
    if action == "tools":
        return "tools"
    if action == "prepare_return":
        return "prepare_return"
    if action == "lookup_status":
        return "lookup_status"
    if action == "handoff":
        return "handoff"
    return "answer"


def node_ask_slot(state: SupportState) -> dict[str, Any]:
    reply = state.get("reply") or clarify_order_id_message(state.get("last_intent"))
    return {
        "reply": reply,
        "visited_nodes": _append_visit(state, "ask_slot"),
        "messages": [AIMessage(content=reply)],
    }


def node_tools(state: SupportState) -> dict[str, Any]:
    """Execute assistant tool calls (never create_return)."""
    messages = list(state.get("messages") or [])
    last = messages[-1] if messages else None
    tool_calls = getattr(last, "tool_calls", None) or []
    outputs: list[ToolMessage] = []
    tools_used = list(state.get("tool_calls") or [])
    order = state.get("order")
    order_found = state.get("order_found")
    policy_text = state.get("policy_text")
    demo_summary = state.get("demo_orders_summary")
    error = state.get("error")
    order_id = state.get("order_id")

    for call in tool_calls:
        name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
        args = call.get("args") if isinstance(call, dict) else getattr(call, "args", {}) or {}
        call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", "")
        tool = TOOLS_BY_NAME.get(name or "")
        if tool is None:
            result_text = json.dumps({"error": f"Unknown tool: {name}"})
        else:
            try:
                result_text = tool.invoke(args)
            except Exception as exc:  # noqa: BLE001 — surface controlled tool failures
                result_text = json.dumps({"error": str(exc)})

        tools_used.append(name or "unknown")
        outputs.append(ToolMessage(content=str(result_text), tool_call_id=call_id or name or "tool"))

        try:
            parsed = json.loads(result_text) if isinstance(result_text, str) else result_text
        except json.JSONDecodeError:
            parsed = None

        if name == "lookup_order" and isinstance(parsed, dict):
            if parsed.get("error") == "orders_unavailable":
                error = "orders_unavailable"
                order_found = False
            elif parsed.get("found"):
                order = parsed.get("order")
                order_found = True
                order_id = (order or {}).get("order_id") or args.get("order_id")
            else:
                order = None
                order_found = False
                order_id = parsed.get("order_id") or args.get("order_id")
        elif name == "read_return_policy":
            policy_text = str(result_text)
        elif name == "list_demo_orders" and isinstance(parsed, dict):
            if parsed.get("error") == "orders_unavailable":
                error = "orders_unavailable"
            else:
                lines = [parsed.get("disclaimer", "")]
                for item in parsed.get("orders") or []:
                    lines.append(
                        f"- {item.get('order_id')}: {item.get('product')} "
                        f"({item.get('amount')}), status={item.get('status')}"
                    )
                demo_summary = "\n".join(lines)

    next_action = "handoff" if error == "orders_unavailable" else "assistant"
    return {
        "messages": outputs,
        "tool_calls": tools_used,
        "order": order,
        "order_found": order_found,
        "order_id": order_id,
        "active_order_id": order_id or state.get("active_order_id"),
        "policy_text": policy_text,
        "demo_orders_summary": demo_summary,
        "error": error,
        "next_action": next_action,
        "visited_nodes": _append_visit(state, "tools"),
    }


def route_after_tools(state: SupportState) -> Literal["assistant", "handoff"]:
    if state.get("error") == "orders_unavailable" or state.get("next_action") == "handoff":
        return "handoff"
    return "assistant"


def node_lookup_status(state: SupportState) -> dict[str, Any]:
    """Deterministic status lookup after a clarified order ID."""
    order_id = extract_order_id(
        state.get("sanitized_message", ""),
        state.get("order_id") or state.get("active_order_id"),
    )
    visited = _append_visit(state, "orders")
    tools = list(state.get("tool_calls") or [])
    if not order_id:
        return {
            "order_found": False,
            "decision": "unknown_order",
            "reply": clarify_order_id_message("orders"),
            "next_action": "ask_slot",
            "awaiting_slot": "order_id",
            "last_intent": "orders",
            "visited_nodes": visited,
        }
    try:
        result = lookup_order(order_id)
        tools.append("lookup_order")
        if not result.get("found"):
            reply = (
                f"I could not find order {order_id} in our demo records "
                f"(found: false). I will not invent a shipment status."
            )
            return {
                "order_id": order_id,
                "order": None,
                "order_found": False,
                "decision": "unknown_order",
                "reply": reply,
                "tool_calls": tools,
                "next_action": "answer",
                "visited_nodes": visited,
            }
        order = result["order"]
        amount = format_eur_cents(int(order["amount_eur_cents"]))
        reply = (
            f"Order {order_id} ({order.get('product')}, {amount}) "
            f"has status **{order.get('status')}**."
        )
        if order.get("shipped_date"):
            reply += f" Shipped on {order['shipped_date']}."
        if order.get("delivered_date"):
            reply += f" Delivered on {order['delivered_date']}."
        if order.get("status") == "in_transit":
            reply += " The shipment is still in transit."
        return {
            "order_id": order_id,
            "order": order,
            "order_found": True,
            "reply": reply,
            "tool_calls": tools,
            "route": "orders",
            "next_action": "answer",
            "visited_nodes": visited,
        }
    except OrdersServiceUnavailable as exc:
        tools.append("lookup_order")
        return {
            "order_id": order_id,
            "order_found": False,
            "decision": "service_unavailable",
            "error": "orders_unavailable",
            "decision_reason": str(exc),
            "tool_calls": tools,
            "next_action": "handoff",
            "visited_nodes": visited,
        }


def route_after_lookup_status(state: SupportState) -> Literal["answer", "handoff", "ask_slot"]:
    if state.get("next_action") == "handoff" or state.get("error") == "orders_unavailable":
        return "handoff"
    if state.get("next_action") == "ask_slot":
        return "ask_slot"
    return "answer"


def node_prepare_return(state: SupportState) -> dict[str, Any]:
    """Lookup order + policy before deterministic decide (return path)."""
    order_id = extract_order_id(
        state.get("sanitized_message", ""),
        state.get("order_id") or state.get("active_order_id"),
    )
    visited = _append_visit(state, "orders")
    tools = list(state.get("tool_calls") or [])

    if not order_id:
        return {
            "awaiting_slot": "order_id",
            "last_intent": "return",
            "next_action": "ask_slot",
            "reply": clarify_order_id_message("return"),
            "visited_nodes": visited,
        }

    try:
        result = lookup_order(order_id)
        tools.append("lookup_order")
    except OrdersServiceUnavailable as exc:
        tools.append("lookup_order")
        return {
            "order_id": order_id,
            "order_found": False,
            "decision": "service_unavailable",
            "error": "orders_unavailable",
            "decision_reason": str(exc),
            "tool_calls": tools,
            "next_action": "handoff",
            "visited_nodes": visited,
        }

    if not result.get("found"):
        return {
            "order_id": order_id,
            "order": None,
            "order_found": False,
            "decision": "unknown_order",
            "reply": (
                f"I could not find order {order_id} in our demo records "
                f"(found: false). I will not invent a shipment status."
            ),
            "tool_calls": tools,
            "next_action": "answer",
            "visited_nodes": visited,
        }

    policy = read_return_policy()
    tools.append("read_return_policy")
    visited = visited + ["policy"]
    return {
        "order_id": order_id,
        "active_order_id": order_id,
        "order": result["order"],
        "order_found": True,
        "policy_text": policy,
        "tool_calls": tools,
        "route": "return",
        "next_action": "decide",
        "visited_nodes": visited,
    }


def route_after_prepare_return(
    state: SupportState,
) -> Literal["decide", "answer", "handoff", "ask_slot"]:
    action = state.get("next_action")
    if action == "handoff":
        return "handoff"
    if action == "ask_slot":
        return "ask_slot"
    if action == "decide":
        return "decide"
    return "answer"


def node_decide(state: SupportState) -> dict[str, Any]:
    decision, reason = evaluate_return(
        state.get("order"),
        found=bool(state.get("order_found")),
    )
    return {
        "decision": decision,
        "decision_reason": reason,
        "visited_nodes": _append_visit(state, "decide"),
    }


def route_after_decide(
    state: SupportState,
) -> Literal["answer", "approval", "create_return", "handoff"]:
    decision = state.get("decision")
    if decision in {"eligible", "already_returned"}:
        return "create_return"
    if decision == "needs_approval":
        return "approval"
    if decision == "service_unavailable":
        return "handoff"
    return "answer"


def node_approval(state: SupportState) -> dict[str, Any]:
    order = state.get("order") or {}
    payload = {
        "type": "staff_approval_simulation",
        "order_id": state.get("order_id"),
        "product": order.get("product"),
        "amount": format_eur_cents(int(order.get("amount_eur_cents", 0))),
        "message": (
            "This return is over EUR 150 and requires simulated staff approval "
            "before a simulated return label is created. "
            "This is a demo staff decision — not a customer self-approval."
        ),
    }
    decision = interrupt(payload)
    if isinstance(decision, dict):
        status = str(decision.get("decision", "rejected")).lower()
    else:
        status = str(decision).lower()
    if status not in {"approved", "rejected"}:
        status = "rejected"
    return {
        "approval_status": status,
        "pending_approval": False,
        "visited_nodes": _append_visit(state, "approval"),
    }


def route_after_approval(state: SupportState) -> Literal["answer", "create_return"]:
    if state.get("approval_status") == "approved":
        return "create_return"
    return "answer"


def node_create_return(state: SupportState) -> dict[str, Any]:
    order_id = state.get("order_id") or state.get("active_order_id")
    if not order_id:
        return {
            "visited_nodes": _append_visit(state, "create_return"),
            "decision_reason": "Missing order ID; cannot create a return.",
            "label_number": None,
        }

    decision = state.get("decision")
    approval = state.get("approval_status")
    if decision == "needs_approval" and approval != "approved":
        return {
            "visited_nodes": _append_visit(state, "create_return"),
            "label_number": None,
            "decision_reason": "Simulated staff approval is required before creating a return label.",
        }
    if decision not in {"eligible", "needs_approval", "already_returned"}:
        return {
            "visited_nodes": _append_visit(state, "create_return"),
            "label_number": None,
        }

    result = create_return(order_id)
    return {
        "label_number": result["label_number"],
        "visited_nodes": _append_visit(state, "create_return"),
        "tool_calls": _append_tool(state, "create_return"),
        "decision": "eligible" if decision != "already_returned" else decision,
    }


def node_blocked(state: SupportState) -> dict[str, Any]:
    reply = state.get("reply") or (
        "I cannot help with that request. Please ask about an order or our return policy."
    )
    return {
        "reply": reply,
        "visited_nodes": _append_visit(state, "blocked"),
        "messages": [AIMessage(content=reply)],
    }


def node_handoff(state: SupportState) -> dict[str, Any]:
    thread_id = state.get("thread_id") or "local-demo"
    summary = state.get("sanitized_message") or state.get("user_message") or "Handoff requested"
    order_id = state.get("order_id") or state.get("active_order_id")

    if state.get("error") == "orders_unavailable" or state.get("decision") == "service_unavailable":
        summary = f"Order service unavailable. Original request: {summary}"

    ticket = create_ticket(
        thread_id=str(thread_id),
        summary=str(summary)[:500],
        order_id=order_id,
        db_path=TICKETS_DB,
    )
    if state.get("error") == "orders_unavailable":
        reply = (
            "Order information is temporarily unavailable. "
            "I cannot look up shipment status or create a return right now. "
            f"I opened simulated support ticket **{ticket['id']}** for handoff. "
            "This is a local simulation — no real agent queue is notified."
        )
    else:
        reply = (
            f"I opened simulated support ticket **{ticket['id']}** for a human handoff. "
            "This is a local demo queue only — no real staff notification is sent. "
            "Please keep your order ID handy if you have one."
        )
    return {
        "ticket_id": ticket["id"],
        "reply": reply,
        "visited_nodes": _append_visit(state, "handoff"),
        "messages": [AIMessage(content=reply)],
    }


async def node_answer(state: SupportState, *, model: Any | None = None) -> dict[str, Any]:
    visited = _append_visit(state, "answer")

    if state.get("reply"):
        return {"reply": state["reply"], "visited_nodes": visited}

    order = state.get("order")
    order_id = state.get("order_id")
    decision = state.get("decision")
    reason = state.get("decision_reason") or ""
    label = state.get("label_number")
    approval = state.get("approval_status")
    route = state.get("route")

    if state.get("demo_orders_summary"):
        reply = state["demo_orders_summary"]
    elif decision == "unknown_order":
        reply = (
            f"I could not find order {order_id or 'with that ID'} in our demo records "
            f"(found: false). I will not invent a shipment status. "
            f"Please check the ID and try again, or ask for a handoff."
        )
    elif route == "orders" and order:
        status = order.get("status")
        product = order.get("product")
        amount = format_eur_cents(int(order["amount_eur_cents"]))
        reply = f"Order {order_id} ({product}, {amount}) has status **{status}**."
        if order.get("shipped_date"):
            reply += f" Shipped on {order['shipped_date']}."
        if order.get("delivered_date"):
            reply += f" Delivered on {order['delivered_date']}."
        if status == "in_transit":
            reply += " The shipment is still in transit."
    elif route == "policy" and state.get("policy_text"):
        reply = (
            "Here is a summary of our return policy: returns are accepted through the "
            "14th calendar day after delivery (inclusive). Returns over EUR 150 require "
            "simulated staff approval before a simulated label is created. "
            "Holm Help does not issue refunds."
        )
    elif label:
        reply = (
            f"Your return request for order {order_id} is approved for label creation. "
            f"Simulated return label: **{label}**. "
            f"This is a simulation only — no real shipping label or refund is issued. "
            f"Status: return approved (not refund issued)."
        )
    elif approval == "rejected":
        reply = (
            f"Simulated staff review declined the return for order {order_id}. "
            f"No return label was created and no refund was issued. {reason}"
        )
    elif decision == "window_closed":
        delivered = (order or {}).get("delivered_date")
        reply = (
            f"I cannot create a return for order {order_id}. "
            f"Delivery date: {delivered}. {reason} No return label was created."
        )
    elif decision == "not_delivered":
        reply = f"I cannot create a return for order {order_id}. {reason}"
    elif decision == "already_returned" and not label:
        reply = reason
    elif decision == "needs_approval" and not approval:
        reply = reason
    else:
        reply = reason or "How else can Holm Help assist you today?"

    model = model or get_chat_model()
    try:
        polished = await model.ainvoke(
            [
                SystemMessage(
                    content=(
                        "Write a short customer-support reply for Holm Help. "
                        "Keep all facts exactly as given. Do not invent order data, "
                        "refunds, or labels. Professional English. 2-5 sentences."
                    )
                ),
                HumanMessage(content=f"Facts to convey:\n{reply}"),
            ]
        )
        content = polished.content if hasattr(polished, "content") else str(polished)
        if isinstance(content, str) and content.strip():
            if "fake-model" in content.lower() or "summarized the outcome" in content.lower():
                pass
            else:
                reply = content.strip()
    except Exception:
        pass

    return {
        "reply": reply,
        "visited_nodes": visited,
        "messages": [AIMessage(content=reply)],
    }


def build_graph(
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    model: Any | None = None,
):
    """Compile the Holm Help StateGraph with visible node names."""

    async def assistant_node(state: SupportState) -> dict[str, Any]:
        return await node_assistant(state, model=model)

    async def answer_node(state: SupportState) -> dict[str, Any]:
        return await node_answer(state, model=model)

    builder = StateGraph(SupportState)

    builder.add_node("guard", node_guard)
    builder.add_node("assistant", assistant_node)
    builder.add_node("ask_slot", node_ask_slot)
    builder.add_node("tools", node_tools)
    builder.add_node("lookup_status", node_lookup_status)
    builder.add_node("prepare_return", node_prepare_return)
    builder.add_node("decide", node_decide)
    builder.add_node("approval", node_approval)
    builder.add_node("create_return", node_create_return)
    builder.add_node("blocked", node_blocked)
    builder.add_node("handoff", node_handoff)
    builder.add_node("answer", answer_node)

    builder.add_edge(START, "guard")
    builder.add_conditional_edges(
        "guard", route_after_guard, {"blocked": "blocked", "assistant": "assistant"}
    )
    builder.add_conditional_edges(
        "assistant",
        route_after_assistant,
        {
            "ask_slot": "ask_slot",
            "tools": "tools",
            "prepare_return": "prepare_return",
            "lookup_status": "lookup_status",
            "handoff": "handoff",
            "answer": "answer",
        },
    )
    builder.add_conditional_edges(
        "tools", route_after_tools, {"assistant": "assistant", "handoff": "handoff"}
    )
    builder.add_conditional_edges(
        "lookup_status",
        route_after_lookup_status,
        {"answer": "answer", "handoff": "handoff", "ask_slot": "ask_slot"},
    )
    builder.add_conditional_edges(
        "prepare_return",
        route_after_prepare_return,
        {
            "decide": "decide",
            "answer": "answer",
            "handoff": "handoff",
            "ask_slot": "ask_slot",
        },
    )
    builder.add_conditional_edges(
        "decide",
        route_after_decide,
        {
            "answer": "answer",
            "approval": "approval",
            "create_return": "create_return",
            "handoff": "handoff",
        },
    )
    builder.add_conditional_edges(
        "approval",
        route_after_approval,
        {"answer": "answer", "create_return": "create_return"},
    )
    builder.add_edge("create_return", "answer")
    builder.add_edge("ask_slot", END)
    builder.add_edge("blocked", END)
    builder.add_edge("handoff", END)
    builder.add_edge("answer", END)

    return builder.compile(checkpointer=checkpointer)


def initial_state(user_message: str, *, thread_id: str | None = None) -> SupportState:
    return {
        "user_message": user_message,
        "sanitized_message": user_message,
        "messages": [],
        "visited_nodes": [],
        "tool_calls": [],
        "pending_approval": False,
        "thread_id": thread_id,
    }


__all__ = [
    "Command",
    "build_graph",
    "initial_state",
]
