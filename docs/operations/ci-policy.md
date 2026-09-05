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

Machine-readable contracts under `docs/contracts/` are executable boundaries, not documentation-only.
Runtime dependency manifests/locks, carriers/compositions/plugins, service dependency manifests,
schema/bootstrap/migration code and every `real-*.ts` journey trigger Integration before broad path matches.
Inline Backend DDL is inspected in both current and baseline source so removals also trigger Integration;
new schema mechanisms must add regression cases in the same PR. Unknown paths fail closed.

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
- Every PR (including same-repository), nightly and manual run uses a standard ephemeral GitHub-hosted
  ubuntu-24.04 VM with read-only token and no production secrets/network. No self-hosted lane remains;
  the production runner registration must be revoked before visibility changes. Do not use `pull_request_target`.
  Billing/approval/runner unavailability means NOT_RUN, not pass. Runner access restrictions must be
  configured by the owner: workflow YAML alone is not a security boundary against a PR editing YAML.
- `ci-gate` requires both selected `local-ci` (including cleanup and log upload) and `contribution` to
  finish `success`. The latter runs the trusted base checker, never PR code with its API token, and checks
  exact-head CLA plus maintainer review for external contributions. Comment/review changes require a rerun;
  merge preflight repeats the live authorization read. This is not proof of copyright ownership.
  Configure both as strict required server-side checks. Skipped/neutral/cancelled is not successful testing.
- Before authorized pre-release auto-merge, use `check-github-gates.py`; configuration disabled or API
  403/unverifiable rules means keep Draft. Never bypass checks with administrative merge.

## Build identity and diagnostics

Every selected container suite builds its dependencies from the checked-out tree first, using normal
Docker layer cache. Images are named `byq-ci-stack-<scope>-<service>` for both component tests and
Compose; image IDs are printed after build. Build/inspect failure terminates CI before tests; Compose
uses `--no-build`. `--build` remains a compatible no-op flag, not permission to reuse production tags.
MCP always builds its live Backend dependency. Integration builds all default and tested optional services.
Local uncommitted changes are tested as a dirty tree, not claimed as evidence of an immutable commit.
Candidate release selectors/attestation remain DSH U1 work; this maintenance does not implement them.

CI disables automatic `.env`/Compose override loading and replaces DB/credentials with test-only values.
Test output must not be discarded. Workflow output passes through `redact-log.py` before console/log
storage; only sanitized logs are uploaded for seven days, including failure evidence before resources vanish.
Redaction is defense-in-depth, not permission to print real credentials, raw production logs or entire Env.
For local saved evidence, pipe through the same redactor with shell `pipefail`; do not persist raw logs.

Target service levels are under one minute for documentation, under four minutes for frontend-only,
under six minutes for an ordinary service, and under fifteen minutes for Full on the current runner.
These are targets, not measured hosted guarantees. Hosted runs record actual memory/disk/tool versions;
Docker build concurrency is limited to two, Node 24 and Python 3.13 are installed explicitly, and browser
OS dependencies are installed. Do not remove suites or reconnect production to meet timing targets.
Actions use their current Node 24-based v7 releases, pinned to verified full commit SHA; setup-node automatic
package-manager caching is disabled because this workflow does not require a shared dependency cache.
Gitleaks 8.30.1 is checksum-verified and scans new reachable history
with full redaction; initial complete-history review is separate publication evidence. Unknown findings block.
Standard public-repository runners have free execution minutes; larger runners, artifacts and caches have
separate limits. No larger runner or paid resource is selected by this workflow.

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

取消并行 BuildKit 时，客户端退出和最终镜像标签发布可能短暂竞态。独立清理只重试当前
run/attempt 的精确名称与标签，次数和间隔均有上限，并要求连续两次观察为零才通过；不能
通过全局 prune、删除其他 job 镜像或忽略第一次失败来掩盖竞态。

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
