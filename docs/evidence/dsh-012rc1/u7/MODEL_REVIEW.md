# U7 promoted-image semantic review — VERIFIED with retained failures

Scope `byq-u5-u6-0tth2mjd`, exact retained U7.3 images, synthetic users and
fixed G1–G6 only. No production conversation, user data or secret is included.
The machine receipt and semantic review are separate acceptance gates.

## G1 — PASS

The final public answer gives Asia/Shanghai 2026-09-07 from the runtime clock,
explicitly separates natural date from market evidence, and refuses to invent a
latest complete trading session because the synthetic calendar is unverified and
the persisted cutoff is absent. Only workspace/session-context reads occurred.

## G2 — PASS

The final public answer analyzes the actual completed synthetic backtest, not
merely its identifier: three trading dates, one buy, no closed trades, ending
equity 100069.697, commission 0.303, no frozen benchmark and aggregate-only
attribution. It explains short-sample uncertainty, concentration, unrealized
returns, zero-slippage assumptions and why extrapolated Sharpe/annualized return
are not strategy evidence. It neither invents attribution nor reruns training or
backtesting. The runner's bounded read-only scenario check also passed.

## Remaining gates

G3 FAILED (exit 1); original child diagnostics were not retained, so its precise
cause is unknown. G4 and final compatible rollback evidence read did not run.
Core G6 approval continuation and G5 follow-up passed, including old→new→old and
exact cleanup. The original overall receipt remains FAIL. Independent fixed G3/G4
diagnosis on the same retained images is in progress with private error retention.
This document does not authorize or claim production deployment or U8 completion.

## Independent G3 semantic finding — FAIL

Scope `byq-u5-u6-s1nwh9l-`, public conversation
`conversation_ab23af0b8eaa4ef4b634e497dd3cae66`: one final public answer, zero
matching approvals, five artifacts (four seeded plus one model strategy), one
seeded backtest, zero training/prediction/feedback. Public answer SHA-256:
`a58c22941ad9fc49463cbb70b7ee3b9bab2b1a401f24b92a5101500ac96c6ffd`.

The model explicitly limited the request to creating and validating a model
research draft, said that this creation did not require approval, and deferred
approval/training to a possible future request. Domain role policy confirms that
`byq_ml_strategy_create` is not approval-gated; `byq_ml_strategy_approve` and
training/prediction actions are gated. Thus no unauthorized execution or broken
approval system is established, but the required G3 approval/continuation journey
was not exercised and must not pass. The fixed prompt's conditional approval
wording permits this interpretation; the test requires exactly one approval.

Do not manufacture an approval, relax the assertion, or silently broaden the
paid prompt. A narrowly clarified G3 intent explicitly requesting one strategy
approval (without starting large training) would change the authorized fixed
prompt and therefore requires maintainer confirmation. Existing G1/G2/G5/G6
successes remain separate; G4/final evidence rollback remain unverified. The
bounded probe is still awaiting its normal deadline/cleanup at this observation.

## Authorized clarified G3 — PASS

The maintainer explicitly authorized one strategy approval, post-approval progress
read and no large training. Scope `byq-u5-u6-9upmb408` uses opt-in prompt revision
`u7-g3-strategy-approval.v2` (hash in raw receipt), not a rewritten historical G3.
It passed in 141.534 seconds with one approval and one bounded continuation retry.
Exactly two additional artifacts (strategy version and strategy approval), zero
training/prediction runs and zero feedback/Hub activity were observed. The public
answer confirms exact approval/strategy binding, authoritative validated/planned
states and no derived backtest. Public answer SHA-256:
`3d152ebc6a0b9862f7760592f465e9ee90eef1e80a2afc9062592bd67aeea9b3`.

The enclosing run remains FAIL: G4 reached final result construction after its
artifact assertions, but newly added prompt-hash reporting incorrectly called
`.encode()` on the evidence content dictionary. The private diagnostic identifies
`AttributeError`, not a provider/Domain failure. Cleanup PASS. The report bug is
fixed by hashing the submitted prompt before artifact inspection; a mocked full
G4 main-path regression covers the real dictionary-bearing artifact. No G4 PASS
receipt or semantic completion is invented. Independent fixed G4/evidence rollback
scope `byq-u5-u6-vnr1-dgb` is running; G3 is not repeated.

## G4 and compatible evidence rollback — PASS

The independent G4 run completed in 99.380 seconds, saved exactly one
URL-bearing Web Research Evidence artifact, created no other counted domain
objects, and left fake Hub counters at zero. Its final public answer links six
CSRC official-page/PDF sources, distinguishes search date from publication date,
declines to claim freshness when publication dates are absent, and explicitly
keeps the material out of factor/strategy/backtest inputs. This is a review of
the model's public answer and persisted evidence contract, not independent
verification of every regulatory source's contents.

Actual new→old coordinated Runtime/Backend/MCP rollback preserved the entire
research-artifact list hash and recognized the qualified new web producer;
no database rewind occurred. Other containers were unchanged. Final runner and
exact cleanup both PASS; see `g4-evidence-rollback.raw.json`. Overall U7 synthetic
acceptance combines the explicitly identified passing components of retained
core/G3 receipts with this independent G4 receipt. Failed original G3 prompts,
diagnostic startup and G4 reporting runs remain FAIL, never overwritten.
