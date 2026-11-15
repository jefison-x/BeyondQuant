# Market research evidence scope

This additive contract applies to the existing durable daily and fundamentals
research reads. It changes no input, authorization, provider access, stored value,
PIT selection, schema migration or DSH runtime. Research responses retain v1 and
add explicit evidence metadata. It does not certify public search completeness.

## Daily reads

`evidence_scope` names the requested symbol and inclusive start/end, returned
row count and earliest/latest returned dates. `requested_range_checked=true`
means the query ran; it does not mean coverage is complete.
`outside_requested_range_checked=false` forbids treating a range response as the
inventory of all locally stored history. Returned rows remain usable as dated
observations even if coverage is incomplete; they do not prove interval returns.

`coverage.calendar_verified` requires an SSE Tushare calendar row for every
natural day in the request, including closed days. Missing calendar days have
an exact count and at most 200 date samples. `missing` lists missing bars only
on known-open dates, not guessed trading days. An empty missing-bar list cannot
prove complete coverage when calendar days are unknown.

`coverage.usable` additionally requires an explicit symbol, at least one open
day and a bar or explicit suspension for that symbol on every known-open day.
A verified all-closed range has reason `no_open_session` and usable=false.
A suspended open day can be usable=true with zero returned bars: this means
coverage is explained, not that a price exists or a return can be calculated.
Such dates appear in `suspended_sessions`; check actual returned data for prices.

Without a symbol, an exact-day request still returns persisted rows but does
not establish the full security universe. It now reports usable=false and
`symbol_universe_unverified`. This deliberately replaces the old inference of
full-market completeness from the returned symbol set. Use separately verified
market-session completeness when that broader claim is required.

## Fundamentals

The selection is `latest_visible_report_per_requested_symbol` at `as_of_date`.
The response does not return a historical series or establish historical absence;
backing dataset counts and ranges are not the returned report inventory.

`field_semantics` preserves uncertainty about the cause of a NULL. For requested
`roe`, formula, annualization and comparability to reported ROAE are unverified.
That does not establish equal or different definitions. `summary_use` is
`omit_until_basis_verified`; raw values remain unchanged for explicit inspection.
A non-NULL value proves availability, not a verified formula. No peer ranking,
annualization conversion or explanation of NULL is implied by these fields.

MCP passes this metadata through unchanged and keeps existing safe error handling.
Public filings, their dates and dividend status still need their own evidence;
these local-data scopes cannot establish that no later announcement exists.

## Model study date reference

GET Product /api/product/ml/options keeps its original shape without a pool_id.
With pool_id, Backend first checks the trusted owner and workspace, non-deleted
pool, active state and current immutable snapshot. Foreign or legacy NULL
workspace pools are not reassigned or exposed through this selector. The read-only selected_pool_data_reference
aggregates only that snapshot's members and persisted Tushare daily rows; SQL
also binds owner, workspace and current active snapshot. It returns counts and overlapping per-member date
bounds only when every member has data and the bounds overlap. This is not proof
of common sessions or continuous history. No-data, partial, inactive and missing
snapshot cases return no suggested dates.

reference_only=true, continuous_history_verified=false and
training_readiness_verified=false remain explicit; recommended_dates is null.
The form displays a reference and warnings, never silently fills example dates or
blocks saving a valid future research definition solely for absent data. Training
retains its existing preparation and approval requirements. Client requests are
lazy and scoped to the selected snapshot; stale pool/snapshot/auth responses and
responses after close/unmount are discarded. No new model, Job or provider call
is started by this metadata read.
