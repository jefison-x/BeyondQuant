FROM node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c AS official-dsh

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git build-essential python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/dsh-runtime
RUN git clone --depth 1 --branch dsh-v0.2.0-rc.2 \
    https://github.com/deepseek-ai/deepseek-harness.git . \
    && test "$(git rev-parse HEAD)" = 639ed015397290b3745d163aafe02ffee4aa3f84 \
    && echo '80fe05eae33582ae26839afd05f1965f9b0e4be11034ddf9797af6085d5ba9b1  pnpm-lock.yaml' | sha256sum -c -
RUN corepack pnpm install --frozen-lockfile \
    && corepack pnpm run build:native-system \
    && corepack pnpm run build:lib:host
RUN test -f apps/cli/lib/bin.js \
    && git rev-parse HEAD > .byq-source-commit

FROM node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BYQ_DSH_COMPATIBILITY_RELEASE=dsh-v0.2.0-rc.2-acp \
    BYQ_DSH_PROCESS_OWNERSHIP=workspace-slot \
    BYQ_DSH_COMPOSITION=/opt/byq/profiles/byq-product.patch.yml \
    BYQ_DSH_COMPOSITION_IDENTITY=/opt/byq/profiles/byq-product.identity.json \
    BYQ_DSH_RELEASE_IDENTITY=/opt/byq/releases/deployment.identity.json \
    BYQ_DSH_RUNTIME_ROOT=/opt/dsh-runtime \
    DSH_TELEMETRY_DISABLED=1 \
    DSH_PERMISSION_MODE=read-only \
    DSH_MAX_TOKENS_AS_SUCCESS=false

RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10002 byq \
    && groupadd --system --gid 10006 byq-acp-product-control \
    && useradd --system --uid 10002 --gid 10002 --no-create-home \
       --home-dir /var/lib/byq/dsh-sessions --shell /usr/sbin/nologin byq \
    && mkdir -p /opt/byq/acp_product_runner/packages/contracts \
       /opt/byq/acp_judgment_runner /opt/byq/profiles /opt/byq/runtime \
       /opt/byq/releases /var/lib/byq/dsh-sessions/dsh-v0.2.0-rc.2-acp \
       /var/lib/byq/acp-product-runner-state /run/byq-acp-product-runner /tmp \
    && chown root:10002 /var/lib/byq/dsh-sessions/dsh-v0.2.0-rc.2-acp \
    && chmod 0710 /var/lib/byq/dsh-sessions/dsh-v0.2.0-rc.2-acp \
    && chmod 0700 /var/lib/byq/acp-product-runner-state \
    && chown root:10006 /run/byq-acp-product-runner \
    && chmod 0710 /run/byq-acp-product-runner \
    && chmod 1777 /tmp

COPY --from=official-dsh /opt/dsh-runtime /opt/dsh-runtime
COPY plugins/dsh-byq/profiles/acp-0.2.0-rc.2/byq-product.patch.yml \
    /opt/byq/profiles/byq-product.patch.yml
COPY plugins/dsh-byq/profiles/acp-0.2.0-rc.2/byq-product.identity.json \
    /opt/byq/profiles/byq-product.identity.json
COPY config/dsh/acp-0.2.0-rc.2.identity.json /opt/byq/releases/deployment.identity.json
COPY plugins/dsh-byq/runtime/package.json \
     plugins/dsh-byq/runtime/byq-acp-mcp-identity.js \
     plugins/dsh-byq/runtime/byq-continuation-budget.js \
     plugins/dsh-byq/runtime/byq-runtime-time-context.js /opt/byq/runtime/
COPY plugins/dsh-byq/skills /opt/dsh/bundles/dsh-byq/skills
COPY services/acp_judgment_runner/server.py /opt/byq/acp_judgment_runner/server.py
COPY services/acp_product_runner/server.py /opt/byq/acp_product_runner/server.py
COPY packages/contracts/acp_product_slot.py \
    /opt/byq/acp_product_runner/packages/contracts/acp_product_slot.py

RUN test -x /usr/local/bin/node \
    && test -f /opt/dsh-runtime/apps/cli/lib/bin.js \
    && test "$(cat /opt/dsh-runtime/.byq-source-commit)" = 639ed015397290b3745d163aafe02ffee4aa3f84 \
    && test "$(sha256sum /opt/byq/profiles/byq-product.patch.yml | cut -d ' ' -f1)" = \
       8bd56a0d3120e10c74e0d51eb95adb392232f1535e0aabc61228a72f372a964d \
    && chown -R root:root /opt/byq /opt/dsh-runtime \
    && chmod -R a-w /opt/byq /opt/dsh-runtime

WORKDIR /
ENTRYPOINT ["python3", "/opt/byq/acp_product_runner/server.py"]
