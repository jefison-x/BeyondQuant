# Phase 81 Chrome MCP Review

Reviewed on 2026-08-30 against the merged production Compose stack at `http://127.0.0.1`.

- Desktop accessibility tree showed the completed first user/assistant pair and the contextual second
  pair in the same durable conversation.
- A 390×844 mobile viewport retained both turns, the composer, navigation entry and approval status;
  the recovered answer remained visible as `海棠七号`.
- Console review after the release/reopen follow-up returned no warning, error or issue messages.
- Network review showed only same-origin Browser requests: authentication, Product settings/approvals,
  conversation catalogue/replay, normalized WorkflowTrace stream and Product turn submission.
- The follow-up used `POST /v1/agent/sessions/{conversation_id}/turns` and returned 202. Browser traffic
  did not reach Backend, MCP, DSH, PostgreSQL, a provider or a Worker directly.
- The misleading failure copy is covered by unit and mocked Playwright regression tests; the successful
  real journey did not render a failure state.
