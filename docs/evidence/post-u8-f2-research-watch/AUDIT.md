# F2 research creation receipt watch — local qualification complete

Authorization: maintainer “授权执行。” continues the previously granted development,
push/PR, CI-green merge and operator authority. Community inspection remains waived
under Accepted ADR-0068. This maintenance slice does not advance Product Phase 97.
F6 was delivered separately in PR #268. F2 as a whole and S3 remain open.

Scope: the three MCP research creation families, finite durable original-request
receipt queries, task/conversation isolation and read-only Product projection.
See [contract](../../contracts/research-submission-watch.md).

Preliminary isolated evidence: six missing-capability failures on the unchanged
prior Backend image, then 23 passing receipt/reconciliation tests; expanded receipt
and F6 scope checks passed 30 tests. MCP build, research receipt tests and existing
write-outcome matrix passed. Frontend build and 179 existing tests passed; two new
stale-conversation/transport-failure tests passed. Source-mounted checks are preliminary
and are not immutable-image qualification. One test collection attempt lacked the
image's registry assets; correcting only the mount scope resolved that environment error.

Exact build manifests, full local CI and real Product API desktop/mobile acceptance
are complete below. Hosted CI, exact-head merge and production deployment are separate
receipts; they are not implied by these local results. No production data was
modified for the development fixtures.

## Feature checklist

| Behavior | Current evidence / required acceptance |
| --- | --- |
| One original business POST after durable acknowledgement | MCP fault tests; concurrent registration test |
| Late commit returns exact original entity | Real PostgreSQL, all three entity families |
| Query failure, expiry, attempts exhausted | Durable budget tests; remains unknown |
| Restart and concurrent consumers | Store recreation, separate connections and actual Gateway container restart PASS |
| Disabled identity / different workspace or conversation | Backend store and HTTP tests |
| F6 original task scope | Same-owner foreign-task watch refused |
| No model task when F6 is off | Gateway passive callback tests |
| State visible through ordinary login | Real Product API browser desktop/mobile PASS |
| Desktop/mobile overflow and persistence | Real browser assertions PASS; screenshots inspected |
| Other user cannot read receipt | Real browser second identity assertion PASS |

No new dependency, provider, service or production data migration. The schema is
additive. Rolling application images back leaves the inert receipt table intact;
no database restore is part of this change. The conservative single-POST rule can
leave an unsent request requiring attention if its registration reply was lost.

## Actual process restart probe

The isolated immutable `.30` Backend/Gateway/MCP images passed
[the HTTP fault probe](restart-probe.py). A transparent test proxy delayed only the
original ResearchTask POST by 14 seconds. MCP's actual 8-second timeout returned
outcome_unknown. The Gateway container was restarted before the original request
committed; its durable lifecycle context recovered the watch and confirmed the
same task on check 3. Exactly one original business POST reached the proxy.
F6 remained 0; this test stack had no Runtime or model provider container.
This is actual process restart evidence, separate from store recreation tests.
The probe uses only an explicitly labeled private network and tmpfs test PostgreSQL.
The probe's labeled containers/network were removed, and a separate
`cleanup-resources.sh --scope=f2-watch-probe --verify-only` check passed.

## Browser acceptance

All 13 real Product API journeys passed, including the two added F2 desktop/mobile
cases. Ordinary durable login, refresh persistence, exact conversation receipt
projection and second-user denial passed. No page errors, server errors or
unexpected origins were observed in these new cases. Horizontal overflow was at
most one pixel at 1440px and 390px. Both screenshots were visually inspected:
[desktop](desktop.png), [mobile](mobile.png). The deadline-expired fixture contains
an unsent original request, not a fabricated business failure or research result.

## Complete immutable qualification

Scope `local-u7-f2-watch-30`: all **30/30** checks passed, followed by an independent
scope cleanup verification. Backend 587 PASS / 1 SKIP / 7 subtests PASS; Gateway
219 PASS; Runtime baseline 157 PASS / 45 SKIP, candidate 166 PASS / 36 SKIP;
real candidate process tests 23 PASS. MCP full contracts PASS. Frontend build,
181 unit tests, 20 mocked browser cases and 13 real Product API cases PASS.
The existing F6 real-domain chain completed in three turns and retained the same
task after Gateway restart; both completed-task browser viewports passed.
Skipped tests and existing framework/ResizeObserver warnings are retained in the
original log and are not counted as passed tests. Docs and full diff checks passed.

Seven exact images were retained with an archive checksum. Source manifests `.29`
and earlier were not modified. See [qualification receipt](QUALIFICATION.json).
This closes the durable watch slice for the three named MCP creation families;
other non-ML families, all of F2, S3 and the interface audit remain open.
