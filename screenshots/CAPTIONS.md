# Screenshot captions

Captured from a real local Chainlit run with `MODEL=google_genai:gemini-3.7-flash` on 2026-10-08.

| File | Scenario | What a reviewer should see |
|------|----------|----------------------------|
| `01-welcome.png` | Start | Stack mention, synthetic-data disclaimer, LangGraph `thread_id` = Chainlit session id |
| `02-shipment-H-1042.png` | Scenario 1 | Nodes `guard` → `route` → `orders` → `answer`; tool `lookup_order`; status `in_transit`; no approval |
| `03-blocked-request.png` | Scenario 6 | Nodes `guard` → `blocked`; no tools |
| `04-eligible-return-H-1048.png` | Scenario 2 | Nodes through `decide` → `create_return` → `answer`; tools include `create_return`; simulated label; no pause |
| `05-approval-pause-H-1107.png` | Scenario 4 (before click) | Nodes through `decide` + `approval` interrupt; both simulation buttons; **no** `create_return` yet |
| `06-approval-approved-H-1107.png` | Scenario 4a | After **Simulate staff approval**: `create_return` + `SIM-LABEL-…` |
