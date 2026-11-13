# Portfolio case: Holm Help

## Problem

Most chatbot demos hide the workflow: a reviewer sees chat bubbles, not the control plane. For customer-support work (returns, eligibility, approvals), that opacity is the wrong signal — it looks clever and proves little.

## What this demo shows

**Holm Help** is a local customer-support assistant for the fictional store **Holm Home Textiles** (Hamburg). The point is a **controlled, observable** LangGraph workflow rendered in Chainlit:

- stable node names in Steps (`guard`, `assistant`, `ask_slot`, `decide`, `approval`, …)
- recognizable tool calls (`lookup_order`, `read_return_policy`, `list_demo_orders`, `create_return`)
- a real `interrupt()` pause for high-value returns (simulated staff buttons)
- an early `blocked` path before tools/model for the documented abuse cases

Stack on the first README screen: **LangGraph + Chainlit**.

## What to look at (screenshots)

| Evidence | File |
|----------|------|
| Stack + disclaimer | `screenshots/01-welcome.png` |
| List path (not a fake `found: false`) | `screenshots/02-list-orders.png` |
| Missing ID → clarify | `screenshots/03-ask-slot.png` |
| Clarify then shipment status | `screenshots/04-status-H-1042.png` |
| HITL pause before write | `screenshots/05-approval-pause-H-1107.png` |
| Early blocked request | `screenshots/06-blocked.png` |
| Approve → simulated label | `screenshots/07-approval-approved-H-1107.png` |

Reproduce with `docs/scenarios.md`.

## Design rule worth copying

The model helps with intent and wording. **Deterministic application code** owns return eligibility, the EUR 150 threshold, approval state, and whether `create_return` may run.

## Limitations (honest)

Synthetic orders, anonymous access (no ownership check), simulated staff approval and labels, simulated handoff tickets, no refunds, local SQLite only — not a production deployment.
