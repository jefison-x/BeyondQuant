# Judgment ACP turn-diagnostic hardening — bounded Root PASS (2026-10-08, byq-acpf6)

Status: **bounded Root PASS for the three diagnostic safety fixes ONLY.**
This is **NOT** an overall ACP/single-version qualification, not a phase advance, and not
production/default/release. Production untouched; no push/merge/deploy/default/tag.

The prior writer's session aborted mid-patch; its dirty tree was preserved and no concurrent
writer was resumed.

## 1. First review FAIL (retained, not erased)

The **first independent review of the diagnostic mini-patch was FAIL**. The prior reviewer found
three defects; Root confirmed them. This record is retained as the historical FAIL:

- First-FAIL source of record: `/tmp/opencode/ACP-NARROW-HANDOFF-20261008.md` (lines 14–18,
  "Reviewer found FAIL; Root confirms").
- Prior (incorrect) redaction proof: `/tmp/opencode/redaction_proof.py` — it only tested very long
  synthetic strings (`HUGE_CLASS_NAME` = 259 chars, `LONG_SECRET_CODE` = 200 chars) and wrongly
  concluded that "any secret" was refused. Its conclusion is **corrected** below by a short-string
  test (`FAKE_SECRET_123`).

The three first-FAIL defects:

1. `_TURN_IDENTIFIER` was **not** a closed allowlist: an arbitrary short `error.code` or a dynamic
   exception class name (<64 bytes) could carry a secret into the journal.
2. `_record_turn_diagnostic` caught only `AcpJudgmentOutcomeUnknown`; an `OSError`/`PermissionError`
   from the optional diagnostic write could skip the original result commit / settlement / ACK.
3. `record_turn_outcome` still admitted `result_committed`/`terminal_closed`, so appending a
   missing diagnostic changed the sealed journal bytes/digest.

## 2. Remediation (files)

| File | Fix |
|---|---|
| `services/runtime-adapter/app/research_judgment_acp_journal.py` | `_TURN_ERROR_CLASSES` fixed class→category map + `_TURN_ERROR_CODES` closed enum (mirrors `_REJECT_CODES`); `_bounded_error_class`/`_bounded_error_code` return `None` for any unknown name/code (no `_TURN_IDENTIFIER` echo). `record_turn_outcome` restricted to pre-settlement phases `{begun, bound, prompt_may_have_dispatched, result_prepared}`. |
| `services/runtime-adapter/app/research_judgment_acp_turn.py` | `_record_turn_diagnostic` catches `Exception` only inside the optional seam; `KeyboardInterrupt`/`SystemExit` (BaseException) still propagate; commit/settle/original-error semantics unchanged. |
| `services/runtime-adapter/tests/test_research_judgment_acp_journal.py` | New tests: closed-allowlist helper, code-enum sync with `_REJECT_CODES`, no dynamic name/code persisted, pre-settlement admission + immutability, sealed-bytes refusal after `result_committed`/`terminal_closed`. |
| `services/runtime-adapter/tests/test_research_judgment_acp_turn.py` | New tests: `OSError` diagnostic write still commits the valid result; still settles and re-raises the original prompt failure. |

Source hashes at this evidence:

```
7af5050a5d8f290c72620233d0c028253789adf53a2d78e7f50481fe5b9ff8e7  services/runtime-adapter/app/research_judgment_acp_journal.py
b0e6a425adb565a551a14593e021ef96c2e1f69c5f9d5c7c25cc3d1708d53f62  services/runtime-adapter/app/research_judgment_acp_turn.py
294e223ce1b35b0c018d1f20504cc4e1cda5213042a4ff8db7b4d6a839a14901  services/runtime-adapter/tests/test_research_judgment_acp_journal.py
924ba5477473bfeef5bf35732f3712090cc9dd7406277a65aabced9eb0ab0457  services/runtime-adapter/tests/test_research_judgment_acp_turn.py
```

## 3. Targeted keyless test evidence

Command (candidate image `byq-acpf6-runtime-adapter:latest`, `--network none`, no model call):

```
docker run --rm --network none ... byq-acpf6-runtime-adapter:latest \
  python3 -m pytest -q -p no:cacheprovider \
  tests/test_research_judgment_acp_journal.py tests/test_research_judgment_acp_turn.py
```

- **60 passed** (53 pre-existing + 4 journal + 2 turn + 1 code-enum-sync).
- Log: `/tmp/opencode/diag-hardening-20261008/targeted-tests-FIXED.log` (this corrected run).
- Original first-FAIL context: `/tmp/opencode/ACP-NARROW-HANDOFF-20261008.md`;
  prior incorrect proof: `/tmp/opencode/redaction_proof.py`.
- Independent Tester raw probe file (12 probes, not repo-committed): `/tmp/opencode/probe_acp_fix.py`.

## 4. Independent verification (this slice)

- **Independent Reviewer (read code, no trust):** all three defects PASS. Confirmed closed maps,
  `except Exception` scoping, sealed-byte refusal, and no settlement/ACK semantics change. Flagged
  only the (already-covered) enum drift risk.
- **Independent Tester (12 own probes driving the real journal):** PASS. Short `FAKE_SECRET_123`
  class/code produced `None` and never appeared in journal bytes; a known class/code persisted;
  `OSError`/`PermissionError` did not block commit/settle and the original error re-raised;
  `KeyboardInterrupt` propagated; post-settlement calls raised with byte-identical journal.

## 5. Scope / boundaries

- Bounded Root PASS covers **only** the three diagnostic fixes above.
- The dirty tree also carries **pre-existing** prior-writer changes (`provider_session_id` overlay
  and `JudgmentRootOpenFailed` open-fence, ADR-0098) that are outside this diagnostic patch; they
  were preserved untouched and are not attributed to these fixes.
- No business semantics, retry, recovery, settlement, ACK, credential/prompt/provider persistence,
  or public contract changed. No new ADR required.
- Child actual-tool proof is handled as a separate slice (not mixed in here).
