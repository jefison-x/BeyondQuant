FROM node:24-bookworm-slim

ENV DSH_HOME=/opt/dsh \
    NODE_ENV=production

RUN apt-get update \
    && apt-get install --no-install-recommends -y python3 make g++ \
    && npm install --global \
      @deepseek-ai/dsh@0.1.0-rc.6 \
      pnpm@10.12.4 \
    && apt-get purge -y python3 make g++ \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/dsh/bundles \
    && chown -R node:node /opt/dsh

# Selective COPY: Product DSH receives only its runtime bundle, never the BYQ
# repository, worktree, Git metadata, Docker socket, or source-editing tools.
COPY --chown=node:node plugins/dsh-byq /opt/dsh/bundles/dsh-byq

USER node

# Use the rc.6-supported plugin mechanism to create the profile and install
# the official web surface plus the local BYQ configuration bundle.
RUN dsh plugin --profile byq add @deepseek-ai/dsh-web-app@0.1.0-rc.6
RUN dsh plugin --profile byq add /opt/dsh/bundles/dsh-byq

# Build-time composition gate. The token exists only for this command and is
# not persisted as an image environment variable or file.
RUN BYQ_MCP_TOKEN=validation \
    dsh --profile byq --dump-config > /tmp/byq-dsh-config \
    && grep -q '@deepseek-ai/dsh-mcp-client' /tmp/byq-dsh-config \
    && grep -q 'serverName: byq' /tmp/byq-dsh-config \
    && grep -q 'transport: streamable-http' /tmp/byq-dsh-config \
    && rm -f /tmp/byq-dsh-config

# rc.6 intentionally keeps this Web/bootstrap surface container-local. It is
# not the Gateway-to-DSH product runtime interface.
CMD ["dsh", "--profile", "byq", "--host", "127.0.0.1", "--port", "3080"]
