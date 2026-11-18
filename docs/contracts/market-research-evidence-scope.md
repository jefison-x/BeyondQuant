# Market research evidence scope

This additive contract applies to the existing durable daily, valuation and fundamentals
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

## Valuation reads

The selection is exactly the requested symbols and fields on trade_date.
For compatibility, coverage.complete still means that the date dataset snapshot
is present; complete_scope names this basis. coverage.usable and usable_scope
check the requested selection, including missing symbols and fields. Neither
flag establishes full-market field completeness. dataset_row_count counts stored
rows, not non-NULL values. evidence_scope explicitly leaves other symbols and
fields unchecked and all_market_field_completeness_verified=false.

For requested dv_ratio/dv_ttm, field_semantics returns only the provider field
label and percent unit. Its calculation basis and implemented distributions
remain unverified. The read does not reconcile dividend periods, issuer payouts
or payment status; it cannot turn a dividend yield into a payout ratio. Values,
NULLs and existing authorization/provider/PIT behavior stay unchanged.

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
training_readiness_verified=false remain explicit at the date-reference level:
observed bounds do not certify the entire history. For an active current
snapshot, an optional horizon_sessions query (integer 1–20, default 5) also
evaluates a bounded compatible/v1 date recommendation. The recommendation checks
the persisted complete calendar, canonical ready input for every member and
session, and the existing feature builder's minimum counts (20 training rows,
5 validation rows and at least 1 prediction row). Forward-return labels remain
inside their own training or validation split. It creates no feature artifact,
study, training run, Job or provider/model call.

recommendation.state is available or unavailable. Its mode is compatible and
horizon_sessions binds the exact requested horizon. Only available returns six
compact YYYYMMDD recommended_dates fields plus train/validation/prediction counts.
Unavailable keeps recommended_dates=null and reports one of no_common_history,
calendar_incomplete, data_not_ready, insufficient_samples or inspection_limit;
counts is null. Inspection is limited to 401 calendar days and 50,000
symbol-session cells; exceeding a limit does not silently truncate the history.
Nested continuous_history_verified and minimum_samples_verified apply only to
the inspected recommendation window. training_quality_verified is always false:
meeting workflow minima does not establish model quality or training readiness.
Walk-forward and regime studies do not adopt compatible recommendations.

The form displays the reference and limitations. An explicit adopt action fills
the six dates only; loading data or changing pool, horizon or mode never
overwrites user dates or starts a write. It does not block saving a valid future
research definition solely for absent data. Training retains its existing
preparation and approval requirements. Requests are lazy and scoped to the
selected snapshot and horizon; stale pool/snapshot/auth/horizon responses and
responses after close/unmount are discarded.
