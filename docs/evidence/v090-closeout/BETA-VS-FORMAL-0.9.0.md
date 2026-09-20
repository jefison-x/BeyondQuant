# `v0.9.0-beta` versus a formal 0.9.0 closeout

Status: **audit only — no tag, release or deployment is created or moved by this change.**

## What the historical `v0.9.0-beta` tag actually is

| Fact | Value |
|---|---|
| Object | annotated Git tag |
| Tag points to | `135bc7d3f34037689477c08231f1405197e27523` |
| Tag date | 2026-09-17 |
| Tag message | `BeyondQuant v0.9.0-beta (source 135bc7d, build post-u8.116)` |
| Relation to base commit | ancestor of `origin/main` `80fb9f8`; **47 commits behind** |

It is a **pre-release marker**: the promotion tag contract was extended in `#284` to
accept stable, beta and RC tags (`v[0-9]+\.[0-9]+\.[0-9]+(?:-(?:beta|rc)(?:\.[0-9]+)?)?`
in `scripts/release/manifest.py`), and the beta tag was created for the then-current
`post-u8.116` build. It is a version label, not a release record.

`v0.9.0-beta` therefore does **not** represent a formal 0.9.0 closeout. The
[VERSION_PLAN](../../roadmap/VERSION_PLAN.md) 0.9.0 gate is "发布清单绑定源码、镜像和实际服务组合，
完成独立发布验收" — a release manifest that binds source, images and the actual
composition, with independent acceptance. None of that exists for this tag.

## Why the beta tag cannot be promoted into 0.9.0

- The tag predates Phase 98/99/100/101, ADR-0077..0081 and the entire D15 stage; its
  source is not the current product baseline.
- `VERSION_PLAN` requires a release record with product version, source SHA, CI run,
  precise digests for **all** services, internal build identity, migration
  classification, actual deployment scope, backup, rollback version and acceptance
  evidence.
- `scripts/release/manifest.py` defines that formal shape as `byq-release.v1`; no such
  manifest is committed on the base commit (only the validator and its tests reference
  the schema).
- The published rule is explicit: a released version cannot be overwritten; changes
  require a new version. Reusing or rewriting `v0.9.0-beta` is prohibited. This audit
  does not touch it.

## What a formal 0.9.0 closeout still lacks

Machine-readable form: [acceptance-matrix.v1.json](acceptance-matrix.v1.json)
`formal_0_9_0_manifest_requirements`.

| # | Missing formal-manifest item | Required form | Current state |
|---|---|---|---|
| 1 | Source SHA | 40-hex source commit of the released build | **missing** |
| 2 | Trusted-main CI run | `https://github.com/jefison-x/BeyondQuant/actions/runs/<id>` from the trusted release workflow | **missing** |
| 3 | All-service image digests | `ghcr.io/...@sha256:...` plus config `image_id` for every service | **missing** |
| 4 | Actual composition | which services are new builds versus retained digests | **missing** |
| 5 | Migration classification | `none` / `forward-compatible` / `operator-required` with review | **missing** |
| 6 | SBOM | SPDX file per service with bound sha256 | **missing** |
| 7 | Backup | backup receipt and readable checksum where required | **missing** |
| 8 | Rollback | previous digests and configuration retained and recorded | **missing** |
| 9 | Independent acceptance | real Product API / business journeys on the actual composition, not health checks | **missing** |
| 10 | Attestation | verifiable with signer-workflow / source-ref / source-digest | **missing** |

## What must happen (separate, explicitly authorized, not this batch)

1. Freeze a candidate source commit and run the trusted release workflow
   (`release-images.yml`) at that exact SHA.
2. Produce the `byq-release.v1` manifest with items 1–6 above and attest it.
3. Record items 7–8 (backup/rollback) and perform item 9 (independent acceptance)
   on the actual composition.
4. Obtain an explicit maintainer decision to create the formal 0.9.0 release/tag.

Items 1–3 and 9–10 are release operations. This audit is a **Draft** governance change:
it creates no tag, publishes no release, and does not move `v0.9.0-beta`.
