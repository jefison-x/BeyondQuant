# Phase 7 slice 10 — pinned live child contract

Base: `db00a1a2` on `clean-break/runtime-simplification`.

## Scope

The current DSH 0.1.5rc1 Product composition runs
`byq_delegate_market_research` as a foreground, one-shot DSH child. DSH owns
its execution. The Adapter's transient `ChildLease` observes the active child
and bounds inactivity while the dedicated root DSH process is alive. This
slice qualifies that live boundary; it does not add a child manager, change
Product APIs, resume a lost DSH process or rebind a child after restart.

An opt-in real-process test uses the pinned DSH SDK/runtime binary, the locked
Product composition and loopback synthetic Provider/MCP. It covers one normal
foreground child, one blocked child stopped by its dedicated timeout, and one
blocked child stopped by hard cancel. It checks root process closure and that
releasing the delayed Provider response cannot publish a late root success.
The test has no external network, credentials, database or production data.

The timeout remains `session.failed`/Product `failed`, which truthfully reports
an observed deadline failure. Hard cancel remains `session.cancelled`.
`interrupted` requires separate, exact loss evidence under the current
Gateway containment contract. This slice does not infer interruption from a
failure event.

## Evidence and limits

The default profile's child notifications and normal foreground result were
observed from the actual pinned process. The candidate continuable probe is
historical evidence for a different mode; its continuable-result predicate is
not the foreground contract. The new test is the current qualification.

This verifies one child at a time, normal completion, dedicated timeout,
hard cancellation and late-result rejection. It does not prove every child
progress-notification cadence, simultaneous siblings, process-restart rebind,
Backend delivery, browser projection or full Golden Scenario A. Existing
focused unit contracts cover event sequence/correlation and sibling accounting;
the broader real Product journey remains a later phase gate.

Tester, independent Reviewer and Root decisions are recorded in
[phase-gates.md](phase-gates.md).
