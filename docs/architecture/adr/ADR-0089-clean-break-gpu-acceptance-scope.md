# ADR-0089 — Clean Break GPU acceptance scope

- Status: Accepted
- Date: 2026-09-30
- Decision owner: BeyondQuant maintainer
- Acceptance evidence: the maintainer explicitly directed that GPU validation not be performed and that it cease blocking the current Clean Break gate in the development conversation on 2026-09-30.
- Scope: BYQ 0.10 Clean Break Phases 15–17 functional and Golden acceptance only. Product architecture, production qualification, and future GPU support are unchanged.
- Classification: Current non-product governance/security policy for BYQ 0.10 verification; it does not join the six Product Core ADRs.
- Supersedes: the mandatory GPU Worker execution and GPU checkpoint/restart acceptance clauses in `docs/clean-break/fidelity-and-execution-plan.md` and `docs/clean-break/verification-gates.md` for the BYQ 0.10 gate.

## Context

The isolated Phase 15 stack completed a real-provider LightGBM CPU TrainingJob and produced validated Feature and Model Artifacts. The current host has no NVIDIA device or Docker NVIDIA runtime. The previous Golden C wording required a GPU Worker and GPU checkpoint/restart, making the 0.10 gate depend on unavailable hardware after the maintainer chose not to run that validation.

## Decision

BYQ 0.10 accepts **CPU ML Worker** evidence for its TrainingJob, Worker independence, durable result, and Artifact contract. Golden C still requires an Agent-initiated TrainingJob and a real Worker termination/restart or reclaim observation while the Job is nonterminal, with the same durable Job ID and no duplicate result. No claim of mid-epoch model checkpoint recovery is made without direct evidence.

GPU execution and GPU checkpoint/restart are **out of scope (`N/A`)** for this 0.10 acceptance gate. They are not marked as tests that passed. A phase may pass when every in-scope requirement passes and this exclusion is recorded; a CPU TrainingJob alone does not complete Golden C.

## Consequences

The Functional Fidelity Matrix and Golden C wording use CPU Worker evidence. Phase 15–17 reviewers must check the remaining Agent, Job, Worker, Artifact, approval, audit and rebuild conditions. Historical `NOT_RUN` GPU evidence remains accurate. Future GPU support needs its own hardware-qualified acceptance before anyone claims GPU behavior works. This decision does not authorize deployment, push or merge.
