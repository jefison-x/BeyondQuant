# U7 execution — IN_PROGRESS

U6 PR #257 merged at 2026-09-06T14:23:57Z, commit
`1ff7df40091dca22620c36da58c90ff4e51f3d1c`. GitHub run 34038058846 passed all
required checks, full CI 26/26 and root 179 PASS. Historical reports stay unchanged.

## Explicit authority

Maintainer: “允许恢复当前停止的 BYQ 生产服务，使用
/home/jefison/backups/byq-dsh-u7 保存私有备份，部署 DSH 0.1.2rc1，
并持续观察 24 小时完成 U8 验收”. Existing U1–U8 push/PR/CI-green squash
auto-merge authority remains subject to ADR-0015/0059. No database rewind/deletion,
Community write, public release/tag or new Product capability is authorized.
Paid model payloads remain synthetic fixed G1–G6 plus synthetic BYQ context only;
this evaluation must never send production dialogues to a model.

Worktree `.byq-worktrees/dsh-u7-promote-012rc1`, branch
`chore/dsh-u7-promote-012rc1`; Product Phase 97 unchanged.

## Baseline recovery performed

Initially PostgreSQL and five core services were stopped (exit 0), Gateway/relay
healthy, three Workers restarting. Cause/intent unknown. Exact project beyondquant;
database volume `byq-postgres-clean-20260904`, not Community storage.
Started only existing postgres, backend, signal-sandbox, mcp, runtime-adapter and
frontend containers, with original images/configuration/volumes. Afterwards core
healthchecks and Gateway readyz passed; ML Worker healthy and data/signal Workers
running, no longer restarting. No test model prompt or feedback submit was made.
This is restored OLD production, not candidate deployment.

## Private backup and restoration

Approved root mode 0700. Backup directory:
`/home/jefison/backups/byq-dsh-u7/baseline-20260906T144052Z`.
`byq-domain.dump`: 2284257666 bytes, mode 0600, SHA-256
`2dfba2c8b34108f8691612f529ddc69ce223181a263bf28abe585a0f2fb917aa`.
The dump, 105 table counts and eight critical-table SHA-256 fingerprints share the
SAME exported repeatable-read READ ONLY snapshot. No row contents in stdout/Git.
Source database size: 17764555799 bytes; initial available host disk about 77 GiB.

Readability PASS. Actual restore PASS in network-none disposable scope
`byq-u7-restore-e73b48e96c39`, using exact source PostgreSQL image. No production
data-directory mount or source-database restore. Cleanup targets only newly created
test resources with matching labels. All 105 counts, eight critical content hashes
and validated constraints matched; cleanup PASS. The private dump remains retained.
This baseline dump does not replace final drained session/trace backup.

## Implementation and retained failures

Promotion tests first failed because implementation did not exist, then passed
exact-report/hash/negative and unchanged capability-ceiling checks. Initial root
run: 183 tests, one error: old-producer hashing incorrectly used a candidate-only
mocked release directory. Implementation now hashes its explicit baseline file;
all four original provenance tests pass, without changing the negative assertion.

U7.1 manifests predate that correction and the complete rollback policy. They are
immutable, uncertified history; a new revision must bind finalized inputs. Default
selection and projections are staged only. New image qualification, full CI,
Product/model/Chrome acceptance, merge, final backup and candidate deployment are
NOT COMPLETE; U8 observation has NOT STARTED.

U7.2 now binds the finalized image inputs: baseline manifest
`sha256:8109e7a5873f4a7d4eb55d6f6300a972aab380a1b802a984888b1ade6959073c`,
target manifest `sha256:f72db702f3f669f97516f11e4d80be3cc9ca4f0af7f983c0509b742c328453f7`.
Root suite 185/185 PASS; docs and diff checks PASS. A prior non-escalated targeted
test invocation could not create temporary directories under the read-only sandbox;
the full permitted rerun passed. Historical failing assertions remain unchanged.
Full CI scope `local-u7-artifacts-20260906` has started, including E2E, smoke,
paired lifecycle measurements and exact image retention. CI outcome pending.

That U7.2 run was deliberately stopped (exit 143) after independent review found
the rollback Dockerfile's default release-identity argument still selected the
global promoted identity. A regression test reproduced the failure before repair.
It also reported one documentation assertion failure after the progress update
omitted the explicit U5/U6 non-production boundary; the statement is restored in
its historical context, with no assertion removed. Test containers were cleaned;
production remained healthy. U7.2 is NOT QUALIFIED. U7.3 fixes the baseline identity
input and adds actual installed policy/registry/identity byte comparison to every
promoted rehearsal preflight and switch. U7.1/U7.2 manifests remain unchanged.

U7.3 baseline/target manifest hashes:
`sha256:d15a2404fea190f41486a18645219e5955789361002fbb82c25e56fe57ee9f70` /
`sha256:84accb9dd446f62c92c61312cb52436b4f643265917e1fcdf47e2852c8bba0d8`.
The first root rerun exposed CI's literal U7.2 selector before fake Docker was
called. CI now resolves both revisions through `selected_build_id`; the existing
build-failure/no-stale-image assertion remains intact. Root 187/187 PASS, docs
and diff PASS. New full CI scope `local-u7-final-artifacts-20260906` is running.
Its root tests passed; one Backend failure has appeared, pending full diagnostics.
No final qualification or artifact handoff is claimed for an incomplete CI run.

Backend diagnostic: `test_cipher_authenticates_aad_and_tamper` failed with
`DID NOT RAISE CredentialUnavailable`; 330 passed, one skipped, seven subtests
passed. The original fixture replaces the final randomized ciphertext byte with
zero, which is a no-op when it was already zero. The standalone network-none
diagnostic reproduced this with deterministic synthetic nonce counter 101:
unchanged ciphertext decrypts; actual changed ciphertext and changed AAD are
rejected. No production key/data used, original test and application unchanged.
The full CI still FAILS; diagnosis is not a waiver. A new full run is required.
The diagnostic test container was automatically removed; the original failed run
and its benchmark files remain separate from any later successful certification.

Additional production read-only check: original SDK/runtime-bin 0.1.1rc1, profile
research, the same three enabled plugins, zero active prompts/sessions; available
backup filesystem space about 73 GiB. No real user history or model payload read.

The failed full run finished 25 PASS / 1 FAIL; exact-scope cleanup verified zero.
Recheck scope `local-u7-recheck-artifacts-20260906` has passed root 188/188 and
Backend 331 PASS / one existing skip / seven subtests; other checks are pending.
The successful Backend rerun did not modify or bypass the original failing test.

## Original application recovery archive

Private directory `/home/jefison/backups/byq-dsh-u7/application-20260906T152832Z`
contains the exact original Backend/MCP/Gateway/Runtime/frontend images, actual
container configuration and separately identified current main Compose/env files.
The latter are not assumed identical to the original container configuration.
Archive `original-images.tar`: 346248704 bytes; SHA-256
`16c2a178dc77746e36a32cd468481df87c1aeb3747c7380354030d691066f417`.
Tar inventory readable and contains five images; directory 0700, all configuration
and archive files 0600. No configuration content, credentials or production data
are in Git or model payloads. No service changes performed. These B0 images are
historical recovery evidence, not a substitute for the qualified R1 rollback set
which must recognize new web evidence. Final drained session/trace backup pending.

## Resumed final acceptance

Automatic tool review temporarily stopped further file work due to account usage
limits. No bypass was attempted. Maintainer subsequently requested continuation.
The already-running CI finished successfully: all 26 checks PASS, exit 0; exact
cleanup verified on continuation. See [CI result](CI_RESULT.md). Seven-image
archive integrity/build/metadata validation and restore passed; no rebuild used.

Promoted synthetic scope `byq-u5-u6-0tth2mjd` is executing with the authorized
literal-key bootstrap and fixed G1–G6. The first old→new switch and actual
desktop/mobile Chrome maintenance/completion/plugin review passed. Main remains
at the U6 merge; no official release exists. Live runner final result, U7 PR/merge,
production switch and U8 observation remain pending.

The promoted runner subsequently FAILED at G3 (subprocess exit 1), with exact
synthetic cleanup PASS. G1/G2 automated and semantic checks passed; core
old→new→old G6/G5 and namespace checks passed. G4 and final new-evidence rollback
read did NOT RUN. See `promoted-rehearsal.failed-g3.raw.json`; no aggregate PASS
or production readiness is inferred. Original runner discarded child stderr,
so the precise G3 cause is not recoverable from that receipt. Diagnostic retention
now saves child stderr privately (0600), publishes only its hash and never retries
within a run. Two new safety tests and the existing targeted suite pass (14 tests).
Both frozen U7.3 build manifests still validate unchanged. An initial manual build
check omitted required `--build` and exited with usage error; explicit old/new
checks then passed. Independent exact-image G3/G4 diagnostic scope
`byq-u5-u6-344ob6hf` has started; paid G1/G2/G5/G6 are not repeated.

That diagnostic launch failed BEFORE any model scenario: it redundantly switched
an already-new empty namespace, correctly tripping the existing nonempty-runtime
namespace assertion. Receipt `diagnostic-launch.failed.raw.json` and cleanup PASS
are retained. The runner now checks an already-selected target without switching;
the namespace assertion is unchanged. Root 190/190 passed after diagnostic
retention was added; targeted eight rehearsal tests passed after the startup fix.
New diagnostic scope `byq-u5-u6-s1nwh9l-` is executing G3. Production core services
remain healthy on the old version; backup filesystem has about 72 GiB available.
