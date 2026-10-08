# Holm Help

Welcome to **Holm Help**, the customer-support assistant for **Holm Home Textiles** (Hamburg).

This is a public portfolio demo built with **LangGraph** and **Chainlit**. It shows a controlled, observable workflow: graph nodes, tool calls, a human-in-the-loop pause, and early blocked requests.

## Demo boundaries

- All customers, orders, and addresses are **fictional**.
- Access is **anonymous** — the app does not verify order ownership.
- Staff approval and return labels are **simulations**.
- The assistant **does not issue refunds**.
- Chat history is **not** persisted across restarts by default. LangGraph SQLite checkpoints **do** persist a paused approval state for the active process.

## Try these

- `Where is order H-1042?`
- `I want to return the wool blanket from H-1048.`
- `I want to return the curtain set from H-1107.` (approval pause)
- See `docs/scenarios.md` for the full scenario list.
