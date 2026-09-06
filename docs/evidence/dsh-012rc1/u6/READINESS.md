# U6 independent-build release readiness

Decision: U6 isolated release rehearsal VERIFIED. T01–T39 acceptance is supported
by the new build-bound report; T40 NOT_RUN. This is not production authorization,
a claim of production health, or an upstream release publication.

## Exact tested compatibility set

[Retained artifact receipt](retained-artifacts.json) is the seven-service image
manifest. B1/R1 use its runtime-adapter image (old release); C1 uses its
runtime-candidate image. Backend, MCP, Gateway, frontend and feedback relay are
identical across the tested switches. PostgreSQL and fake Hub are isolated fixture
dependencies, not deployable replacements for production data or the real Hub.

Both release descriptors, generated historical identities, historical Dockerfiles,
U5 reports and withdrawn-report failure assertions remain unchanged. See ADR-0061.
Independent builds:
- Baseline: dsh-0.1.1rc1-u6.3; manifest
  sha256:bc84ddeff4851d90541008a5baf0507840f374cd160bc2b16853b882a6837c1f.
- Candidate: dsh-0.1.2rc1-u6.3; manifest
  sha256:c76bff7fd0dd4189c02cddf77777d1812a98bf74bd07e630308d8622868bf0a6.

The receipt's image IDs are local Docker identities (OCI index/manifest IDs where
supported), not remote registry digests. The raw rehearsal records the same
resolved image IDs. Do not substitute a config digest, floating tag or rebuilt
image. The validated 461490176-byte OCI/Docker archive is the recovery authority:
SHA-256 c50628332acd52441647e3baba083f5f4b8a206f98a65a1b19d38c8eac781c5a.
It is retained under the worktree's private
`.ci-artifacts/local-u6-artifacts-20260906/retained-u6/`. CI's original tags were
removed normally. Operator restore verified all seven original image IDs.

Actual resolved base layers, not future floating-tag assumptions:

| Input | Observed SHA-256 |
|---|---|
| Python 3.13 slim bookworm | ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e |
| Python 3.11 candidate base | 528257d48c1da0dcecc2e725d1ae34498d60c965f1241e39cd6a85a8859bdf84 |
| Node 24 bookworm slim | ba849c60be29959425b8734d57b8b4b7d56f98edd9504c9af091d5281095a71e |
| Node 22 frontend build | 83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5 |
| nginx 1.27 alpine | 65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10 |

## Executed rehearsal and rollback commands

From the isolated U6 worktree, the reproducible entry points for the final runs
(with a bounded Chrome review window for the core run) are:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m tests.dsh_upgrade.rehearsal --model-key-env-file /home/jefison/projects/BeyondQuant/.env --browser-window-seconds 180 --ci-scope local-u6-artifacts-20260906 --qualify-g1-g4
PYTHONDONTWRITEBYTECODE=1 python3 -m tests.dsh_upgrade.rehearsal --model-key-env-file /home/jefison/projects/BeyondQuant/.env --browser-window-seconds 0 --ci-scope local-u6-artifacts-20260906 --g2-only
```

The first run's operator implementation is commit
266823b67301a6b2b92576eea631192365f3d172; the targeted G2 probe correction is
dc0b3fa6150b6d43536e87009ac2eb809a7ededa. Neither changes frozen application inputs.
The runner reads only the literal authorized model-key field, never sources the
file, strips controller credentials after bootstrap, and exposes no key in evidence.

[Core raw receipt](core-rehearsal.raw.json) records scope byq-u5-u6-mr5ccwtq:
closed shared admission → drained zero prompts → candidate runtime-only
replacement → queued G6 continuation exactly once → contextual G5 → closed/drained
→ old runtime-only replacement → same-conversation G5. The seven other container
IDs and start times remained unchanged. Additional candidate G1–G4 were followed
by another drained rollback. Maintenance uses one local shared inode with
read-only Gateway/Runtime mounts; it is not a multi-host/NFS locking design.

Zero cross-namespace writes were asserted during the core opposite-version
intervals. The raw namespace_checkpoints map contains the latest checkpoints
after additional runs, not the original paired snapshots; do not reinterpret
those final hashes as initial/core pairs. No private JSONL conversion or domain
mutation replay is performed.

One pending approval and one feedback survived: fake Hub attempts=1, received=1,
published=0, including duplicate continuation. No real Hub submission, moderation
or GitHub Issue occurred. [Model review](MODEL_REVIEW.md) retains the original G2
semantic rejection and the separately successful exact-object-context retest.

## Backup and actual restore

Synthetic dump: /tmp/byq-u6-mr5ccwtq/backups/synthetic-domain.dump,
275457 bytes, mode 0600, SHA-256
1bdfbe2d5992d9bfa6960d68cbcd93b11b1f641e1ec8a859e94b05fc5ad128c1.
An actual restore into isolated byq_u6_restore matched all 105 public table counts,
critical row fingerprints and validated constraints. This is stronger than
pg_restore --list, but only proves the synthetic rehearsal. The raw receipt
includes the comparison results. No physical PostgreSQL copying occurred.

Both final synthetic scopes were removed with zero containers/networks/volumes;
their logical dumps and safe metadata remain locally recoverable. Operator image
archive is retained separately and was not deleted. Temporary synthetic files
are not a persistent production backup or a promise of indefinite retention.

## Performance and retained failures

[Final 20+20 raw samples](lifecycle-comparison.retained-artifact.json):
baseline/candidate median 0.643482/0.968379 seconds, below the 1.7721784-second
ceiling; peak RSS 210.133/284.379 MiB, above the frozen 284.1596-MiB ceiling by
0.2194 MiB (0.0772%). The report records an explicit RSS exception, not a threshold
pass. Main carrier RSS differs by 72.266 MiB; Adapter by 1.980 MiB. Both completed
20 cycles with zero retained sessions/lingering owned threads; no safety services
were disabled. This is consistent with U5 carrier overhead, not proof of
production long-term memory stability. Earlier larger excesses and failed CI/
rehearsal attempts remain in [validation](VALIDATION.md).

## U7 preflight remains a separate gate

Production defaults remain dsh-0.1.1rc1 / Product Phase 97. U6 merge is authorized;
production start, default promotion and deployment are not yet authorized.
The last read-only observation found production PostgreSQL and core services
stopped and workers restarting; cause/intent unknown. Do not start them implicitly.

Before U7: obtain operator authority for the exact restoration/deployment service
list and an administrator-selected persistent private backup path; confirm the
merged code, actual production resources and healthy B0/B1 baseline; preserve
real database/Worker continuity and independently back up drained sessions/traces.
Derive required Backend/MCP/Gateway/Runtime/frontend changes from actual policy/
registry/admission inputs, not from an assumed runtime-only production operation.
No production command is fabricated from the synthetic Compose project.

U7 generated promotion/profile/policy changes are new image inputs: they require
a new immutable build revision and appropriate qualification. Do not relabel
these U6.3 artifacts as P1 if any bound input changes. Rollback preserves domain
data and uses retained compatible R1 artifacts, never database rewind, npm/PyPI
resolution during incident response, or production down -v/prune. Identity,
authorization, duplicate mutation, hidden failure or leak red lines stop promotion.
U8 needs actual deployment plus a real 24-hour observation window (first 30 minutes
dense checks); it cannot be marked complete from U6 tests or zero production traffic.
