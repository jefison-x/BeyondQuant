# Phase 13 — Runtime and Workspace reset

Base: `8d6929a140d4ebddc55091b43f9c8a3c9d465e4b` (Phase 12 merged `origin/main`).
Status: Phase 13 local gate PASS; repository PR/CI/merge gate OPEN.
Phase 14 schema baseline remains closed.

## Ownership and reset semantics

Phase 13 has two related boundaries. The **Product Reset Runtime** contract
must durably fence one Workspace's Agent business calls before Gateway releases
its exact DSH sessions and normalized traces. It preserves Jobs, Artifacts,
conversation transcripts, financial facts and unknown external outcomes. A
failed cleanup remains fenced and retryable. The **offline development reset**
stops Agent admission and Workers for the whole isolated Compose project, then
clears its disposable DSH sessions and Gateway traces. The dev command is not
evidence of the workspace-scoped Product contract.

`Reset Workspace` removes disposable research, conversations, temporary
experiments, generated Artifacts and completed Job history for exactly one
Workspace. Active Jobs require explicit cancellation and confirmed terminal
state before deletion. An active Agent root or an unresolved external action
must fail closed; absence of an in-memory session is not evidence of terminal
business authority. Keep the Workspace identity, membership, user accounts,
authentication, RBAC, SystemConfig, global credentials, shared data sources,
financial facts and audit records. Repeat calls must be safe. Fresh minimal
seed belongs to Phase 14 and Golden Scenario E/F verification to Phase 16.
The existing personal Workspace row and owner membership are the minimal
default state after reset; keeping their stable IDs avoids rekeying the user's
authentication context.

`make dev-reset-runtime` stops the verified **worktree-scoped** Compose stack,
removes only its DSH-session and workflow-trace volumes, then restarts the core
profile. It leaves PostgreSQL, Jobs and Artifacts intact. `make dev-reset`
adds Workspace data cleanup: it
stops all services, starts only its PostgreSQL, runs the exact Workspace reset
for each personal Workspace after preflighting all of them, removes only its DSH-session and workflow-trace
volumes, then restarts the core profile. Before runtime volume removal, an
offline maintenance container scans the two object volumes against **all**
remaining database references and removes only unreferenced verified CAS
objects in known namespaces. A repeat scan discovers any orphan left by an
interrupted deletion. PostgreSQL, reusable model/data cache outside those
namespaces, credentials and images remain. A blocked Workspace reset stops the
command before deleting runtime volumes; the stack remains stopped except for
PostgreSQL for diagnosis. `make dev-clean` remains the separate full stack
teardown with dry-run preview.

Neither operation may clear a whole PostgreSQL schema, shared object-store
namespace, Docker volume or DSH state shared by other Workspaces. Development
`dev-clean` is an isolated worktree teardown and is a separate command.

## Focused acceptance

1. The Product Reset Runtime route requires durable user authentication,
   fences only that user's Workspace, and cannot be invoked by Product Token.
   A retry after failure uses the same persisted reset operation.
2. The development command accepts only the verified isolated Compose project
   and its exact resources. It cannot operate on a Product stack or arbitrary
   volume. Durable Job and Artifact identities remain queryable after runtime
   reset.
3. Reset Workspace handles a generated research → Job → Artifact graph;
   active Jobs and unresolved external actions fail closed with no partial
   deletion. The user, membership, global settings and a second Workspace are
   unchanged.
4. Both resets are idempotent. Object blobs are removed only when no retained
   reference exists. The scoped development reset uses the same domain
   contract and never targets the Product stack.
5. Focused disposable-database and Gateway tests pass, followed by independent
   Tester, Sol Reviewer and Root PASS. Required hosted CI and repository merge
   gate are separate. Full empty-schema rebuild stays in Phases 14–16.

## Evidence

The UI acceptance items are tracked in the [Phase 13 feature checklist](phase13-feature-checklist.md).

Local focused checks: development reset command tests 12 passed; Workspace
SQL reset tests 4 passed against a fresh disposable PostgreSQL 16; object
cleanup tests 4 passed; Gateway runtime-reset contract tests 7 passed in an
isolated container. The disposable PostgreSQL container and network were
removed after testing. No existing Product database or volume was changed.

The maintainer explicitly authorized the previously blocked Backend
workspace-access/schema and private begin/finalize code changes on this isolated
branch. The Product route now fences one Workspace before exact Adapter session
release; an unsuccessful release leaves the durable fence for retry. A fresh
disposable PostgreSQL 16 run passed six focused Backend tests, including two
Workspace isolation, Agent admission denial during reset, exact release proof,
finalize and retry. The test containers and network were removed without a
persistent volume. The final `.266` build manifest check, 83 selected build and
architecture tests, and diff check passed.

**Independent Tester: PASS. Independent Sol Reviewer: Functional PASS / Tests
PASS / Clean Break Architecture PASS for the tested Backend/development slice.
Root acceptance: bounded slice local PASS; Phase 13 overall OPEN.** The later
Product Workspace reset candidate adds an authenticated Gateway Product API,
private Backend begin/finalize contract, persistent idempotency receipts, and a
frontend reset menu. Focused candidate checks passed: disposable PostgreSQL 16
Backend reset tests 10/10, Gateway reset tests 11/11, frontend focused tests
10/10 and frontend build. After the Reviewer identified two precise evidence
gaps, the affected Backend Product reset node passed 1/1 with a completed
FactorJob and Artifact in the deleted graph. The sole real-browser case passed
1/1 against a fresh PostgreSQL 16 and isolated six-service project: signed-in
user created a ResearchTask, confirmed Runtime reset and saw the task retained,
then confirmed Workspace reset and saw it removed; the protected page still
loaded after refresh and browser requests stayed same-origin. The exact test
project's containers, network and volumes were removed. One earlier browser
attempt stopped before any reset request because its locator matched two buttons;
the locator was made exact and only that case was rerun. Independent Sol Reviewer
inspected the actual diff and returned **Functional PASS / Tests PASS / Clean
Break Architecture PASS for the local Phase 13 code**. Root accepts this local
code gate as PASS. The maintainer explicitly authorized the `.267` build metadata
update; the immutable `.267` manifest and Dockerfile are current, `.267` and
frozen `.266` checks pass, and the focused build/retirement/architecture set
passes 86/86. Independent Sol Reviewer reconfirmed **Functional PASS / Tests
PASS / Clean Break Architecture PASS** on the final diff. Root accepts Phase 13
local gate PASS. The Product route removes Artifact database
references; physical object cleanup is a separate global-reference-safe GC
pass and is not claimed as immediate Product request behavior.
The repository PR/CI/merge gate is also open. No existing Product database,
deployment, push or merge was touched or authorized in this Phase 13 turn.
Fresh schema and Golden scenarios remain Phases 14–16.
