# Child tool-count slice — missing files and session recovery (post-reboot)

The machine reboot cleared `/tmp`. Old handoff/probe/raw logs/temp compose/env are gone. This file
records what is missing, what was recovered **from this session's SQLite** (opencode.db `part` tool
`write` inputs), and what must not be reconstructed.

## Missing (cleared from /tmp) — NOT restored
- `/tmp/opencode/ACP-NARROW-HANDOFF-20261008.md`, `/tmp/opencode/ACP-NEW-SESSION-HANDOFF-20261008.md`
- `/tmp/opencode/acp-cand-build-20261008/*` (child probes, build logs, fixtures, identity files)
- `/tmp/opencode/diag-hardening-20261008/*` (earlier slice probe scripts/logs, `agent_entry.py`, `plan_run.py`, browser readback)
- `/tmp/opencode/adr0108-browser/*`, `/tmp/opencode/pwrun/*`, `redaction_proof.py`, `probe_acp_fix.py`, `judgment_fixture.py`, `ordinary_driver.py`
- **Secret-bearing (deliberately NOT restored, never printed):** `/tmp/opencode/byq-acpf6.env`,
  `/tmp/opencode/byq-acpf6-override.yml`, `/tmp/byq-acp-opencode-test-key-*.secret`

## Recovered from session SQLite (recorded `recovered-from-session`)
Source: `/home/jefison/.local/share/opencode/opencode.db` (read-only), `part` table, `tool:"write"` inputs.
- `recovered-from-session/boot_diag.py` (part `prt_11b39d114001rIOMnBkuYY7sBg`) — boot-only observer-load diagnostic.
- `recovered-from-session/count_only_hook_probe.py` (part `prt_118ba4f4b00140h8OsCk7mUpoN`) — root-only hook probe base.

Not recoverable as single writes (created earlier via `cp` + python heredoc mutations):
`count_only_child_probe.py`, `count_only_child_observer_probe.py`, `count_only_child_probe2.py`.
Their base hook probe is recovered above; the corrected probe for this slice is authored fresh at
`probe_count_only_child_scope.py` (secret-free).

## Local isolation (not in repo)
Full raw of the NOT_PROVEN run is kept only at
`/tmp/opencode/child-tool-count-raw-local-20261008/` (contains non-secret DSH state, not committed).
Repo keeps only reduced/desensitized evidence: `observer-reduced.jsonl`, `probe-result-reduced.json`,
`NOT_PROVEN.md`, this file, the probe source, and `recovered-from-session/`.

## Never reconstruct
Signed START env, provider keys, user passwords, or any secret-bearing temp file. Do not re-run the
already-PASS diagnostic/fresh-chain acceptances.

## Repo placeholder
`services/runtime-adapter/boot_diag.py` is a pre-existing, untracked, zero-byte placeholder (read
first, not deleted). The recovered content lives at
`docs/evidence/dsh-acp-single-version/child-tool-count-20261008/recovered-from-session/boot_diag.py`.
