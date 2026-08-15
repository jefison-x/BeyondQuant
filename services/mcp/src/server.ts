import { createServer, type IncomingMessage, type ServerResponse } from "node:http";

import { toNodeHandler } from "@modelcontextprotocol/node";
import { createMcpHandler, McpServer } from "@modelcontextprotocol/server";

const SERVICE = "beyondquant-mcp";
const VERSION = "0.1.0";
const PORT = Number(process.env.PORT ?? "8300");
const MCP_PATH = "/mcp/v1";
const BACKEND_URL = process.env.BYQ_BACKEND_URL ?? "http://backend:8000";
const MCP_TOKEN = process.env.BYQ_MCP_TOKEN;

if (!MCP_TOKEN) {
  throw new Error("BYQ_MCP_TOKEN is required to start the MCP service");
}

function healthPayload(): Record<string, string> {
  return { service: SERVICE, status: "ok", version: VERSION };
}

function writeJson(response: ServerResponse, statusCode: number, payload: unknown): void {
  const body = JSON.stringify(payload);
  response.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
  });
  response.end(body);
}

function authorized(request: IncomingMessage): boolean {
  return request.headers.authorization === `Bearer ${MCP_TOKEN}`;
}

async function byqHealth(): Promise<{
  content: Array<{ type: "text"; text: string }>;
  isError?: boolean;
}> {
  try {
    const response = await fetch(`${BACKEND_URL}/healthz`);
    const backend = (await response.json()) as Record<string, unknown>;
    const payload = {
      service: SERVICE,
      status: response.ok ? "ok" : "error",
      backend,
    };
    return {
      content: [{ type: "text", text: JSON.stringify(payload) }],
      ...(response.ok ? {} : { isError: true }),
    };
  } catch (error) {
    return {
      content: [
        {
          type: "text",
          text: JSON.stringify({
            service: SERVICE,
            status: "error",
            backend: { status: "unreachable", error: String(error) },
          }),
        },
      ],
      isError: true,
    };
  }
}

function buildServer(): McpServer {
  const server = new McpServer({ name: SERVICE, version: VERSION });
  server.registerTool(
    "byq_health",
    {
      description: "Return BeyondQuant MCP and Backend health status.",
      inputSchema: {},
    },
    byqHealth,
  );
  return server;
}

const handler = toNodeHandler(createMcpHandler(buildServer));

const httpServer = createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", `http://${request.headers.host ?? "localhost"}`);

  if (request.method === "GET" && url.pathname === "/healthz") {
    writeJson(response, 200, healthPayload());
    return;
  }

  if (url.pathname !== MCP_PATH) {
    writeJson(response, 404, { service: SERVICE, status: "not_found" });
    return;
  }

  if (!authorized(request)) {
    response.setHeader("WWW-Authenticate", "Bearer");
    writeJson(response, 401, { service: SERVICE, status: "unauthorized" });
    return;
  }

  await handler(request, response);
});

httpServer.listen(PORT, "0.0.0.0", () => {
  console.log(`${SERVICE} listening on ${MCP_PATH}`);
});

async function shutdown(): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    httpServer.close((error) => (error ? reject(error) : resolve()));
  });
}

process.once("SIGTERM", () => void shutdown().then(() => process.exit(0)));
process.once("SIGINT", () => void shutdown().then(() => process.exit(0)));
