"""
Holm Help — Chainlit UI for the LangGraph customer-support demo.

Chainlit session.id is used as the LangGraph thread_id so interrupt()/Command(resume=...)
resumes the same checkpointed conversation.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import chainlit as cl
from dotenv import load_dotenv
from langgraph.types import Command

from holm_help.config import BOT_NAME, CHECKPOINT_DB, JOURNAL_DB, MODEL, STORE_NAME
from holm_help.graph import build_graph, initial_state
from holm_help.journal import init_journal
from holm_help.model import get_chat_model

load_dotenv()

# Align Gemini key naming for LangChain google_genai.
if not os.getenv("GOOGLE_API_KEY") and os.getenv("GEMINI_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]

# Module-level async checkpointer lifecycle (one local process).
_checkpointer_cm = None
_checkpointer = None
_graph = None


def _safe_step_summary(data: Any, *, limit: int = 400) -> str:
    text = str(data)
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


async def _ensure_graph():
    global _checkpointer_cm, _checkpointer, _graph
    if _graph is not None:
        return _graph

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
    init_journal(JOURNAL_DB)

    _checkpointer_cm = AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB))
    _checkpointer = await _checkpointer_cm.__aenter__()
    await _checkpointer.setup()

    use_fake = os.getenv("HOLM_FAKE_MODEL", "").strip() in {"1", "true", "yes"}
    model = get_chat_model(use_fake=use_fake)
    _graph = build_graph(checkpointer=_checkpointer, model=model)
    return _graph


def _thread_config() -> dict[str, Any]:
    """Map Chainlit session ID → LangGraph thread_id."""
    session_id = cl.context.session.id
    return {"configurable": {"thread_id": session_id}}


def _has_pending_interrupt(snapshot: Any) -> bool:
    if snapshot is None:
        return False
    tasks = getattr(snapshot, "tasks", None) or ()
    for task in tasks:
        interrupts = getattr(task, "interrupts", None) or ()
        if interrupts:
            return True
    # Newer/older APIs may expose next nodes waiting on interrupt.
    nxt = getattr(snapshot, "next", None) or ()
    if "approval" in nxt:
        return True
    return False


async def _emit_node_steps(visited: list[str], tool_calls: list[str], values: dict[str, Any]) -> None:
    """Show real executed nodes and tool calls as Chainlit Steps."""
    for node in visited:
        async with cl.Step(name=node, type="run") as step:
            step.input = _safe_step_summary(
                {
                    "route": values.get("route"),
                    "order_id": values.get("order_id"),
                    "decision": values.get("decision"),
                }
            )
            out: dict[str, Any] = {"node": node}
            if node == "orders" and values.get("order"):
                order = values["order"]
                out["order_status"] = order.get("status")
                out["found"] = True
            elif node == "orders":
                out["found"] = values.get("order_found", False)
            if node == "decide":
                out["decision"] = values.get("decision")
                out["reason"] = values.get("decision_reason")
            if node == "approval":
                out["approval_status"] = values.get("approval_status")
            if node == "create_return":
                out["label_number"] = values.get("label_number")
            if node == "blocked":
                out["blocked_reason"] = values.get("blocked_reason")
                if values.get("card_masked"):
                    out["card_masked"] = values.get("card_masked")
            if node == "answer":
                out["reply_preview"] = _safe_step_summary(values.get("reply"), limit=200)
            step.output = _safe_step_summary(out)

    for tool in tool_calls:
        async with cl.Step(name=f"tool:{tool}", type="tool") as step:
            step.input = {"tool": tool, "order_id": values.get("order_id")}
            if tool == "lookup_order":
                step.output = {
                    "found": values.get("order_found"),
                    "status": (values.get("order") or {}).get("status"),
                }
            elif tool == "read_return_policy":
                step.output = {"policy_loaded": bool(values.get("policy_text"))}
            elif tool == "create_return":
                step.output = {
                    "label_number": values.get("label_number"),
                    "simulated": True,
                }


async def _handle_interrupt(interrupt_value: Any) -> None:
    """Show approval pause BEFORE any create_return step."""
    payload = interrupt_value
    if hasattr(interrupt_value, "value"):
        payload = interrupt_value.value
    if isinstance(payload, (list, tuple)) and payload:
        first = payload[0]
        payload = getattr(first, "value", first)

    message = (
        "Simulated staff approval required\n\n"
        "This high-value return needs a **staff** decision before a simulated label "
        "is created. This is a portfolio demo — buttons simulate staff, not the customer.\n\n"
    )
    if isinstance(payload, dict):
        message += (
            f"- Order: `{payload.get('order_id')}`\n"
            f"- Product: {payload.get('product')}\n"
            f"- Amount: {payload.get('amount')}\n\n"
            f"{payload.get('message', '')}"
        )

    actions = [
        cl.Action(
            name="simulate_staff_approval",
            payload={"decision": "approved"},
            label="Simulate staff approval",
        ),
        cl.Action(
            name="simulate_staff_rejection",
            payload={"decision": "rejected"},
            label="Simulate staff rejection",
        ),
    ]

    async with cl.Step(name="approval", type="run") as step:
        step.input = "interrupt() — waiting for simulated staff decision"
        step.output = "Paused before create_return. No journal write yet."

    await cl.Message(content=message, actions=actions).send()
    cl.user_session.set("awaiting_approval", True)


async def _run_graph(input_payload: Any) -> None:
    graph = await _ensure_graph()
    config = _thread_config()
    cl.user_session.set("thread_id", config["configurable"]["thread_id"])

    # Collect updates while streaming for step visibility.
    final_values: dict[str, Any] = {}
    visited: list[str] = []
    tool_calls: list[str] = []
    interrupted = False
    interrupt_payload = None

    async for event in graph.astream(input_payload, config=config, stream_mode="updates"):
        # event is {node_name: update_dict} or interrupt markers depending on version
        if not isinstance(event, dict):
            continue
        for node_name, update in event.items():
            if node_name == "__interrupt__":
                interrupted = True
                interrupt_payload = update
                continue
            if isinstance(update, dict):
                final_values.update(update)
                if "visited_nodes" in update:
                    visited = list(update["visited_nodes"])
                if "tool_calls" in update:
                    tool_calls = list(update["tool_calls"])

    # Also inspect state for interrupts (authoritative).
    state = await graph.aget_state(config)
    if state and state.values:
        final_values = {**final_values, **dict(state.values)}
        visited = list(final_values.get("visited_nodes") or visited)
        tool_calls = list(final_values.get("tool_calls") or tool_calls)

    if state and _has_pending_interrupt(state):
        interrupted = True
        # Prefer interrupt payloads from tasks.
        for task in getattr(state, "tasks", None) or ():
            for item in getattr(task, "interrupts", None) or ():
                interrupt_payload = item
                break

    # Emit only newly completed nodes (avoid replaying the whole path on resume).
    previously_emitted = list(cl.user_session.get("emitted_nodes") or [])
    previously_emitted_tools = list(cl.user_session.get("emitted_tools") or [])

    visible_visited = [n for n in visited if n not in previously_emitted]
    visible_tools = [t for t in tool_calls if t not in previously_emitted_tools]

    if interrupted:
        # Pause before create_return; show approval via dedicated interrupt UI.
        visible_visited = [
            n for n in visible_visited if n not in {"approval", "create_return"}
        ]
        visible_tools = [t for t in visible_tools if t != "create_return"]
        await _emit_node_steps(visible_visited, visible_tools, final_values)
        cl.user_session.set(
            "emitted_nodes", previously_emitted + visible_visited + ["approval"]
        )
        cl.user_session.set("emitted_tools", previously_emitted_tools + visible_tools)
        await _handle_interrupt(interrupt_payload)
        return

    await _emit_node_steps(visible_visited, visible_tools, final_values)
    cl.user_session.set("emitted_nodes", previously_emitted + visible_visited)
    cl.user_session.set("emitted_tools", previously_emitted_tools + visible_tools)
    cl.user_session.set("awaiting_approval", False)
    reply = final_values.get("reply") or "How can Holm Help assist you?"
    await cl.Message(content=reply).send()


@cl.on_chat_start
async def on_chat_start() -> None:
    await _ensure_graph()
    thread_id = cl.context.session.id
    cl.user_session.set("thread_id", thread_id)
    cl.user_session.set("awaiting_approval", False)
    cl.user_session.set("emitted_nodes", [])
    cl.user_session.set("emitted_tools", [])

    await cl.Message(
        content=(
            f"**{BOT_NAME}** — support assistant for {STORE_NAME} (Hamburg).\n\n"
            f"This is a **public portfolio demo** of a controlled LangGraph workflow "
            f"with Chainlit observability.\n\n"
            f"- Model: `{MODEL}`\n"
            f"- LangGraph `thread_id` for this chat: `{thread_id}` "
            f"(same as Chainlit session id)\n"
            f"- Orders and returns are **synthetic**. Staff approval and labels are **simulated**. "
            f"No real refunds. Anonymous access — order ownership is not verified.\n\n"
            f"Try: `Where is order H-1042?` or see `docs/scenarios.md`."
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    if cl.user_session.get("awaiting_approval"):
        await cl.Message(
            content=(
                "A simulated staff decision is pending. "
                "Please use **Simulate staff approval** or **Simulate staff rejection**."
            )
        ).send()
        return

    await _run_graph(initial_state(message.content))


async def _resume_with_decision(decision: str) -> None:
    graph = await _ensure_graph()
    config = _thread_config()
    state = await graph.aget_state(config)

    if not _has_pending_interrupt(state):
        await cl.Message(
            content=(
                "There is no pending staff-approval interrupt on this thread. "
                "The button payload is ignored unless LangGraph reports a pending approval."
            )
        ).send()
        return

    # Trust only the action name / explicit decision enum — never order_id from payload.
    if decision not in {"approved", "rejected"}:
        decision = "rejected"

    cl.user_session.set("awaiting_approval", False)
    await _run_graph(Command(resume={"decision": decision}))


@cl.action_callback("simulate_staff_approval")
async def on_approve(action: cl.Action) -> None:
    # Do not trust order_id from payload — only the decision enum is used after
    # verifying a pending interrupt on this thread_id.
    await action.remove()
    await _resume_with_decision("approved")


@cl.action_callback("simulate_staff_rejection")
async def on_reject(action: cl.Action) -> None:
    await action.remove()
    await _resume_with_decision("rejected")


@cl.on_stop
async def on_stop() -> None:
    # Keep checkpointer alive for the process; Chainlit may call stop per session.
    pass


@cl.on_chat_end
async def on_chat_end() -> None:
    pass
