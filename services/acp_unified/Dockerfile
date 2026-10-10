# BYQ ACP single-image candidate (adapter / product / judgment roles).
#
# One artifact serves the three ACP container roles; the role is chosen at
# runtime by the explicit, fail-closed BYQ_ACP_ROLE parameter (see
# services/acp_unified/entrypoint.sh). This Dockerfile is ADDITIVE and does not
# replace the three role-faithful Dockerfiles; adopting it as the release lane
# requires an Accepted ADR and the container-topology / build-identity contract
# tests to be updated first.
#
# Boundaries preserved per role by Compose (unchanged): user/caps/read_only,
# no-new-privileges, networks, mounted volumes/sockets, profile/identity and
# secrets. No secret is baked here. The fixed official DSH source/lock and the
# authoritative build-input check for ALL THREE roles are enforced before any
# network clone.

FROM node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c AS official-dsh

ARG BYQ_DSH_BUILD_RELEASE_ID
ARG BYQ_DSH_BUILD_SOURCE_COMMIT
ARG BYQ_DSH_BUILD_PNPM_LOCK_SHA256
ARG BYQ_DSH_BUILD_COMPATIBILITY_FAMILY
ARG BYQ_DSH_BUILD_ADAPTER_PROFILE_PATH
ARG BYQ_DSH_BUILD_ADAPTER_PROFILE_SHA256
ARG BYQ_DSH_BUILD_ADAPTER_PROFILE_IDENTITY_PATH
ARG BYQ_DSH_BUILD_ADAPTER_PROFILE_IDENTITY_SHA256
ARG BYQ_DSH_BUILD_ADAPTER_RELEASE_IDENTITY_PATH
ARG BYQ_DSH_BUILD_ADAPTER_RELEASE_IDENTITY_SHA256
ARG BYQ_DSH_BUILD_ORDINARY_RUNNER_PROFILE_PATH
ARG BYQ_DSH_BUILD_ORDINARY_RUNNER_PROFILE_SHA256
ARG BYQ_DSH_BUILD_ORDINARY_RUNNER_PROFILE_IDENTITY_PATH
ARG BYQ_DSH_BUILD_ORDINARY_RUNNER_PROFILE_IDENTITY_SHA256
ARG BYQ_DSH_BUILD_ORDINARY_RUNNER_RELEASE_IDENTITY_PATH
ARG BYQ_DSH_BUILD_ORDINARY_RUNNER_RELEASE_IDENTITY_SHA256
ARG BYQ_DSH_BUILD_JUDGMENT_RUNNER_PROFILE_PATH
ARG BYQ_DSH_BUILD_JUDGMENT_RUNNER_PROFILE_SHA256
ARG BYQ_DSH_BUILD_JUDGMENT_RUNNER_PROFILE_IDENTITY_PATH
ARG BYQ_DSH_BUILD_JUDGMENT_RUNNER_PROFILE_IDENTITY_SHA256

COPY scripts/dsh/authoritative_version.py /opt/byq-authoritative/scripts/dsh/authoritative_version.py
COPY scripts/dsh/acp_build.py /opt/byq-authoritative/scripts/dsh/acp_build.py
COPY config/dsh/acp/authoritative.json /opt/byq-authoritative/config/dsh/acp/authoritative.json
COPY config/dsh/acp-0.2.0-rc.2.identity.json /opt/byq-authoritative/config/dsh/acp-0.2.0-rc.2.identity.json
COPY plugins/dsh-byq/profiles/acp-0.2.0-rc.2/ /opt/byq-authoritative/plugins/dsh-byq/profiles/acp-0.2.0-rc.2/

RUN test -n "$BYQ_DSH_BUILD_RELEASE_ID" \
    && test -n "$BYQ_DSH_BUILD_SOURCE_COMMIT" \
    && test -n "$BYQ_DSH_BUILD_PNPM_LOCK_SHA256" \
    && test -n "$BYQ_DSH_BUILD_COMPATIBILITY_FAMILY" \
    && test -n "$BYQ_DSH_BUILD_ADAPTER_PROFILE_PATH" \
    && test -n "$BYQ_DSH_BUILD_ADAPTER_PROFILE_SHA256" \
    && test -n "$BYQ_DSH_BUILD_ADAPTER_PROFILE_IDENTITY_PATH" \
    && test -n "$BYQ_DSH_BUILD_ADAPTER_PROFILE_IDENTITY_SHA256" \
    && test -n "$BYQ_DSH_BUILD_ADAPTER_RELEASE_IDENTITY_PATH" \
    && test -n "$BYQ_DSH_BUILD_ADAPTER_RELEASE_IDENTITY_SHA256" \
    && test -n "$BYQ_DSH_BUILD_ORDINARY_RUNNER_PROFILE_PATH" \
    && test -n "$BYQ_DSH_BUILD_ORDINARY_RUNNER_PROFILE_SHA256" \
    && test -n "$BYQ_DSH_BUILD_ORDINARY_RUNNER_PROFILE_IDENTITY_PATH" \
    && test -n "$BYQ_DSH_BUILD_ORDINARY_RUNNER_PROFILE_IDENTITY_SHA256" \
    && test -n "$BYQ_DSH_BUILD_ORDINARY_RUNNER_RELEASE_IDENTITY_PATH" \
    && test -n "$BYQ_DSH_BUILD_ORDINARY_RUNNER_RELEASE_IDENTITY_SHA256" \
    && test -n "$BYQ_DSH_BUILD_JUDGMENT_RUNNER_PROFILE_PATH" \
    && test -n "$BYQ_DSH_BUILD_JUDGMENT_RUNNER_PROFILE_SHA256" \
    && test -n "$BYQ_DSH_BUILD_JUDGMENT_RUNNER_PROFILE_IDENTITY_PATH" \
    && test -n "$BYQ_DSH_BUILD_JUDGMENT_RUNNER_PROFILE_IDENTITY_SHA256"

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git build-essential python3 \
    && rm -rf /var/lib/apt/lists/*

# Authoritative build-input verification for every role before any network use.
# The three verifications reuse the existing acp_build.py contract; only the
# role-generic arguments differ per role. A missing or mismatched value aborts
# the build for that role.
RUN set -e; \
    BYQ_DSH_BUILD_PROFILE_PATH="$BYQ_DSH_BUILD_ADAPTER_PROFILE_PATH" \
    BYQ_DSH_BUILD_PROFILE_SHA256="$BYQ_DSH_BUILD_ADAPTER_PROFILE_SHA256" \
    BYQ_DSH_BUILD_PROFILE_IDENTITY_PATH="$BYQ_DSH_BUILD_ADAPTER_PROFILE_IDENTITY_PATH" \
    BYQ_DSH_BUILD_PROFILE_IDENTITY_SHA256="$BYQ_DSH_BUILD_ADAPTER_PROFILE_IDENTITY_SHA256" \
    BYQ_DSH_BUILD_RELEASE_IDENTITY_PATH="$BYQ_DSH_BUILD_ADAPTER_RELEASE_IDENTITY_PATH" \
    BYQ_DSH_BUILD_RELEASE_IDENTITY_SHA256="$BYQ_DSH_BUILD_ADAPTER_RELEASE_IDENTITY_SHA256" \
    python3 /opt/byq-authoritative/scripts/dsh/acp_build.py \
        --verify-build-inputs --role adapter --root /opt/byq-authoritative; \
    BYQ_DSH_BUILD_PROFILE_PATH="$BYQ_DSH_BUILD_ORDINARY_RUNNER_PROFILE_PATH" \
    BYQ_DSH_BUILD_PROFILE_SHA256="$BYQ_DSH_BUILD_ORDINARY_RUNNER_PROFILE_SHA256" \
    BYQ_DSH_BUILD_PROFILE_IDENTITY_PATH="$BYQ_DSH_BUILD_ORDINARY_RUNNER_PROFILE_IDENTITY_PATH" \
    BYQ_DSH_BUILD_PROFILE_IDENTITY_SHA256="$BYQ_DSH_BUILD_ORDINARY_RUNNER_PROFILE_IDENTITY_SHA256" \
    BYQ_DSH_BUILD_RELEASE_IDENTITY_PATH="$BYQ_DSH_BUILD_ORDINARY_RUNNER_RELEASE_IDENTITY_PATH" \
    BYQ_DSH_BUILD_RELEASE_IDENTITY_SHA256="$BYQ_DSH_BUILD_ORDINARY_RUNNER_RELEASE_IDENTITY_SHA256" \
    python3 /opt/byq-authoritative/scripts/dsh/acp_build.py \
        --verify-build-inputs --role ordinary_runner --root /opt/byq-authoritative; \
    BYQ_DSH_BUILD_PROFILE_PATH="$BYQ_DSH_BUILD_JUDGMENT_RUNNER_PROFILE_PATH" \
    BYQ_DSH_BUILD_PROFILE_SHA256="$BYQ_DSH_BUILD_JUDGMENT_RUNNER_PROFILE_SHA256" \
    BYQ_DSH_BUILD_PROFILE_IDENTITY_PATH="$BYQ_DSH_BUILD_JUDGMENT_RUNNER_PROFILE_IDENTITY_PATH" \
    BYQ_DSH_BUILD_PROFILE_IDENTITY_SHA256="$BYQ_DSH_BUILD_JUDGMENT_RUNNER_PROFILE_IDENTITY_SHA256" \
    python3 /opt/byq-authoritative/scripts/dsh/acp_build.py \
        --verify-build-inputs --role judgment_runner --root /opt/byq-authoritative

WORKDIR /opt/dsh-runtime
RUN git clone --depth 1 --branch "$BYQ_DSH_BUILD_RELEASE_ID" \
    https://github.com/deepseek-ai/deepseek-harness.git . \
    && test "$(git rev-parse HEAD)" = "$BYQ_DSH_BUILD_SOURCE_COMMIT" \
    && echo "$BYQ_DSH_BUILD_PNPM_LOCK_SHA256  pnpm-lock.yaml" | sha256sum -c -
RUN corepack pnpm install --frozen-lockfile \
    && corepack pnpm run build:native-system \
    && corepack pnpm run build:lib:host
RUN test -f apps/cli/lib/bin.js \
    && git rev-parse HEAD > .byq-source-commit
# Remove the write bit in the discarded builder so the final stage inherits
# read-only root-owned modes through COPY --from, avoiding a second recursive
# chmod/chown layer over the ~2.3GB runtime tree (identical final modes).
RUN chown -R root:root /opt/dsh-runtime \
    && chmod -R a-w /opt/dsh-runtime

FROM node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c

ARG BYQ_DSH_BUILD_RELEASE_ID
ARG BYQ_DSH_BUILD_SOURCE_COMMIT
ARG BYQ_DSH_BUILD_PNPM_LOCK_SHA256
ARG BYQ_DSH_BUILD_COMPATIBILITY_FAMILY
ARG BYQ_DSH_BUILD_ADAPTER_PROFILE_PATH
ARG BYQ_DSH_BUILD_ADAPTER_PROFILE_SHA256
ARG BYQ_DSH_BUILD_ADAPTER_PROFILE_IDENTITY_PATH
ARG BYQ_DSH_BUILD_ADAPTER_PROFILE_IDENTITY_SHA256
ARG BYQ_DSH_BUILD_ADAPTER_RELEASE_IDENTITY_PATH
ARG BYQ_DSH_BUILD_ADAPTER_RELEASE_IDENTITY_SHA256
ARG BYQ_DSH_BUILD_ORDINARY_RUNNER_PROFILE_PATH
ARG BYQ_DSH_BUILD_ORDINARY_RUNNER_PROFILE_SHA256
ARG BYQ_DSH_BUILD_ORDINARY_RUNNER_PROFILE_IDENTITY_PATH
ARG BYQ_DSH_BUILD_ORDINARY_RUNNER_PROFILE_IDENTITY_SHA256
ARG BYQ_DSH_BUILD_ORDINARY_RUNNER_RELEASE_IDENTITY_PATH
ARG BYQ_DSH_BUILD_ORDINARY_RUNNER_RELEASE_IDENTITY_SHA256
ARG BYQ_DSH_BUILD_JUDGMENT_RUNNER_PROFILE_PATH
ARG BYQ_DSH_BUILD_JUDGMENT_RUNNER_PROFILE_SHA256
ARG BYQ_DSH_BUILD_JUDGMENT_RUNNER_PROFILE_IDENTITY_PATH
ARG BYQ_DSH_BUILD_JUDGMENT_RUNNER_PROFILE_IDENTITY_SHA256

# Common, role-neutral image environment only. Role-specific process ownership,
# transport, composition/profile selection and DSH_MAX_TOKENS_AS_SUCCESS are
# supplied per service by Compose so one image cannot force one role's settings
# onto another.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/byq-venv/bin:$PATH \
    BYQ_DSH_RUNTIME_ROOT=/opt/dsh-runtime \
    BYQ_DSH_COMPATIBILITY_RELEASE=${BYQ_DSH_BUILD_COMPATIBILITY_FAMILY} \
    DSH_TELEMETRY_DISABLED=1 \
    DSH_PERMISSION_MODE=read-only

# Adapter runtime (venv). Product/judgment use the system python3 explicitly in
# the dispatcher, so the venv cannot change their interpreter behavior.
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/byq-venv

WORKDIR /app
COPY services/runtime-adapter/requirements.acp-candidate.lock ./requirements.acp-candidate.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.acp-candidate.lock \
    && pip install --no-cache-dir \
       fastapi==0.116.1 httpx==0.28.1 'uvicorn[standard]==0.35.0' pytest==9.0.3 \
    && pip check

COPY --from=official-dsh /opt/dsh-runtime /opt/dsh-runtime

# Adapter application and its contracts (only the adapter executes these).
COPY services/runtime-adapter/app ./app
COPY packages/contracts ./packages/contracts
COPY packages/operations ./packages/operations

# Both ACP profiles/identities and the release identity.
COPY plugins/dsh-byq/profiles/acp-0.2.0-rc.2/byq-product.patch.yml /opt/byq/profiles/byq-product.patch.yml
COPY plugins/dsh-byq/profiles/acp-0.2.0-rc.2/byq-product.identity.json /opt/byq/profiles/byq-product.identity.json
COPY plugins/dsh-byq/profiles/acp-0.2.0-rc.2/byq-research-judgment.patch.yml /opt/byq/profiles/byq-research-judgment.patch.yml
COPY plugins/dsh-byq/profiles/acp-0.2.0-rc.2/byq-research-judgment.identity.json /opt/byq/profiles/byq-research-judgment.identity.json
COPY config/dsh/acp-0.2.0-rc.2.identity.json /opt/byq/releases/deployment.identity.json

# Reviewed runtime plugins and skills (adapter + product load skills; judgment
# disables skill plugins at profile level, so the bytes stay inert for it).
COPY plugins/dsh-byq/runtime/package.json plugins/dsh-byq/runtime/byq-acp-mcp-identity.js plugins/dsh-byq/runtime/byq-continuation-budget.js plugins/dsh-byq/runtime/byq-runtime-time-context.js /opt/byq/runtime/
COPY plugins/dsh-byq/skills /opt/dsh/bundles/dsh-byq/skills

# Runner servers and contract modules, in their original on-image layout so the
# product runner's shared-helper import and sys.path[0] resolution are unchanged.
COPY services/acp_judgment_runner/server.py /opt/byq/acp_judgment_runner/server.py
COPY services/acp_product_runner/server.py /opt/byq/acp_product_runner/server.py
COPY packages/contracts/acp_product_slot.py /opt/byq/acp_product_runner/packages/contracts/acp_product_slot.py
COPY packages/contracts/product_turn_request.py /opt/byq/acp_product_runner/packages/contracts/product_turn_request.py

# Explicit, fail-closed role dispatcher (PID 1 entrypoint).
COPY services/acp_unified/entrypoint.sh /usr/local/bin/byq-acp-entrypoint.sh
RUN chmod 0755 /usr/local/bin/byq-acp-entrypoint.sh

# Fixed official DSH source/lock and profile/identity readback for all roles.
RUN test -x /usr/local/bin/node \
    && test -f /opt/dsh-runtime/apps/cli/lib/bin.js \
    && test "$(cat /opt/dsh-runtime/.byq-source-commit)" = "$BYQ_DSH_BUILD_SOURCE_COMMIT" \
    && test "$(sha256sum /opt/dsh-runtime/pnpm-lock.yaml | cut -d ' ' -f1)" = "$BYQ_DSH_BUILD_PNPM_LOCK_SHA256" \
    && test "$(sha256sum /opt/byq/profiles/byq-product.patch.yml | cut -d ' ' -f1)" = "$BYQ_DSH_BUILD_ADAPTER_PROFILE_SHA256" \
    && test "$(sha256sum /opt/byq/profiles/byq-product.identity.json | cut -d ' ' -f1)" = "$BYQ_DSH_BUILD_ADAPTER_PROFILE_IDENTITY_SHA256" \
    && test "$(sha256sum /opt/byq/releases/deployment.identity.json | cut -d ' ' -f1)" = "$BYQ_DSH_BUILD_ADAPTER_RELEASE_IDENTITY_SHA256" \
    && test "$(sha256sum /opt/byq/profiles/byq-research-judgment.patch.yml | cut -d ' ' -f1)" = "$BYQ_DSH_BUILD_JUDGMENT_RUNNER_PROFILE_SHA256" \
    && test "$(sha256sum /opt/byq/profiles/byq-research-judgment.identity.json | cut -d ' ' -f1)" = "$BYQ_DSH_BUILD_JUDGMENT_RUNNER_PROFILE_IDENTITY_SHA256"

# Users/groups and every role's fixed runtime directories. The runners re-assert
# their own volume perms at startup as root PID 1; the read-only container rootfs
# only needs these paths to exist with a safe default.
RUN groupadd --system --gid 10002 byq \
    && groupadd --system --gid 10005 byq-acp-control \
    && groupadd --system --gid 10006 byq-acp-product-control \
    && useradd --system --uid 10002 --gid 10002 --no-create-home \
       --home-dir /var/lib/byq/dsh-runtime-home --shell /usr/sbin/nologin byq \
    && mkdir -p /opt/byq/acp_product_runner/packages/contracts \
       /opt/byq/acp_judgment_runner /opt/byq/profiles /opt/byq/runtime \
       /opt/byq/releases /var/lib/byq/dsh-sessions/${BYQ_DSH_BUILD_COMPATIBILITY_FAMILY} \
       /var/lib/byq/dsh-runtime-home /var/lib/byq/acp-product-runner-state \
       /var/lib/byq/acp-judgment-sessions /var/lib/byq/acp-runner-state \
       /run/byq-acp-product-runner /run/byq-acp-runner /tmp \
    && chown -R byq:byq /var/lib/byq/dsh-runtime-home \
    && chown root:10002 /var/lib/byq/dsh-sessions/${BYQ_DSH_BUILD_COMPATIBILITY_FAMILY} \
    && chmod 0710 /var/lib/byq/dsh-sessions/${BYQ_DSH_BUILD_COMPATIBILITY_FAMILY} \
    && chmod 0700 /var/lib/byq/acp-product-runner-state /var/lib/byq/acp-runner-state \
       /var/lib/byq/acp-judgment-sessions \
    && chown root:10005 /run/byq-acp-runner \
    && chmod 0710 /run/byq-acp-runner \
    && chown root:10006 /run/byq-acp-product-runner \
    && chmod 0710 /run/byq-acp-product-runner \
    && chmod 1777 /tmp \
    && chown -R root:root /app /opt/byq \
    && chmod -R a-w /app /opt/byq \
    && chmod a-w /opt/dsh-runtime

# Default to the unprivileged byq identity, matching the accepted per-role
# adapter Dockerfile (USER byq, uid/gid 10002). The product/judgment root PID-1
# runners override this back to 0:0 explicitly in Compose, and the adapter
# entrypoint re-validates its effective uid/gid as a fail-closed guard, so a
# service that forgets its `user:` cannot silently launch the adapter as root.
USER byq

WORKDIR /
ENTRYPOINT ["/usr/local/bin/byq-acp-entrypoint.sh"]
