FROM node:24-bookworm-slim

WORKDIR /app

COPY services/mcp/package.json services/mcp/package-lock.json services/mcp/tsconfig.json ./
RUN npm ci

COPY services/mcp/src ./src
COPY services/mcp/tests ./tests
COPY docs/contracts/product-capability-catalog.v1.json /app/product-capability-catalog.v1.json
RUN npm run build

ENV NODE_ENV=production
USER node
EXPOSE 8300

CMD ["node", "dist/src/server.js"]
