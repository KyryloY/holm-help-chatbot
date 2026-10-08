"""Explicit LangGraph StateGraph for Holm Help."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from holm_help.decide import evaluate_return, format_eur_cents
from holm_help.exceptions import OrdersServiceUnavailable
from holm_help.fake_model import classify_intent_heuristic
from holm_help.guard import guard_message
from holm_help.model import get_chat_model
from holm_help.state import SupportState
from holm_help.tools import create_return, lookup_order, read_return_policy

ORDER_ID_RE = re.compile(r"\bH-\d{4}\b", re.I)


def _append_visit(state: SupportState, node: str) -> list[str]:
    visited = list(state.get("visited_nodes") or [])
    visited.append(node)
    return visited


def _append_tool(state: SupportState, tool: str) -> list[str]:
    tools = list(state.get("tool_calls") or [])
    tools.append(tool)
    return tools


def _extract_order_id(text: str, hint: str | None = None) -> str | None:
    if hint:
        return hint.upper()
    match = ORDER_ID_RE.search(text or "")
    return match.group(0).upper() if match else None


async def _classify_route(model: Any, message: str) -> dict[str, Any]:
    """Use the model for intent classification; fall back to heuristics."""
    prompt = [
        SystemMessage(
            content=(
                "You are an intent classifier for Holm Help customer support. "
                "Classify the customer message. Reply with ONLY compact JSON: "
                '{"route":"orders|policy|return|smalltalk|handoff","order_id":"H-####"|null}. '
                "Use route=return when the customer wants to return an item. "
                "Use route=orders for shipment/status questions. "
                "Use route=policy for return-policy questions without a specific return request. "
                "Use route=handoff when they ask for a human. Otherwise smalltalk."
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
        # Tolerate fenced JSON.
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)
        route = str(data.get("route", "smalltalk")).lower()
        if route not in {"orders", "policy", "return", "smalltalk", "handoff"}:
            route = "smalltalk"
        order_id = data.get("order_id")
        if order_id:
            order_id = str(order_id).upper()
        else:
            order_id = _extract_order_id(message)
        return {"route": route, "order_id": order_id}
    except Exception:
        return classify_intent_heuristic(message)


def node_guard(state: SupportState) -> dict[str, Any]:
    """Runs before any tool call or model call."""
    result = guard_message(state["user_message"])
    update: dict[str, Any] = {
        "sanitized_message": result["sanitized_message"],
        "visited_nodes": _append_visit(state, "guard"),
        "tool_calls": list(state.get("tool_calls") or []),
        "card_masked": result.get("card_masked"),
        "blocked_reason": result.get("blocked_reason"),
        "pending_approval": False,
    }
    if result["blocked"]:
        update["route"] = "blocked"
        update["reply"] = result["reply"]
    return update


def route_after_guard(state: SupportState) -> Literal["blocked", "route"]:
    if state.get("route") == "blocked" or state.get("blocked_reason"):
        return "blocked"
    return "route"


async def node_route(state: SupportState, *, model: Any | None = None) -> dict[str, Any]:
    model = model or get_chat_model()
    classified = await _classify_route(model, state["sanitized_message"])
    return {
        "route": classified["route"],
        "order_id": classified.get("order_id"),
        "visited_nodes": _append_visit(state, "route"),
    }


def route_after_route(state: SupportState) -> Literal["orders", "policy", "smalltalk", "handoff"]:
    route = state.get("route")
    if route == "return":
        # Return requests must pass through orders (lookup) then policy then decide.
        return "orders"
    if route in {"orders", "policy", "smalltalk", "handoff"}:
        return route  # type: ignore[return-value]
    return "smalltalk"


def node_orders(state: SupportState) -> dict[str, Any]:
    order_id = _extract_order_id(state.get("sanitized_message", ""), state.get("order_id"))
    visited = _append_visit(state, "orders")
    tools = list(state.get("tool_calls") or [])

    if not order_id:
        return {
            "order_id": None,
            "order": None,
            "order_found": False,
            "decision": "unknown_order",
            "decision_reason": "I could not find an order ID in your message. Please include an ID like H-1042.",
            "visited_nodes": visited,
            "tool_calls": tools,
            "error": None,
        }

    try:
        result = lookup_order(order_id)
        tools = _append_tool({**state, "tool_calls": tools}, "lookup_order")
        if not result.get("found"):
            return {
                "order_id": order_id,
                "order": None,
                "order_found": False,
                "decision": "unknown_order",
                "decision_reason": f"No order was found for {order_id}.",
                "visited_nodes": visited,
                "tool_calls": tools,
                "error": None,
            }
        return {
            "order_id": order_id,
            "order": result["order"],
            "order_found": True,
            "visited_nodes": visited,
            "tool_calls": tools,
            "error": None,
        }
    except OrdersServiceUnavailable as exc:
        tools = _append_tool({**state, "tool_calls": tools}, "lookup_order")
        return {
            "order_id": order_id,
            "order": None,
            "order_found": False,
            "decision": "service_unavailable",
            "decision_reason": str(exc),
            "error": "orders_unavailable",
            "visited_nodes": visited,
            "tool_calls": tools,
        }


def route_after_orders(state: SupportState) -> Literal["answer", "policy", "handoff"]:
    if state.get("error") == "orders_unavailable" or state.get("decision") == "service_unavailable":
        return "handoff"
    # Status-only path: route was orders (not return) → answer.
    if state.get("route") == "return":
        return "policy"
    return "answer"


def node_policy(state: SupportState) -> dict[str, Any]:
    text = read_return_policy()
    return {
        "policy_text": text,
        "visited_nodes": _append_visit(state, "policy"),
        "tool_calls": _append_tool(state, "read_return_policy"),
    }


def route_after_policy(state: SupportState) -> Literal["answer", "decide"]:
    if state.get("route") == "return":
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
        # already_returned still enters create_return for an idempotent label echo.
        return "create_return"
    if decision == "needs_approval":
        return "approval"
    if decision == "service_unavailable":
        return "handoff"
    return "answer"


def node_approval(state: SupportState) -> dict[str, Any]:
    """Human-in-the-loop pause via langgraph.types.interrupt (not a UI-only if)."""
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
    # Pause here. Resume value must be {"decision": "approved"|"rejected"}.
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
    """Visible write node — only after decide (and approval when required)."""
    order_id = state.get("order_id")
    if not order_id:
        return {
            "visited_nodes": _append_visit(state, "create_return"),
            "decision_reason": "Missing order ID; cannot create a return.",
            "label_number": None,
        }

    # Defense in depth: refuse write unless eligibility already decided.
    decision = state.get("decision")
    approval = state.get("approval_status")
    if decision == "needs_approval" and approval != "approved":
        return {
            "visited_nodes": _append_visit(state, "create_return"),
            "label_number": None,
            "decision_reason": "Simulated staff approval is required before creating a return label.",
        }
    if decision not in {"eligible", "needs_approval", "already_returned"}:
        # already_returned still goes through create_return for idempotent label echo
        if decision != "already_returned":
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


def node_smalltalk(state: SupportState) -> dict[str, Any]:
    return {
        "visited_nodes": _append_visit(state, "smalltalk"),
        "reply": (
            "Hello! I am Holm Help, the support assistant for Holm Home Textiles. "
            "I can check synthetic order status, explain our return policy, or start a "
            "simulated return for demo order IDs such as H-1048."
        ),
    }


def node_blocked(state: SupportState) -> dict[str, Any]:
    reply = state.get("reply") or (
        "I cannot help with that request. Please ask about an order or our return policy."
    )
    return {
        "reply": reply,
        "visited_nodes": _append_visit(state, "blocked"),
    }


def node_handoff(state: SupportState) -> dict[str, Any]:
    if state.get("error") == "orders_unavailable" or state.get("decision") == "service_unavailable":
        reply = (
            "Order information is temporarily unavailable. "
            "I cannot look up shipment status or create a return right now. "
            "I am handing you off to a human agent. Please try again later, "
            "or share your order ID with the agent when they join."
        )
    else:
        reply = (
            "I am connecting you with a human support agent at Holm Home Textiles. "
            "Please stay in this chat; an agent will continue from here."
        )
    return {
        "reply": reply,
        "visited_nodes": _append_visit(state, "handoff"),
    }


async def node_answer(state: SupportState, *, model: Any | None = None) -> dict[str, Any]:
    """Compose the customer-facing reply (deterministic facts + optional NL polish)."""
    visited = _append_visit(state, "answer")

    if state.get("reply") and state.get("route") == "smalltalk":
        return {"reply": state["reply"], "visited_nodes": visited}

    order = state.get("order")
    order_id = state.get("order_id")
    decision = state.get("decision")
    reason = state.get("decision_reason") or ""
    label = state.get("label_number")
    approval = state.get("approval_status")
    route = state.get("route")

    # Build factual reply without inventing data.
    if decision == "unknown_order":
        reply = (
            f"I could not find order {order_id or 'with that ID'} in our demo records "
            f"(found: false). I will not invent a shipment status. "
            f"Please check the ID and try again, or ask for a handoff."
        )
    elif route == "orders" and order:
        status = order.get("status")
        product = order.get("product")
        shipped = order.get("shipped_date")
        delivered = order.get("delivered_date")
        amount = format_eur_cents(int(order["amount_eur_cents"]))
        reply = (
            f"Order {order_id} ({product}, {amount}) has status **{status}**."
        )
        if shipped:
            reply += f" Shipped on {shipped}."
        if delivered:
            reply += f" Delivered on {delivered}."
        if status == "in_transit":
            reply += " The shipment is still in transit."
    elif route == "policy" and state.get("policy_text"):
        reply = (
            "Here is a summary of our return policy: returns are accepted through the "
            "14th calendar day after delivery (inclusive). Returns over EUR 150 require "
            "simulated staff approval before a simulated label is created. "
            "Holm Help does not issue refunds. "
            "Full policy text was loaded via the read_return_policy tool."
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
            f"No return label was created and no refund was issued. "
            f"{reason}"
        )
    elif decision == "window_closed":
        delivered = (order or {}).get("delivered_date")
        reply = (
            f"I cannot create a return for order {order_id}. "
            f"Delivery date: {delivered}. {reason} "
            f"No return label was created."
        )
    elif decision == "not_delivered":
        reply = f"I cannot create a return for order {order_id}. {reason}"
    elif decision == "already_returned" and not label:
        reply = reason
    elif decision == "needs_approval" and not approval:
        reply = reason
    else:
        reply = reason or "How else can Holm Help assist you today?"

    # Optional NL polish via model (facts already fixed above).
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
            # For fake model, keep deterministic factual reply.
            if "fake-model" in content.lower() or "summarized the outcome" in content.lower():
                pass
            else:
                reply = content.strip()
    except Exception:
        pass

    return {"reply": reply, "visited_nodes": visited}


def build_graph(
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    model: Any | None = None,
):
    """Compile the Holm Help StateGraph with stable, visible node names."""

    async def route_node(state: SupportState) -> dict[str, Any]:
        return await node_route(state, model=model)

    async def answer_node(state: SupportState) -> dict[str, Any]:
        return await node_answer(state, model=model)

    builder = StateGraph(SupportState)

    builder.add_node("guard", node_guard)
    builder.add_node("route", route_node)
    builder.add_node("orders", node_orders)
    builder.add_node("policy", node_policy)
    builder.add_node("decide", node_decide)
    builder.add_node("approval", node_approval)
    builder.add_node("create_return", node_create_return)
    builder.add_node("smalltalk", node_smalltalk)
    builder.add_node("blocked", node_blocked)
    builder.add_node("handoff", node_handoff)
    builder.add_node("answer", answer_node)

    builder.add_edge(START, "guard")
    builder.add_conditional_edges("guard", route_after_guard, {"blocked": "blocked", "route": "route"})
    builder.add_conditional_edges(
        "route",
        route_after_route,
        {
            "orders": "orders",
            "policy": "policy",
            "smalltalk": "smalltalk",
            "handoff": "handoff",
        },
    )
    builder.add_conditional_edges(
        "orders",
        route_after_orders,
        {"answer": "answer", "policy": "policy", "handoff": "handoff"},
    )
    builder.add_conditional_edges(
        "policy",
        route_after_policy,
        {"answer": "answer", "decide": "decide"},
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
    builder.add_edge("smalltalk", "answer")
    builder.add_edge("blocked", END)
    builder.add_edge("handoff", END)
    builder.add_edge("answer", END)

    return builder.compile(checkpointer=checkpointer)


def initial_state(user_message: str) -> SupportState:
    return {
        "user_message": user_message,
        "sanitized_message": user_message,
        "visited_nodes": [],
        "tool_calls": [],
        "pending_approval": False,
    }


__all__ = [
    "Command",
    "build_graph",
    "initial_state",
]
