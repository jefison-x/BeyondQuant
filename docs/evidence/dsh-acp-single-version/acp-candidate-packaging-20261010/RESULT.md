# ACP candidate packaging checkpoint

2026-10-10, retained isolated `codex/dsh-acp-single-version`.
OC (`opencode-go/deepseek-v4.1-flash`) prepared the candidate and relative
secret-scan scripts; independent Tester executed them, independent Reviewer
and Root gave limited candidate packaging/security PASS.

The first proposed source-only scan had four synthetic idempotency fixture
findings; exact inline annotations preserve the entire Python AST and values.
The first complete 344-file delta scan remained FAIL with 35 findings.
Independent classification established 29 previously classified source/log
digests and six new source hashes, all in five fixed JSON files. Absolute scan
paths did not match the existing anchored relative rules. The follow-up uses
snapshot cwd with target `.` and adds only the two exact archive JSON paths
to the existing path AND lowercase SHA-256 shape rule. It passed with zero
findings; 286 selected files and 344 snapshot files remained stable. The
original failed scans and raw redacted execution receipts are preserved locally.

During staging, four newly added files failed `git diff --check` for extra
blank lines at EOF. Only redundant trailing LF bytes were removed; both Python
ASTs and all other file bytes remain unchanged. A narrow scan of these four
format changes plus this summary is recorded separately. This summary adds
one path to the selected candidate (287 files; predicted PR delta 345 files).

`scripts/dsh/authoritative_version.py` is one of the retained image's 91 build
inputs. Its byte hash changed only because of EOF normalization. Earlier image,
three-role boot, synthetic F6 and archive receipts retain their original hashes
and remain valid checkpoints; they are not relabeled as an exact image of this
final packaging commit. Exact final-source image binding remains OPEN for the
planned CI qualification. No image rebuild or F6 replay was performed here.

Only reviewed source and 138 safe evidence files are selected; 231 diagnostic
evidence files and the unqualified SDK323/324 artifacts remain locally preserved.
The default ACP topology and Product phase are unchanged. Overall adoption and
release remain NOT_READY. Exact-head architecture/CI, complete 17-service export,
cross-store load, registry/SBOM/attestation and separately authorized publication
and production adoption remain OPEN/NOT_RUN.
