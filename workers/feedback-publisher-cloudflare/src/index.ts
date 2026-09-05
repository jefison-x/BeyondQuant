import { PublicationEvent, REPOSITORY, jsonResponse } from "../../../services/feedback-hub-cloudflare/src/contracts";

interface PublisherEnv {
  HUB: Fetcher;
  BYQ_FEEDBACK_PUBLISHER_TOKEN: string;
  BYQ_FEEDBACK_GITHUB_APP_ID: string;
  BYQ_FEEDBACK_GITHUB_INSTALLATION_ID: string;
  BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY: string;
  BYQ_FEEDBACK_GITHUB_REPOSITORY: string;
}

interface QueueEnvelope {
  schema_version: "feedback-publish-queue.v1";
  event_id: string;
}

interface GitHubIssue {
  id: number | string;
  number: number;
  html_url: string;
  body?: string;
}

export class PublisherError extends Error {
  constructor(public readonly category: string, public readonly retryAfter = 30) {
    super(category);
  }
}

let cachedToken: { value: string; expiresAt: number } | null = null;

function base64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function encodeDerLength(length: number): Uint8Array {
  if (length < 128) return Uint8Array.of(length);
  const bytes: number[] = [];
  for (let value = length; value > 0; value >>= 8) bytes.unshift(value & 0xff);
  return Uint8Array.of(0x80 | bytes.length, ...bytes);
}

function der(tag: number, content: Uint8Array): Uint8Array {
  const length = encodeDerLength(content.length);
  const result = new Uint8Array(1 + length.length + content.length);
  result[0] = tag;
  result.set(length, 1);
  result.set(content, 1 + length.length);
  return result;
}

function concat(...values: Uint8Array[]): Uint8Array {
  const result = new Uint8Array(values.reduce((total, value) => total + value.length, 0));
  let offset = 0;
  for (const value of values) {
    result.set(value, offset);
    offset += value.length;
  }
  return result;
}

export function privateKeyDer(pem: string): Uint8Array {
  const normalized = pem.trim();
  const body = normalized.replace(/-----BEGIN (?:RSA )?PRIVATE KEY-----/, "")
    .replace(/-----END (?:RSA )?PRIVATE KEY-----/, "").replace(/\s/g, "");
  if (!body) throw new PublisherError("authentication_failed");
  const raw = Uint8Array.from(atob(body), (character) => character.charCodeAt(0));
  if (normalized.includes("BEGIN PRIVATE KEY")) return raw;
  if (!normalized.includes("BEGIN RSA PRIVATE KEY")) throw new PublisherError("authentication_failed");
  const version = Uint8Array.of(0x02, 0x01, 0x00);
  const rsaAlgorithm = Uint8Array.of(
    0x30, 0x0d, 0x06, 0x09, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d, 0x01, 0x01, 0x01, 0x05, 0x00
  );
  return der(0x30, concat(version, rsaAlgorithm, der(0x04, raw)));
}

async function githubJwt(env: PublisherEnv, now = Date.now()): Promise<string> {
  const header = base64Url(new TextEncoder().encode(JSON.stringify({ alg: "RS256", typ: "JWT" })));
  const issued = Math.floor(now / 1000) - 30;
  const payload = base64Url(new TextEncoder().encode(JSON.stringify({
    iat: issued, exp: issued + 540, iss: env.BYQ_FEEDBACK_GITHUB_APP_ID
  })));
  const unsigned = `${header}.${payload}`;
  try {
    const keyData = privateKeyDer(env.BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY);
    const key = await crypto.subtle.importKey(
      "pkcs8", keyData.buffer as ArrayBuffer,
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"]
    );
    const signature = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(unsigned));
    return `${unsigned}.${base64Url(new Uint8Array(signature))}`;
  } catch (error) {
    if (error instanceof PublisherError) throw error;
    throw new PublisherError("authentication_failed");
  }
}

export function classifyGitHubStatus(status: number, headers = new Headers()): PublisherError {
  let category = new Map<number, string>([
    [401, "authentication_failed"], [403, "permission_denied"], [404, "repository_unavailable"],
    [410, "issues_disabled"], [422, "validation_rejected"], [429, "rate_limited"]
  ]).get(status) ?? (status >= 500 ? "provider_unavailable" : "validation_rejected");
  if (status === 403 && (headers.has("retry-after") || headers.get("x-ratelimit-remaining") === "0")) category = "rate_limited";
  const parsed = Number(headers.get("retry-after") ?? 30);
  return new PublisherError(category, Number.isFinite(parsed) ? Math.min(Math.max(parsed, 5), 3600) : 30);
}

async function githubRequest(env: PublisherEnv, path: string, init: RequestInit = {}, expected = 200): Promise<unknown> {
  const response = await fetch(`https://api.github.com${path}`, {
    ...init,
    headers: {
      accept: "application/vnd.github+json",
      "content-type": "application/json",
      "user-agent": "BeyondQuant-Feedback-Publisher/2",
      "x-github-api-version": "2022-11-28",
      ...(init.headers ?? {})
    }
  });
  if (response.status !== expected) throw classifyGitHubStatus(response.status, response.headers);
  return response.status === 204 ? {} : response.json();
}

async function installationToken(env: PublisherEnv): Promise<string> {
  if (cachedToken && Date.now() + 120_000 < cachedToken.expiresAt) return cachedToken.value;
  const response = await githubRequest(env,
    `/app/installations/${encodeURIComponent(env.BYQ_FEEDBACK_GITHUB_INSTALLATION_ID)}/access_tokens`, {
      method: "POST",
      body: "{}",
      headers: { authorization: `Bearer ${await githubJwt(env)}` }
    }, 201) as { token?: unknown; expires_at?: unknown };
  if (typeof response.token !== "string" || typeof response.expires_at !== "string") {
    throw new PublisherError("authentication_failed");
  }
  const expiry = Date.parse(response.expires_at);
  if (!Number.isFinite(expiry)) throw new PublisherError("authentication_failed");
  cachedToken = { value: response.token, expiresAt: expiry };
  return response.token;
}

function safe(value: unknown): string {
  return String(value).replaceAll("@", "＠").replaceAll("<!--", "&lt;!--");
}

export function marker(event: PublicationEvent): string {
  return `<!-- byq-feedback:${event.event_id}:${event.snapshot_hash} -->`;
}

export function render(event: PublicationEvent): { title: string; body: string } {
  const content = event.snapshot.public_content;
  const prefix: Record<string, string> = {
    bug: "[Bug]", feature: "[Feature]", performance: "[Performance]", usability: "[UX]", other: "[Feedback]"
  };
  const sections = [`## Summary\n\n${safe(content.description)}`];
  if (content.reproduction_steps.length) {
    sections.push(`## Reproduction\n\n${content.reproduction_steps.map((step, index) => `${index + 1}. ${safe(step)}`).join("\n")}`);
  }
  if (content.expected_behavior) sections.push(`## Expected\n\n${safe(content.expected_behavior)}`);
  if (content.actual_behavior) sections.push(`## Actual\n\n${safe(content.actual_behavior)}`);
  const environment = Object.entries(content.environment);
  if (environment.length) sections.push(`## Environment\n\n${environment.map(([key, value]) => `- ${safe(key)}: \`${safe(value)}\``).join("\n")}`);
  sections.push("_Submitted through BeyondQuant's privacy-reviewed Product Feedback flow._");
  sections.push(marker(event));
  return { title: `${prefix[content.category] ?? "[Feedback]"} ${safe(content.title)}`.slice(0, 256), body: sections.join("\n\n") };
}

async function hubRequest(env: PublisherEnv, path: string, payload: unknown): Promise<Response> {
  return env.HUB.fetch(`https://byq-feedback-hub${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-byq-feedback-publisher-token": env.BYQ_FEEDBACK_PUBLISHER_TOKEN
    },
    body: JSON.stringify(payload)
  });
}

async function claim(env: PublisherEnv, eventId: string, workerId: string): Promise<PublicationEvent | null> {
  const response = await hubRequest(env, `/internal/feedback-publications/${eventId}/claim`, {
    worker_id: workerId, lease_seconds: 60
  });
  if (response.status === 204) return null;
  if (response.status === 409) throw new PublisherError("lease_busy", 60);
  if (!response.ok) throw new PublisherError("hub_unavailable", 60);
  return response.json<PublicationEvent>();
}

async function reconcileOrCreate(env: PublisherEnv, event: PublicationEvent): Promise<GitHubIssue> {
  const token = await installationToken(env);
  const base = `/repos/${REPOSITORY}/issues`;
  const headers = { authorization: `Bearer ${token}` };
  const catalog = await githubRequest(env, `${base}?state=all&per_page=100&page=1`, { headers }) as GitHubIssue[];
  if (!Array.isArray(catalog)) throw new PublisherError("provider_unavailable");
  const matches = catalog.filter((issue) => String(issue.body ?? "").includes(marker(event)));
  if (matches.length > 1) throw new PublisherError("reconciliation_conflict");
  if (matches[0]) return matches[0];
  return githubRequest(env, base, { method: "POST", headers, body: JSON.stringify(render(event)) }, 201) as Promise<GitHubIssue>;
}

async function processMessage(message: Message<QueueEnvelope>, env: PublisherEnv, workerId: string): Promise<void> {
  const body = message.body;
  if (!body || body.schema_version !== "feedback-publish-queue.v1" || !/^feedback_outbox_[0-9a-f]{32}$/.test(body.event_id)) {
    message.ack();
    return;
  }
  let event: PublicationEvent | null;
  try {
    event = await claim(env, body.event_id, workerId);
  } catch (error) {
    const delay = error instanceof PublisherError ? error.retryAfter : 60;
    message.retry({ delaySeconds: delay });
    return;
  }
  if (!event) {
    message.ack();
    return;
  }
  try {
    const issue = await reconcileOrCreate(env, event);
    const number = issue.number;
    const expectedUrl = `https://github.com/${REPOSITORY}/issues/${number}`;
    if (!Number.isInteger(number) || number < 1 || issue.html_url !== expectedUrl || !issue.id) {
      throw new PublisherError("validation_rejected");
    }
    const result = await hubRequest(env, `/internal/feedback-publications/${event.event_id}/complete`, {
      worker_id: workerId,
      lease_fence: event.lease_fence,
      repository: REPOSITORY,
      issue_number: number,
      html_url: expectedUrl,
      provider_identity: String(issue.id)
    });
    if (!result.ok) throw new PublisherError("hub_unavailable", 60);
    message.ack();
  } catch (error) {
    const failure = error instanceof PublisherError ? error : new PublisherError("transport_ambiguous", 60);
    try {
      const result = await hubRequest(env, `/internal/feedback-publications/${event.event_id}/retry`, {
        worker_id: workerId,
        lease_fence: event.lease_fence,
        error_category: failure.category,
        retry_after_seconds: failure.retryAfter
      });
      if (!result.ok) throw new Error("hub result unavailable");
      message.ack();
    } catch {
      message.retry({ delaySeconds: 60 });
    }
  }
}

function configured(env: PublisherEnv): boolean {
  return env.BYQ_FEEDBACK_GITHUB_REPOSITORY === REPOSITORY
    && (env.BYQ_FEEDBACK_PUBLISHER_TOKEN ?? "").length >= 32
    && Boolean(env.BYQ_FEEDBACK_GITHUB_APP_ID)
    && Boolean(env.BYQ_FEEDBACK_GITHUB_INSTALLATION_ID)
    && (env.BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY ?? "").includes("PRIVATE KEY");
}

export default {
  async fetch(request: Request, env: PublisherEnv): Promise<Response> {
    if (new URL(request.url).pathname !== "/healthz") return jsonResponse({ detail: "not found" }, 404);
    return jsonResponse({ service: "feedback-publisher", status: configured(env) ? "ok" : "unconfigured" }, configured(env) ? 200 : 503);
  },
  async queue(batch: MessageBatch<QueueEnvelope>, env: PublisherEnv): Promise<void> {
    if (!configured(env)) {
      for (const message of batch.messages) message.retry({ delaySeconds: 300 });
      return;
    }
    const workerId = `cloudflare-publisher-${crypto.randomUUID().slice(0, 24)}`;
    await Promise.all(batch.messages.map((message) => processMessage(message, env, workerId)));
  }
} satisfies ExportedHandler<PublisherEnv, QueueEnvelope>;
