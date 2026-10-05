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
    DSH_TELEMETRY_DISABLED=1 \
    DSH_PERMISSION_MODE=read-only \
    DSH_MAX_TOKENS_AS_SUCCESS=false

RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10002 byq \
    && groupadd --system --gid 10005 byq-acp-control \
    && useradd --system --uid 10002 --gid 10002 --no-create-home \
       --home-dir /var/lib/byq/acp-judgment-sessions --shell /usr/sbin/nologin byq \
    && mkdir -p /opt/byq/acp_judgment_runner /opt/byq/profiles \
       /var/lib/byq/acp-judgment-sessions /var/lib/byq/acp-runner-state \
       /run/byq-acp-runner /tmp \
    && chown root:10005 /run/byq-acp-runner \
    && chmod 0710 /run/byq-acp-runner \
    && chmod 0555 /opt/byq /opt/byq/profiles /opt/byq/acp_judgment_runner \
    && chmod 1777 /tmp

COPY --from=official-dsh /opt/dsh-runtime /opt/dsh-runtime
COPY plugins/dsh-byq/profiles/acp-0.2.0-rc.2/byq-research-judgment.patch.yml \
    /opt/byq/profiles/byq-research-judgment.patch.yml
COPY plugins/dsh-byq/profiles/acp-0.2.0-rc.2/byq-research-judgment.identity.json \
    /opt/byq/profiles/byq-research-judgment.identity.json
COPY plugins/dsh-byq/runtime/package.json \
     plugins/dsh-byq/runtime/byq-acp-mcp-identity.js \
     plugins/dsh-byq/runtime/byq-continuation-budget.js \
     plugins/dsh-byq/runtime/byq-runtime-time-context.js /opt/byq/runtime/

RUN test -x /usr/local/bin/node \
    && test -f /opt/dsh-runtime/apps/cli/lib/bin.js \
    && test "$(cat /opt/dsh-runtime/.byq-source-commit)" = 639ed015397290b3745d163aafe02ffee4aa3f84 \
    && test -f /opt/byq/profiles/byq-research-judgment.patch.yml \
    && test -f /opt/byq/profiles/byq-research-judgment.identity.json \
    && chown -R root:root /opt/byq /opt/dsh-runtime \
    && chmod -R a-w /opt/byq /opt/dsh-runtime
COPY services/acp_judgment_runner/server.py /opt/byq/acp_judgment_runner/server.py

WORKDIR /
ENTRYPOINT ["python3", "/opt/byq/acp_judgment_runner/server.py"]
