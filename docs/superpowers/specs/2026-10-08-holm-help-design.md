# Holm Help — Design Spec

**Date:** 2026-10-08  
**Product:** Holm Help — customer-support chatbot demo for Holm Home Textiles (Hamburg)  
**Stack:** LangGraph 1.x + Chainlit 2.x + Python 3.12 + SQLite

## Goal

Public portfolio demo of a controlled, observable workflow: visible graph nodes, tool calls, human-in-the-loop pause, and early blocked requests — without claiming production security or real refunds.

## Architecture

Monolithic package `holm_help` with an explicit `StateGraph`. Chainlit is the only UI. Model calls live inside named nodes; eligibility, thresholds, and write permission are enforced in deterministic application code.

```
START -> guard -> blocked|route
route -> orders|policy|smalltalk|handoff
orders -> answer|policy|handoff
policy -> answer|decide
decide -> answer|approval|create_return|handoff
approval -> answer|create_return
create_return -> answer
smalltalk -> answer
blocked|handoff|answer -> END
```

## Tools (exactly three)

1. `lookup_order(order_id)` — `data/orders.json`
2. `read_return_policy()` — `data/policy.md`
3. `create_return(order_id)` — idempotent SQLite journal + simulated label

## Key constants

- `RETURN_APPROVAL_EUR = 150` (integer cents comparisons)
- `DEMO_TODAY = 2026-10-08` (injectable clock for tests)
- Model via `init_chat_model` from `MODEL` env (default `google_genai:gemini-3.7-flash`)

## HITL

`approval` calls `interrupt()`. Chainlit buttons only pass `approved`/`rejected` via `Command(resume=...)` on the same `thread_id`. Payload must not supply order ID or invent approval state. Writes only in `create_return` after resume.

## Limitations (honest)

Synthetic orders, anonymous access, simulated staff approval, simulated labels, no refunds, local-only persistence, no chat-history survival across restarts by default.
