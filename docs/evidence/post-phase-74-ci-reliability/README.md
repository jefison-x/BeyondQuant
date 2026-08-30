# Post-Phase 74 CI reliability evidence

Date: 2026-08-30

This maintenance replaces unconditional pull-request Full CI with a tested change-impact plan while
retaining Full coverage for integration-risk changes, nightly drift detection and manual release
checks. It also introduces exact run-attempt resource ownership, signal-aware cleanup and an
independent workflow cleanup verifier.

## Local verification

| Check | Result |
|---|---|
| Architecture and CI policy suite | 75 tests passed |
| Changed-document validation | passed |
| Documentation selective lane | passed without Docker |
| Frontend selective lane | production build, 124 Vitest tests, dependency audit and 18 mocked Playwright journeys passed without Docker |
| Classifier fixtures | documentation, frontend, shared-contract and unknown-path routes passed |
| Exact-scope cleanup drill | disposable container, network and volume removed; zero resources verified |
| TERM interruption drill | active backend test interrupted; exact scope subsequently verified empty |
| Historical-resource reconciliation | 11 exact `local-*` scopes removed; CI containers, networks and volumes verified at zero |
| GitHub `--no-cleanup` rejection | exited with usage error as required |
| Shell syntax and diff hygiene | passed |

The existing Product stack was not stopped or rebuilt during these checks. No second local Full CI
was started; after reconciliation all ten `beyondquant-*` Product containers remained running and
the host reported 5,170,636 KiB available memory. The Draft PR is the single Full integration
execution for this CI-affecting change.

## Acceptance boundary

- A narrow lane still runs the complete suite for every selected component.
- CI/workflow/shared-contract/unknown executable changes fail closed to Integration.
- Full remains scheduled nightly and available through manual dispatch.
- Cleanup targets only the current run-attempt scope; broad prune operations are prohibited.
- The Draft PR must remain at the human merge gate after its required status check completes.
