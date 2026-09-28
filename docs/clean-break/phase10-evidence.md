# Phase 10 DSH Adapter qualification — in progress

The qualified Product release remains the paired official DSH Python packages
`deepseek-harness-sdk==0.1.5rc1` and
`deepseek-harness-runtime-bin==0.1.5rc1`. See the
[transport contract](phase10-dsh-contract.md).

## Completed bounded slice

The Adapter no longer creates a fresh DSH process and native session under an
interrupted or failed public Agent session during `/resume`. A still-live READY
process can be reattached. A normal completed turn can still admit the next
explicit root. Interrupted and failed sessions reject same-session
reconstruction with distinct Product errors. The rejected call does not mutate
the Adapter record, issue a second model request or discharge an outstanding
Backend terminal acknowledgement. The hard-cancel event no longer promises
same-session restart.

## Public transcript input slice under review

The failed-turn `conversation_recovery.v2` envelope and its task-inference
helpers were removed. For an explicitly admitted new root, Gateway now selects
only Product conversation messages tied to a successful DSH root and a durable
public answer. It verifies the public answer was saved before supplying that
bounded transcript as input. A short ambiguous “continue/retry” after the
latest failed or cancelled root is rejected before saving a new user message;
the user must state the next instruction. This is Product-visible input, not
DSH-private session restoration. The first slice's distinct failed/interrupted
resume errors and exact business authority fence remain.

The implementer and independent Tester both observed affected Gateway tests
85/85 and Adapter tests 104/104 in isolated read-only images. The independent
Tester also observed governance 2/2 and a clean diff, including exact original
receipt/no-redispatch, `outcome_unknown`, completed public transcript and
ambiguous short-continuation cases. Independent Sol Reviewer inspected the
actual code/deletions and rated this bounded slice Functional PASS / Tests
PASS / Clean Break Architecture PASS. Root accepted this slice only; the
joined real Product/DSH two-turn gate was subsequently run below.

## Local verification

- Adapter process cleanup, generation continuity and session containment:
  92 passed in the pinned isolated test image (Luna implementer run).
- Independent Tester reran those suites plus root process lifecycle: 102 passed
  in the existing read-only, network-isolated test image. The image defaulted
  to root-turn mode; a first run had nine setup failures in session-mode tests.
  Setting the suite's intended `BYQ_DSH_PROCESS_OWNERSHIP=session` resolved all
  nine. Root-turn tests explicitly opt in to their own mode.
- Gateway Product Agent suite: 50 passed, independently repeated by Tester, in
  an isolated read-only image.
- Clean Break governance: 2 passed (independent Tester).
- Pinned DSH real-process blocked-child hard-cancel contract: 1 passed in an
  isolated read-only, network-isolated container with executable temporary DSH
  cache. The test used only loopback synthetic services. Two earlier attempts
  failed before test logic because the test-only DSH cache was absent and then
  mounted non-executable; no product code change was needed.
- `git diff --check`: passed.

Independent Tester: **PASS** for the affected behavior. Both bounded slices
have independent Tester/Reviewer PASS. The
[field audit](phase10-adapter-ownership.md) classifies the live Adapter
process/call handles, and ADR-002 now distinguishes Product-visible transcript
input from private DSH context. Reviewer rated overall architecture PASS in
principle. The joined real Product/DSH evidence follows.

## Joined real Product/DSH flow

The isolated [two-turn runner](../../scripts/clean_break/phase10_two_turn.py)
used the existing Phase 9 images with current Gateway/Adapter source mounted
read-only. The Adapter image contains the official paired DSH Python packages
at `0.1.5rc1`; no image rebuild or production selector change was claimed.
The five-service private Compose project used a fresh PostgreSQL volume,
synthetic credentials and a loopback scripted provider. No provider request
body or secret was recorded; the probe retained only exact-input booleans,
process IDs and exact terminal receipt observations.
The retained runner derives local image tags from the Phase 9 worktree scope
and verifies each image exists before starting. A later clean checkout can
rebuild its own core images and use the derived default. The live run used the
existing `byq-dev-3b060f285d` image refs before the runner was parameterized.
A post-change preflight selected the same refs with
`--image-project byq-dev-3b060f285d` and reported `stack_started=false`; no
second live run was needed for this test-only parameterization.

**Result:** `PASS` for disposable project `byq-p10-two-bde5890766`. The first
assistant answer was persisted through Product API before turn two. Backend
root `62de9a7eaf1d45f8b4787c7f0de668fa` had closed authority and its
exact terminal receipt was acknowledged before the second Product turn was
submitted. The second root
`395d520aeecd4b4d8b0e4fb09fa0745f` was distinct. Native DSH provider
process IDs were 32 and 66 in that isolated process namespace. The second
root received exactly one BYQ public input containing the completed first
user/assistant exchange plus its explicit current prompt; prior private tool
state and failed-turn recovery input were absent. Two Product MCP
registrations produced exactly two Backend domain rows. The runner verified
that all five containers and its network/volumes were removed afterward; Root
independently found no `byq-p10-two-*` container, volume or network.

Two earlier attempts failed a **test assertion**, not product execution:
the probe initially assumed DSH sends only one `user` role message, while
real DSH includes its own instruction messages. The assertion was narrowed
to require the exact BYQ Product input once without constraining DSH-owned
instructions. Each failed attempt also removed its own disposable resources.
The final PASS used that corrected probe. Independent Tester confirmed the
runner preflight, code syntax, isolated scope, cleanup inventory and evidence.
Independent Sol Reviewer inspected the complete diff and returned Functional
PASS / Tests PASS / Clean Break Architecture PASS for Phase 10 overall. Root
accepted **Phase 10 local PASS**; hosted CI and human PR/merge gates remain
separate. No push, merge or deployment was performed.
