# D2 — Single authoritative DSH version manifest (design)

Status: **Design + authoritative value created; consumers not yet wired, default
not yet switched.** The default runtime stays SDK until the ordinary ACP path is
qualified for production (see the gate table); switching the default while ACP
is unqualified is not permitted.

## Authoritative value

`config/dsh/acp/authoritative.json` (`byq-dsh-authoritative-version.v1`) is the
single source for the ACP DSH version and its bound artifacts:

- `release_id` / `source_commit` / `pnpm_lock_sha256` for `dsh-v0.2.0-rc.2` @
  `639ed015…`.
- Per-role release (`adapter`, `ordinary_runner`, `judgment_runner`) all
  `dsh-v0.2.0-rc.2` — one version across every DSH container.
- Profile/identity paths and exact sha256 for Product and judgment, and the
  release identity.
- Capability entries that point at Accepted ADRs and evidence; an entry is
  `NOT_RUN` until its evidence exists.
- Offline-only rollback release `dsh-0.1.5rc1`.

## Consumer rules

- Consumers (Compose defaults, dev environment, Adapter/runner Dockerfiles, CI,
  Release Images, Promote, ops config) must resolve the version/commit/profile
  from this manifest. No scattered literals; no selector that disagrees with the
  built Dockerfile.
- Qualification identifiers bind to the **tested artifact and configuration**
  digests, never to a "version >= X" predicate. A newer tag does not inherit an
  older qualification automatically.
- Multiple containers with different roles are allowed; their DSH version must
  be identical.
- The normal online path must not import the old SDK, branch on its version, or
  auto-fall back to it. Old files are retained only as classified offline
  rollback/delivery assets.

## Validation (to implement with the cutover)

A focused architecture test will assert, for every consumer:
- Compose default / dev `CURRENT_DSH_DOCKERFILE` / runner Dockerfiles / CI
  `BYQ_DSH_*` / Release-Promote selectors resolve to the manifest's
  `release_id`/`source_commit`.
- The manifest's profile/identity hashes equal the worktree files and the
  embedded Dockerfile assertions.
- No normal-path module imports `deepseek_harness` / `deepseek_harness_runtime`
  outside the classified rollback boundary.

## Transition and rollback

- Switch the default only after the ordinary ACP path passes the remaining live
  qualification gates; the cutover is a normal PR through the existing gates.
- Rollback is the exact `0.1.5rc1` images/configuration, offline only; never a
  normal-path fallback and never by replaying pending/unknown input.
- Old-version records in historical evidence are not mechanically rewritten;
  classification of what remains as history vs. removed is explicit.

## Open items

- Wire consumers and add the validation test (requires a new build revision
  because source roots change).
- Complete F6 ACP, judgment lifecycle and interrupted-business-continuation
  evidence entries before their capability entries leave `NOT_RUN`.
- D3 user-visible cutover decision (see `SESSION-CUTOVER-CONTRACT.md`).
