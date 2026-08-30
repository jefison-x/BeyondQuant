# BeyondQuant CI execution and resource policy

Status: **Normative**

## Goals

CI must be complete relative to a change's impact, fast for narrow changes, isolated from the
`beyondquant` Product stack, and resource-clean after success, failure, timeout, or cancellation.
Path selection is an impact graph, not permission to skip a changed component's complete suite.

## Profiles

| Profile | Trigger | Required checks |
|---|---|---|
| Documentation | Markdown/evidence only | diff hygiene, changed-document links and architecture tests when normative architecture/contract/roadmap files change |
| Component | ordinary Product/service source | diff hygiene, architecture tests, complete build/unit/contract suite for every affected component |
| Integration | Compose, migrations, shared contracts, workers, CI, real-browser specifications or unknown executable paths | every affected component plus isolated Compose smoke, real Product API browser journeys, restart and two-user checks |
| Full | nightly schedule, release candidate or explicit manual dispatch | all components and the complete Integration profile |

Frontend source changes run the complete frontend build, Vitest and mocked Playwright suite but do
not start PostgreSQL or Compose unless they modify the real Product journey or a shared boundary.
Unknown source paths fail closed to Integration. `scripts/ci/classify-changes.sh` is the executable
source of truth and has architecture tests for representative routes.

## Pull request and merge policy

- Pull requests run the risk-selected profile.
- New commits cancel an older run for the same PR.
- A merge to `main` does not repeat the same full suite; nightly Full detects cross-change drift.
- Full CI remains available through `workflow_dispatch` and is mandatory for release candidates.
- A failing selected check is a failing required check. Selection may not hide an assertion failure.

Target service levels are under one minute for documentation, under four minutes for frontend-only,
under six minutes for an ordinary service, and under fifteen minutes for Full on the current runner.

## Resource ownership

Every mutable CI resource must be scoped by
`${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}` and either have a `byq-ci-*` name or the
`byq.ci.scope` label. CI must never address Product containers, networks or volumes by a broad
filter. `docker prune` is prohibited.

The runner enforces all of the following:

1. an `EXIT`, `INT`, `TERM` and `HUP` cleanup path inside `local-ci.sh`;
2. an independent workflow `if: always()` cleanup step;
3. idempotent removal of only the current run-attempt's containers, Compose project, networks and volumes;
4. post-cleanup verification that no current-scope resource remains;
5. a host-wide lock for heavy Compose CI;
6. a minimum available-memory preflight before Compose starts;
7. rejection of `--no-cleanup` inside GitHub Actions.

Failure diagnostics must be emitted or uploaded before cleanup. A cleanup-verification failure must
fail CI even if tests passed. Local debug retention is explicit, never automatic, and the operator
owns its prompt removal.

## Operator commands

```bash
# Select from the diff and show the plan without running tests.
scripts/ci/local-ci.sh --base=origin/main --with-e2e --auto-smoke --plan-only

# Run the same selective profile as a pull request.
scripts/ci/local-ci.sh --base=origin/main --with-e2e --auto-smoke

# Explicit Full profile.
scripts/ci/local-ci.sh --base=origin/main --all --with-e2e --with-smoke
```

Component deployment must not rebuild or restart its dependency chain. For a frontend-only release:

```bash
docker compose build frontend
docker compose up -d --no-deps frontend
```

After deployment, verify the changed service, its public route, dependent health and host resources.
