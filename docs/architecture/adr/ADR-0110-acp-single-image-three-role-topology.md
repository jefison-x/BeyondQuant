# ADR-0110 — One ACP image for the adapter / product / judgment roles

- Status: **Accepted** (2026-10-09). The maintainer accepted in the ACP
  handoff conversation the one-image/three-role topology and its loss of
  independent per-role image upgrades. This authorizes bounded implementation
  and qualification of this topology; adoption, publication and deployment
  remain subject to the gates below.
- Date: 2026-10-09.
- Scope: the three ACP container roles already declared by
  `compose.dsh-acp-rc2-candidate.yml` (`runtime-adapter` = adapter,
  `acp-product-runner` = ordinary ACP process owner, `acp-judgment-runner` =
  dedicated judgment process owner) and the additive candidate
  `services/acp_unified/` + `compose.dsh-acp-single-image-candidate.yml`.
  It does **not** change the DSH release/version, provider route, business
  contracts, permission model, MCP boundary, network purpose, secret ownership
  or any Product/default promotion.
- Related: ADR-0093 (Product ACP root identity), ADR-0094 (delegate MCP scope),
  ADR-0097 (judgment process scope), ADR-0099 (judgment egress isolation),
  ADR-0100 (runner control availability), ADR-0103/ADR-0105 (single-version /
  F6 continuation), ADR-0080 (release-artifact secret boundary),
  `ARCHITECTURE.md` §K/§L.
- Evidence (evaluation only, not adoption): `/tmp/opencode/acp-unified/evidence/`
  (`ROOT-UIDFIX-REBUILD.txt`, `MATRIX-AND-BOUNDARY-ASSESSMENT.txt`) and
  `docs/evidence/dsh-acp-single-version/acp-single-image-security-fix-20261009/RESULT.md`.

## Context

The single-version ACP phase already resolves **one** DSH `release_id`,
`source_commit` and pnpm lock for all three roles
(`config/dsh/acp/authoritative.json`; `tests/architecture/test_acp_authoritative_version.py`
asserts `set(manifest["roles"].values()) == {release_id}`). That shared
`release_id` is a DSH-*version* value: it does **not** mean the three images
carry the same profile or release identity. Each per-role image keeps its own
baked profile/identity, and the accepted judgment image contains only the
judgment profile/identity and no deployment release identity (the adapter and
product images additionally bake `deployment.identity.json`). The three roles
are therefore not independently *versioned* today, but they are not identical in
profile/identity either. What remains per-role is the
**build**: three Dockerfiles (`runtime-adapter/Dockerfile.acp-0.2.0-rc.2-candidate`,
`acp_product_runner/Dockerfile`, `acp_judgment_runner/Dockerfile`) each produce a
distinct image and digest from largely the same DSH tree and lock, with
role-specific profiles, build inputs, ENV and PID-1 entrypoints.

The candidate overlay statically declares one shared image tag/build for all
three roles while every runtime boundary stays per-service in Compose, and the
role is chosen at startup by the explicit, fail-closed parameter `BYQ_ACP_ROLE`.
What has been shown at most is that a **single local build yields one local image
ID**. Registry digest publication, release-manifest binding of one digest to the
three roles, and three running containers actually sharing one digest are **not**
verified and remain adoption gates (see Adoption criteria).

## Decision (accepted scope)

1. **One build, one digest, three containers.** All three ACP
   services would declare the same `build` (the unified
   `services/acp_unified/Dockerfile`) and the same `image:` tag, so one build
   yields one image reference that all three roles reference. Role selection is a
   runtime parameter, not a distinct artifact. This ADR fixes the *intent*: the
   shared registry digest, its binding to the three roles in the release
   manifest, and three live containers sharing one digest are adoption evidence,
   not current facts.
2. **Per-role runtime boundaries stay Compose-owned and unchanged.** Network
   membership, read-only rootfs, capability drop/add, volumes/sockets, per-role
   secrets and PID-1 interpreter/entrypoint remain declared per service exactly
   as in the accepted `compose.dsh-acp-rc2-candidate.yml`. `no-new-privileges` is
   **not** uniform today: in `compose.yml`, `compose.dsh-acp-rc2-candidate.yml`
   and the candidate overlay only the two runner services set it
   (`security_opt: ["no-new-privileges:true"]`); the `runtime-adapter` service
   does not set it in any of the three files. This ADR does not silently add it
   to the adapter; adding an adapter `no-new-privileges` is a separate
   security-boundary decision. The shared image must not force one role's environment onto another:
   no role-specific ownership/transport/profile/`DSH_MAX_TOKENS_AS_SUCCESS` value
   is baked as an image default; they are supplied by Compose.
3. **Fail-closed role dispatch.** An unset or unknown `BYQ_ACP_ROLE` refuses to
   start (exit 64). The image default identity is the unprivileged adapter
   identity (`USER byq`, uid/gid 10002); the product/judgment services
   explicitly request `user: "0:0"` for their root PID-1 servers.
4. **Adapter identity is fail-closed, not just configured.** The adapter branch
   re-validates its **effective** uid/gid and refuses to start (exit 77) unless
   both are 10002; uvicorn is never launched otherwise. This closes the
   root-regression found in the first candidate, where only Compose pinned the
   adapter `user:` and the image defaulted to root.
5. **Build identity and digest binding.** The unified Dockerfile performs the
   authoritative `--verify-build-inputs` check for **all three roles before any
   network clone**, then clones the pinned release, checks source commit and pnpm
   lock, and re-reads all profile/identity hashes. The release identity must bind
   the three roles to the **same image digest**; the identity schema already
   permits equal `image_id` per role, so this is a binding/verification change,
   not a new storage schema. That binding is an adoption requirement, not yet
   implemented or verified. No literal commit/hash may be hard-coded in the
   Dockerfile (it is resolver-fed, matching the accepted per-role Dockerfiles).

## Benefits, and the independent-upgrade loss

**Gain (intended; not yet demonstrated end to end).** One build instead of three;
one digest to qualify, sign, publish and promote; no cross-role digest skew (a
partial rebuild cannot leave one role on a different DSH tree); a single artifact
surface to verify against the authoritative manifest; less CI/release build cost
and less image duplication. Today only a single local build yielding one local
image ID is shown; registry publication, release-manifest digest binding and
three live containers on one digest are still adoption gates.

**Cost — independent upgrade.** `ARCHITECTURE.md` §L states the directional intent
that future core components MUST be able to deploy and upgrade independently. A
shared digest couples the three roles' *upgrade*: rebuilding for one role
produces a new digest for all. This is the explicit exception this ADR must
record. Mitigations that keep the decision reversible:
the per-role Dockerfiles remain in the tree and are not deleted by this ADR; the
candidate overlay is additive and not auto-loaded; and the single-version
resolver already forces one `release_id` for all three roles, so the *version*
coupling already exists. Adoption trades per-role image-level upgrade independence
for release simplicity. If the maintainer judges per-role upgrade independence a
hard requirement, this ADR should be **rejected** and the three-image topology
kept.

## Role isolation under one digest

| Boundary | adapter | product | judgment |
|---|---|---|---|
| USER (Compose) | `10002:10002` (+ fail-closed effective-id guard) | `0:0` (root PID 1) | `0:0` (root PID 1) |
| PID 1 entrypoint | `uvicorn app.main:app` via dispatcher | `acp_product_runner/server.py` | `acp_judgment_runner/server.py` |
| Interpreter | `/opt/byq-venv` venv | system `python3` explicit | system `python3` explicit |
| cap_drop / cap_add | drop `NET_RAW` | drop `ALL`; add `CHOWN,SETGID,SETUID,KILL` | drop `ALL`; add `CHOWN,SETGID,SETUID,KILL` |
| read_only / no-new-privileges | neither `read_only` nor `no-new-privileges` (matches accepted adapter; adding is a future decision) | read_only + no-new-privileges | read_only + no-new-privileges |
| networks | `byq_product` + `byq_acp_judgment` | `byq_product` | `byq_acp_judgment` (internal only) |
| secrets | distinct, Compose-only; never baked | Product runner control secret | separate judgment runner control secret |
| volumes | runner + product control sockets, product session leaf | product sessions/state/control | judgment sessions, runner state/control |
| tmpfs | n/a | `/tmp` bounded, `noexec,nosuid,nodev` | `/tmp` bounded, `noexec,nosuid,nodev` |

The union image adds inert read-only bytes (both profiles/identities and both
runner servers). Runtime mounts, secrets and networks still isolate the roles;
no runtime privilege crossing was found in the boundary assessment. The
ADR-0097/ADR-0099 judgment-isolation rationale (dedicated internal network,
dedicated signing key, no product-network route from the judgment runner) is
preserved by the per-service Compose fields, not by the image.

## Plugin / content trimming is explicitly not part of this decision

The candidate does **not** trim DSH plugins, skills or build content. Removal
cannot be proven safe without a full DSH boot proof (NOT_RUN), and the
assessment found no product/adapter-required plugin or skill removable with high
confidence:

- The only high-confidence trims are judgment-only (two continuation/time-context
  JS files, ~20 KB) and are **needed** by the adapter+product roles in the union
  image, so they stay.
- `/opt/dsh-runtime/.git` (~37 MB) has no production reference but needs a boot
  proof before removal, so it stays.
- Pruning non-ACP `node_modules` (~1.1 GB) and source-only directories requires a
  filtered pnpm install plus a boot smoke and its own ADR: NOT_RUN, not done.

Trimming, if pursued later, is a separate decision requiring boot evidence and
its own ADR; it must not be smuggled into adoption of this topology.

## Rollback

This ADR does **not** introduce any requirement to retain the pre-existing
three per-role images as rollback artifacts. It adds no new rollback-image
obligation; existing general deployment rollback guidance is out of scope and
unchanged. The per-role Dockerfiles and the accepted candidate overlay remain in
the tree, so reverting the adoption is a Compose/build-selector change, not a
data migration. No database, session-store or volume format changes here.

## Explicitly not accepted by this ADR

- **BuildKit path** — the candidate image was built with the legacy builder;
  local buildx/BuildKit is absent. BuildKit execution is NOT_RUN.
- **17-image release batch** — the unified image is not integrated into the
  17-service release image set. NOT_RUN.
- **F6 ACP live business chain** — NOT_RUN; unchanged by this ADR.
- **Full / CI / publication / deployment** — NOT_RUN. No push/PR/merge/deploy/tag,
  no default promotion, no Phase advance.
- Any change to DSH version, provider route, MCP boundary, permissions, business
  contracts or secret ownership.

## Adoption criteria

Adopt only when **all** hold, with independent Tester/Reviewer/Root evidence:

1. This ADR is explicitly **Accepted** by the maintainer for the exact scope
   recorded above. **Satisfied on 2026-10-09**; criteria 2–6 remain gates.
2. The container-topology / build-identity contract tests
   (`tests/architecture/test_dsh_authoritative_build.py`,
   `tests/architecture/test_acp_authoritative_version.py`) are updated to encode
   the single-build/single-digest topology, and the architecture suite is green
   on the adopting commit.
3. The release identity binds the three roles to the same verified image digest,
   read back from the built image (not from build args).
4. A full DSH boot smoke passes on the unified image for **each** role under its
   Compose boundary, with the adapter effective-uid guard and runner root-PID-1
   guards proven (including the negative cases).
5. BuildKit-path qualification, or a maintainer-accepted explicit waiver, is
   recorded.
6. The 17-image release batch, F6 and Full/CI gates are separately satisfied or
   explicitly waived in the release plan.

## Rejection criteria

Reject (keep three images) if any hold: per-role independent image-level upgrade
is judged a hard requirement; the unified image cannot prove a role boundary at
runtime; digest binding cannot bind one digest to three roles; a full boot proof
shows the union content changes a role's behavior; or the maintainer does not
accept the plugin/content untrimmed surface.

## Consequences

- Defines the intended production topology. Until adoption criteria are met,
  the three per-role Dockerfiles and accepted overlay remain operative topology.
- Requires updating accepted topology/build-identity contract tests as part of
  adoption, and re-justifying the judgment isolation rationale against the union
  image.
- Keeps the change reversible (Compose/build selector) with no data migration.

## Acceptance record and remaining decisions

The maintainer accepted the shared image and independent-upgrade tradeoff in
the ACP handoff conversation on 2026-10-09. The accepted scope includes the
fail-closed role and adapter identity behavior, the existing role-specific
Compose boundaries, digest binding and contract updates required by the
adoption criteria, and no new old-per-role-image retention obligation. It
does not claim the candidate image is qualified or waive any gate.

- Verify release-identity binding and contract-test updates against the
  authoritative built image and adopting commit.
- Qualify the untrimmed plugin/content surface and the BuildKit path, or
  request an explicit, separate waiver for a gate that cannot be met.
- Decide any adapter `no-new-privileges` addition separately; it is absent
  from the current service declaration and is not part of this decision.

## Source adoption record (2026-10-11)

The default Compose/CI/release source route now declares the single-image
topology: `compose.dsh-acp-rc2-candidate.yml` (included by
`compose.override.yml`) builds the one `services/acp_unified/Dockerfile` for the
adapter / product / judgment services under one run-scoped project image tag and
dispatches the role at runtime by the fail-closed `BYQ_ACP_ROLE` parameter. Every
per-service runtime boundary (user, caps, `read_only`, `no-new-privileges`,
networks, volumes/sockets and per-role secrets) and the formal resource names
are unchanged. The additive `compose.dsh-acp-single-image-candidate.yml` remains
a separate isolated evaluation overlay, and the three per-role Dockerfiles remain
in the tree. The release/CI lane derives the topology from the single checked-in
Compose route (`scripts/release/images.py`), builds the ACP image once and aliases
that one image to the three role tags so per-service capture stays exact; there is
no ambient topology selector.

This record is **source adoption only**. It does **not** claim that any registry
digest was published or bound, that three live containers shared one digest, that
the BuildKit path or the full DSH three-role boot was re-run, or that hosted CI,
F6, the 17-image release batch, publication, promotion or deployment passed.
Those remain the separate adoption gates above and are exercised by the release
and deployment lanes, not by this source change.

### Operator environment delta for a published unified image

The published unified image bakes no role-specific process ownership, transport,
composition/profile or `DSH_MAX_TOKENS_AS_SUCCESS` value. A constrained operator
overlay for the digest-pinned unified image must therefore supply the role
dispatch and the role environment the accepted per-role images used to bake. The
required non-secret delta (names and literal non-secret values only; existing
per-role secrets remain operator-supplied by reference and no secret value is
recorded here):

- `runtime-adapter`: `BYQ_ACP_ROLE=adapter`.
- `acp-product-runner`: `BYQ_ACP_ROLE=product`,
  `BYQ_DSH_PROCESS_OWNERSHIP=workspace-slot`,
  `BYQ_DSH_COMPOSITION=/opt/byq/profiles/byq-product.patch.yml`,
  `BYQ_DSH_COMPOSITION_IDENTITY=/opt/byq/profiles/byq-product.identity.json`,
  `BYQ_DSH_RELEASE_IDENTITY=/opt/byq/releases/deployment.identity.json`,
  `DSH_MAX_TOKENS_AS_SUCCESS=false`.
- `acp-judgment-runner`: `BYQ_ACP_ROLE=judgment`, `DSH_MAX_TOKENS_AS_SUCCESS=false`.

Resolving this delta in the production overlay is a deployment-lane gate and is
**not** part of this source change.
