# U7.3 full local CI

Scope `local-u7-recheck-artifacts-20260906`: exit 0, all 26 checks PASS.
Independent cleanup verification PASS on continuation, 2026-09-07 Asia/Shanghai.
This is local CI evidence, not remote PR CI or production deployment.

- Root: 188 PASS.
- Backend: 331 PASS, one existing skip, seven subtests PASS.
- Gateway: 91 PASS; Runtime baseline: 77 PASS, two real-process-gated skips.
- Candidate real process and five-delegate journeys: seven PASS.
- Complete MCP contract suite and real save/legacy provenance checks: PASS.
- Frontend: 150 unit, 20 mocked E2E and nine real Product API E2E PASS.
- Cloudflare: typecheck, 15 workerd tests, four deployment-contract tests and dry-run PASS; no deployment.
- Full Compose smoke, genuine ML/backtest flows, restart persistence, two-user
  isolation and Product coherence: PASS.

Full-suite Compose intentionally tests the explicit old rollback baseline. The
promoted policy/registry combination is separately tested on these exact images
by the U7 closed model/Product/Chrome rehearsal. Do not label baseline E2E as
promoted-runtime coverage. No production credentials entered keyless CI.

[Retained image identities](retained-artifacts.json): seven application images,
461501440-byte archive, SHA-256
`3659a109ecbf9a293ef9a2f62b9602606c808694ccfb9a33c0604ef5a3ed9cf6`.
Archive restored after integrity/build/metadata verification; image identity is
local Docker identity, not a remote registry digest. No rebuilt replacement used.

## Performance and explicit reference-threshold exception

Raw samples are the baseline/candidate `*.recheck-ci.json` files here. Both
versions completed 20 create/prompt/release cycles with zero retained sessions
or lingering owned threads. Baseline/new median: 0.639450/0.960116 seconds,
below the frozen formula ceiling 1.767340 seconds.

Peak RSS: 210.426/287.023 MiB. New RSS exceeds the 284.5112-MiB formula ceiling by
2.5118 MiB (about 0.88%): **EXCEPTION, not threshold PASS**. Explicit acceptance
reason: component peaks attribute 73.887 MiB of the version delta to the official
bundled carrier and 2.711 MiB to Adapter Python. The 20 candidate samples range
268.961–287.023 MiB, end at 271.930 MiB, and do not show unbounded session/process
retention. No safety component was disabled and no reference formula was widened.
This continues the documented carrier overhead finding; it does not prove
24-hour production stability. U8 must still observe resource growth and owned
process closure on the actual deployment and retain rollback readiness.

The prior full run `local-u7-final-artifacts-20260906` remains FAIL (25/26):
unchanged-byte randomized cipher fixture, reproduced with synthetic counter 101.
Its separate raw `*.failed-ci.json` samples retain candidate RSS 291.746 MiB
against 286.184 MiB reference, excess 5.562 MiB. These measurements are not hidden
or replaced by the recheck. The successful rerun changed neither original cipher
test nor crypto implementation. See [execution](EXECUTION.md).
