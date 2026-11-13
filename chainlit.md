# Holm Help

Welcome to **Holm Help**, the customer-support assistant for **Holm Home Textiles** (Hamburg).

Built with **LangGraph** and **Chainlit**: multi-turn slots, tool calling, gated returns, simulated handoff tickets, and observable steps.

## Demo boundaries

- All customers, orders, and addresses are **fictional**.
- Access is **anonymous** — the app does not verify order ownership.
- Staff approval, return labels, and handoff tickets are **simulations**.
- The assistant **does not issue refunds**.
- LangGraph SQLite checkpoints persist paused approvals and slot state. Optional local Chainlit SQLite may persist transcripts when enabled.

## Try these

- `give me list of existing orders`
- `Where is my order?` then `H-1042`
- `Where is order H-1042?`
- `I want to return the curtain set from H-1107.` (approval pause)
- `I want to speak to a human agent`
- See `docs/scenarios.md` for the full scenario list.
