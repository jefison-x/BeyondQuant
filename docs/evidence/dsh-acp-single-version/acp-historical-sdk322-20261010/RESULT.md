# Historical SDK 322 candidate closure

2026-10-10, retained isolated `codex/dsh-acp-single-version`, HEAD
`2d5810973240c5d7692569319c2b5ab337ae2082` plus working changes.
Tester → independent Reviewer → Root **limited PASS** for the three-file
historical SDK identity correction. No current SDK or ACP release qualification
is inferred from the historical artifacts.

`scripts/dsh/build_revision.py` selects the exact frozen `.322` identity for
`dsh-0.1.5rc1`; it no longer registers untracked `.323` or selects untracked
`.324`. The two tests distinguish exact stored bytes from a structurally valid
render of today's source. ACP selectors and runtime routing are unchanged.
The three paths are absent from the retained unified image's 91 inputs.

The tracked `.322` manifest and Dockerfile remain byte-identical to HEAD:
`ee97823eb01251c48f99a0b7d2a1d5b50debba6f1f9533e39c47862eedce90cc`
and `dc87eeb772d37fafd29fd4c38d81475cffe1549bd767419f766307cc9d36bfa5`.
Four untracked `.323/.324` artifact files are preserved locally, with their
hashes and Git status unchanged; they are excluded from the proposed candidate.

Independent Tester executed only `tests/test_current_build_revision.py` and
`tests/test_dsh_build_revision.py`: **7 passed in 1.35 s**, compile and scoped
diff checks PASS, source hashes unchanged. The original receipt's FAIL was
a local summary predicate error: it compared `?? <path>` with literal `??`.
`artifacts/tester/result-initial-calculation.json` preserves that original;
the correction used identical captured pre/post evidence without rerunning
tests or relaxing a gate. Independent Reviewer verified the correction and
reported no P1/P2 findings; one duplicated assertion is nonblocking P3.

Frozen source hashes and independent receipts are retained in `artifacts/`.
No Docker, build, F6, provider call, commit, push or deployment occurred in this
slice. Overall adoption/release remains **NOT_READY**; exact candidate secret
scan and adopting-commit/hosted gates remain separate.
