FROM node:24-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NODE_ENV=production \
    BYQ_DSH_RUNTIME_ROOT=/opt/dsh-runtime \
    BYQ_DSH_COMPOSITION=/opt/byq/compositions/byq-product-sdk.cordis.yml \
    BYQ_DSH_COMPOSITION_IDENTITY=/opt/byq/compositions/byq-product-sdk.identity.json \
    DSH_SESSION_ROOT=/var/lib/byq/dsh-sessions

RUN apt-get update \
    && apt-get install --no-install-recommends -y python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/dsh-runtime
COPY services/runtime-adapter/runtime/package.json services/runtime-adapter/runtime/package-lock.json ./
RUN npm ci --omit=optional --ignore-scripts

WORKDIR /app
COPY services/runtime-adapter/pyproject.toml ./
COPY services/runtime-adapter/app ./app
COPY services/runtime-adapter/tests ./tests
COPY packages/contracts ./packages/contracts
RUN python3 -m pip install --break-system-packages --no-cache-dir ".[test]"

ARG BYQ_DSH_COMPOSITION_SOURCE=plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml
ARG BYQ_DSH_IDENTITY_SOURCE=plugins/dsh-byq/compositions/byq-product-sdk.identity.json
COPY ${BYQ_DSH_COMPOSITION_SOURCE} /opt/byq/compositions/byq-product-sdk.cordis.yml
COPY ${BYQ_DSH_IDENTITY_SOURCE} /opt/byq/compositions/byq-product-sdk.identity.json
COPY plugins/dsh-byq/runtime /opt/byq/runtime
COPY services/runtime-adapter/runtime/verify-time-context.mjs /opt/dsh-runtime/verify-time-context.mjs
COPY services/runtime-adapter/runtime/verify-qualified-plugins.mjs /opt/dsh-runtime/verify-qualified-plugins.mjs
COPY plugins/dsh-byq/skills /opt/dsh/bundles/dsh-byq/skills
RUN cd /opt/dsh-runtime \
    && node verify-time-context.mjs \
    && node verify-qualified-plugins.mjs \
    && rm verify-time-context.mjs verify-qualified-plugins.mjs

RUN groupadd --system --gid 10002 byq \
    && useradd --system --uid 10002 --gid byq --no-create-home \
       --home-dir /nonexistent --shell /usr/sbin/nologin byq \
    && mkdir -p /var/lib/byq/dsh-sessions \
    && chown -R byq:byq /var/lib/byq/dsh-sessions

USER byq

CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8400"]
