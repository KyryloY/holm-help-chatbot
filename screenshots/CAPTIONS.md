# Screenshot captions

Captured from a real local Chainlit run with `MODEL=google_genai:gemini-3.7-flash` (portfolio refresh).

| File | What a reviewer should see |
|------|----------------------------|
| `01-welcome.png` | Stack mention, synthetic-data disclaimer, LangGraph `thread_id` = Chainlit session id |
| `02-list-orders.png` | Nodes `guard` → `assistant` → `answer`; tool `list_demo_orders`; synthetic order list (not `found: false`) |
| `03-ask-slot.png` | Missing order ID → `ask_slot` clarification (not a fake lookup failure) |
| `04-status-H-1042.png` | After clarifying with `H-1042`: shipment status `in_transit` |
| `05-approval-pause-H-1107.png` | High-value return path through `decide` → `approval` interrupt; both simulation buttons; no `create_return` yet |
| `06-blocked.png` | `guard` → `blocked`; no tools for a customer-list / rule-bypass request |
