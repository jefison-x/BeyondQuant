# ACP qualification data preparation — 2026-10-09

## Authorization / environment

Maintainer explicitly permitted reusing the production Tushare source in the test environment. Only its existing configuration credential was used, via the normal authenticated Gateway/Product credential-create API; no production DB/archive was imported or production service started. Secret value is absent from these receipts and was never placed in a command argument or source.

Fresh scope `byq-dev-c89ff732f2`; ordinary ACP roots and prior unknown roots were not replayed. Data preparation is local real-provider evidence, not production acceptance and not yet completed-background-Job ACP acceptance.

## Actual observed results

- Product credential POST HTTP 201; encrypted-store active Tushare source. Connection-test POST HTTP 200: `daily`, `000001.SZ`, `20260930`, one real row.
- Normal Product security-master Job completed: L/P/D catalogue, 5911 received / 5910 imported / one quarantined. Snapshot identity in the readback receipt.
- Normal Product single-stock range Job completed: `000001.SZ`, `20260901..20260930`, 21 real daily bars inserted. Temporary DataWorker stopped afterward.
- Worker local candidate `sha256:96e8ae88c0771f4f8979011093acd7fb15f17d368df8cf6653987faa68ccd28b`: offline derives current verified Backend `sha256:753662c496721f9cb3b411850351ba1ddfb08ec6661e7fe8716710c33661b281` app/dependencies, copies unchanged production worker.py SHA256 `470783582698669429fe01bff2b7b220a3e9919ee02dc848906db5f9be49a5d1`; UID/GID 10004, 1 CPU / 768MiB / 64 pids / restart no. This is not a clean-source Release Image qualification.
- Independent Reviewer checked all multi-queue and automatic-producer preconditions. Source scope starts with no DataImport, repair, pool definitions/runs, run-now or session jobs; automatic full-market scheduling disabled. The first bars Job was the only work.

## Three-date research completeness / retained failure

Single-stock bars alone cannot establish research readiness. A reviewed trusted Engineering DataPlane bootstrap fetched real calendar only for `20260928..20260930` (3 rows, all open) and created exactly three existing standard session Jobs. These Jobs fetch full-market daily + required supplements; their volume is larger than the one-stock range. No run-now, whole-month full-market request, new Product privilege, fake provenance or new harness.

**FAIL — qualification observer:** first read used `row_count`, which is a completeness-table field, not a Job column. The exception triggered finally-stop. Correct fields are `rows_received/rows_inserted/rows_kept`; both observer versions retained. This was not a provider rejection and not proof the Job had no effect.

After stopping, first date remains running / attempts 1; later dates queued / attempts 0. The first date already has 5557 canonical bars, while status/factors/session/supplement completeness remain empty. Product readiness returns `unavailable`. Partial durable writes are retained; no false completion or unknown-result reconciliation performed.

Old worker state: exited, PID 0, exit code 137, OOM false. First Job lease expires `2026-10-08 23:17:49.480277 UTC` (2026-10-09 07:17:49 Asia/Shanghai). Independent Reviewer allows one explicit Engineering recovery through existing lease-expiry/reclaim semantics, preserving attempts and partial data; cannot clear/shorten the lease or assert first attempt never happened. Recovery is NOT_RUN until lease expiry and exact preflight. Do not automatically re-run completed source/stock jobs or model tests.

Independent Tester verified receipt consistency for source connection/catalogue/single-stock ingestion. Root PASS is limited to these three operations. Quality receipt reports 21/21 valid OHLC and recomputed canonical hashes, unique dates, Tushare daily provenance, volume lots / amount thousand_cny / adjust none; Tester checked these assertions, not independent raw-row recomputation. Quarantine is T600018.SH / tushare_historical_alias. Native-history duplication count remains NOT_RUN. Independent Reviewer approved one natural-lease recovery using one worker start, a 240-second window counted before start plus finally-stop, and existing minimum 300-second failed-Job retry delay. Observed per-Job caps are 2/1/1, not persisted max_attempts; DB defaults remain unchanged. First observed error triggers best-effort stop; the next authorized date may already have been claimed. No recovery executed before lease expiry. Complete readiness, actual signal Job completion and ACP automatic background continuation remain NOT_RUN.

## Completed single lease recovery — actual follow-up

Recovery began only after the DB read-only preflight at `2026-10-08 23:17:52 UTC` confirmed natural expiry. Exactly one worker start; all three existing Job IDs finished completed with attempts 2/1/1 and error_code null. September 28: 5557 received, 0 inserted, 5557 kept (preserves first-attempt effects). September 29: 5559 received, 5558 inserted, 1 kept. September 30: 5561 received, 5560 inserted, 1 kept. Final Worker exited cleanly, exit code 0, PID 0, OOM false, finished 23:18:47 UTC. No third attempt, lease shortening or DB retry-cap change.

Actual Gateway `/api/product/data-center/readiness` HTTP 200 returned usable, 3/3 sessions, missing 0, calendar complete for `000001.SZ`, `20260928..20260930`, research. The initial script incorrectly used `/v1` on Gateway and received HTTP 404; corrected read-only Product route succeeded. Both the earlier observer failure and this path error remain recorded.

Independent Reviewer: bounded data-preparation PASS. Independent Tester: recovery-receipt consistency PASS (no independent raw-row recomputation or regression run). Root directly verified terminal Jobs, attempts, clean Worker exit and actual Product API response: bounded data-preparation PASS. This does not prove other symbols/ranges, browser, signal computation, automatic conversation continuation, production acceptance or default DSH switch.
