import { DurableObject } from "cloudflare:workers";
import {
  ContractError, HOURLY_LIMIT, IntakeEnvelope, MAX_BYTES, MAX_PUBLISH_ATTEMPTS,
  PublicationEvent, REPOSITORY, canonical, digest, hmacHex, jsonResponse, randomId,
  timingSafeEqual, validateEnvelope
} from "./contracts";
import { adminConsoleAsset } from "./admin-console";

interface HubEnv {
  DB: D1Database;
  INSTALLATION_GATE: DurableObjectNamespace<InstallationGate>;
  FEEDBACK_GATE: DurableObjectNamespace<FeedbackGate>;
  PUBLISH_QUEUE: Queue<{ schema_version: "feedback-publish-queue.v1"; event_id: string }>;
  BYQ_FEEDBACK_HUB_STATUS_SECRET: string;
  BYQ_FEEDBACK_HUB_ADMIN_TOKEN: string;
  BYQ_FEEDBACK_PUBLISHER_TOKEN: string;
  BYQ_FEEDBACK_GITHUB_REPOSITORY: string;
}

interface FeedbackRow {
  receipt_id: string;
  installation_hash: string;
  source_event_hash: string;
  snapshot_json: string;
  snapshot_hash: string;
  fingerprint: string;
  status: string;
  duplicate_of: string | null;
  github_repository: string | null;
  github_issue_number: number | null;
  github_html_url: string | null;
  github_provider_identity: string | null;
  created_at: string;
  updated_at: string;
}

interface OutboxRow {
  event_id: string;
  receipt_id: string;
  snapshot_json: string;
  snapshot_hash: string;
  state: string;
  attempt: number;
  next_attempt_at: string;
  lease_owner: string | null;
  lease_expires_at: string | null;
  lease_fence: number;
  last_error_category: string | null;
  created_at: string;
  updated_at: string;
}

const RECEIPT = /^central_feedback_[0-9a-f]{32}$/;
const OUTBOX_EVENT = /^feedback_outbox_[0-9a-f]{32}$/;
const ADMIN_SESSION_COOKIE = "__Host-byq_feedback_admin";
const ADMIN_SESSION_SECONDS = 8 * 60 * 60;
const ADMIN_UI_REQUEST_HEADER = "x-byq-feedback-admin-request";
const ADMIN_UI_REQUEST_VALUE = "ui-v1";
const PUBLIC_STATUSES = new Set(["received", "triaged", "accepted", "rejected", "duplicate", "publishing", "published"]);
const TERMINAL_ERRORS = new Set([
  "authentication_failed", "permission_denied", "repository_unavailable", "issues_disabled",
  "validation_rejected", "reconciliation_conflict"
]);
const PUBLISHER_ERRORS = new Set([
  ...TERMINAL_ERRORS, "rate_limited", "provider_unavailable", "hub_unavailable", "transport_ambiguous"
]);

function hasOnlyKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  const keys = new Set(allowed);
  return Object.keys(value).every((key) => keys.has(key));
}

function configurationError(env: HubEnv): string | null {
  if (env.BYQ_FEEDBACK_GITHUB_REPOSITORY !== REPOSITORY) return "fixed repository is invalid";
  if ((env.BYQ_FEEDBACK_HUB_STATUS_SECRET ?? "").length < 32) return "status secret is invalid";
  if ((env.BYQ_FEEDBACK_HUB_ADMIN_TOKEN ?? "").length < 32) return "admin token is invalid";
  if ((env.BYQ_FEEDBACK_PUBLISHER_TOKEN ?? "").length < 32) return "publisher token is invalid";
  return null;
}

function bearer(request: Request, expected: string): boolean {
  const raw = request.headers.get("authorization") ?? "";
  return raw.startsWith("Bearer ") && timingSafeEqual(raw.slice(7), expected);
}

function cookieValue(request: Request, name: string): string | null {
  for (const item of (request.headers.get("cookie") ?? "").split(";")) {
    const separator = item.indexOf("=");
    if (separator > 0 && item.slice(0, separator).trim() === name) return item.slice(separator + 1).trim();
  }
  return null;
}

async function adminSessionSignature(env: HubEnv, expires: number): Promise<string> {
  return hmacHex(env.BYQ_FEEDBACK_HUB_ADMIN_TOKEN, `central-feedback-admin-session.v1:${expires}`);
}

async function adminSessionAuthenticated(request: Request, env: HubEnv): Promise<boolean> {
  const value = cookieValue(request, ADMIN_SESSION_COOKIE);
  if (!value) return false;
  const match = value.match(/^v1\.(\d{10})\.([0-9a-f]{64})$/);
  if (!match) return false;
  const expires = Number(match[1]);
  const now = Math.floor(Date.now() / 1000);
  if (!Number.isInteger(expires) || expires <= now || expires > now + ADMIN_SESSION_SECONDS) return false;
  return timingSafeEqual(match[2]!, await adminSessionSignature(env, expires));
}

async function adminAuthentication(request: Request, env: HubEnv): Promise<"bearer" | "session" | null> {
  if (request.headers.has("authorization")) {
    return bearer(request, env.BYQ_FEEDBACK_HUB_ADMIN_TOKEN) ? "bearer" : null;
  }
  return await adminSessionAuthenticated(request, env) ? "session" : null;
}

function sameOriginUiRequest(request: Request): boolean {
  return request.headers.get("origin") === new URL(request.url).origin
    && request.headers.get(ADMIN_UI_REQUEST_HEADER) === ADMIN_UI_REQUEST_VALUE;
}

function adminSessionCookie(expires: number, signature: string): string {
  return `${ADMIN_SESSION_COOKIE}=v1.${expires}.${signature}; Path=/; Max-Age=${ADMIN_SESSION_SECONDS}; Secure; HttpOnly; SameSite=Strict`;
}

function clearAdminSessionCookie(): string {
  return `${ADMIN_SESSION_COOKIE}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict`;
}

async function createAdminSession(request: Request, env: HubEnv): Promise<Response> {
  if (!sameOriginUiRequest(request)) return jsonResponse({ detail: "admin session origin is invalid" }, 403);
  const payload = await requestJson(request, 1024);
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)
      || !hasOnlyKeys(payload as Record<string, unknown>, ["token"])) {
    return jsonResponse({ detail: "admin session request is invalid" }, 422);
  }
  const token = (payload as Record<string, unknown>).token;
  if (typeof token !== "string" || token.length < 32 || token.length > 512
      || !timingSafeEqual(token, env.BYQ_FEEDBACK_HUB_ADMIN_TOKEN)) {
    return jsonResponse({ detail: "administrator token is invalid" }, 401);
  }
  const expires = Math.floor(Date.now() / 1000) + ADMIN_SESSION_SECONDS;
  const response = jsonResponse({
    schema_version: "central-feedback-admin-session.v1",
    authenticated: true,
    expires_at: new Date(expires * 1000).toISOString()
  });
  response.headers.set("set-cookie", adminSessionCookie(expires, await adminSessionSignature(env, expires)));
  return response;
}

async function inspectAdminSession(request: Request, env: HubEnv): Promise<Response> {
  return jsonResponse({
    schema_version: "central-feedback-admin-session.v1",
    authenticated: await adminSessionAuthenticated(request, env)
  });
}

function deleteAdminSession(request: Request): Response {
  if (!sameOriginUiRequest(request)) return jsonResponse({ detail: "admin session origin is invalid" }, 403);
  const response = jsonResponse({ schema_version: "central-feedback-admin-session.v1", authenticated: false });
  response.headers.set("set-cookie", clearAdminSessionCookie());
  return response;
}

function publisherAuthenticated(request: Request, env: HubEnv): boolean {
  return timingSafeEqual(request.headers.get("x-byq-feedback-publisher-token") ?? "", env.BYQ_FEEDBACK_PUBLISHER_TOKEN);
}

async function requestJson(request: Request, limit = MAX_BYTES): Promise<unknown> {
  const declared = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(declared) && declared > limit) throw new ContractError(413, "request is too large");
  const bytes = await request.arrayBuffer();
  if (bytes.byteLength > limit) throw new ContractError(413, "request is too large");
  try {
    return JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    throw new ContractError(400, "request JSON is invalid");
  }
}

function statusProjection(row: Pick<FeedbackRow, "receipt_id" | "status" | "github_repository" | "github_issue_number" | "github_html_url">) {
  return {
    schema_version: "central-feedback-status.v1",
    receipt_id: row.receipt_id,
    status: row.status,
    github_issue: row.status === "published" ? {
      repository: row.github_repository,
      issue_number: row.github_issue_number,
      html_url: row.github_html_url
    } : null
  };
}

async function statusToken(env: HubEnv, receipt: string): Promise<string> {
  return hmacHex(env.BYQ_FEEDBACK_HUB_STATUS_SECRET, `feedback-status:${receipt}`);
}

async function auditStatement(env: HubEnv, receipt: string, action: string, source: string | null,
                              target: string, detail: unknown, timestamp: string): Promise<D1PreparedStatement> {
  return env.DB.prepare(`INSERT INTO central_feedback_audit
    (audit_id,receipt_id,action,actor,from_status,to_status,detail_json,created_at)
    VALUES(?,?,?,?,?,?,?,?)`).bind(
    randomId("hub_audit_"), receipt, action, "central-hub", source, target, canonical(detail), timestamp
  );
}

export class InstallationGate extends DurableObject<HubEnv> {
  constructor(ctx: DurableObjectState, env: HubEnv) {
    super(ctx, env);
  }

  async fetch(request: Request): Promise<Response> {
    const body = await request.json() as {
      envelope: IntakeEnvelope;
      installation_hash: string;
      event_hash: string;
    };
    const { envelope, installation_hash: installationHash, event_hash: eventHash } = body;
    const existing = await this.env.DB.prepare(`SELECT receipt_id,snapshot_hash,status,github_repository,
      github_issue_number,github_html_url FROM central_feedback
      WHERE installation_hash=? AND source_event_hash=?`).bind(installationHash, eventHash).first<FeedbackRow>();
    if (existing) {
      if (!timingSafeEqual(existing.snapshot_hash, envelope.snapshot_hash)) {
        return jsonResponse({ detail: "idempotency conflict" }, 409);
      }
      return jsonResponse({
        schema_version: "central-feedback-receipt.v1",
        receipt_id: existing.receipt_id,
        status_token: await statusToken(this.env, existing.receipt_id),
        status: existing.status
      }, 202);
    }

    const nowMs = Date.now();
    const rate = await this.ctx.storage.transaction(async (transaction) => {
      const entries = await transaction.list<number>({ prefix: "event:" });
      const expired: string[] = [];
      let recent = 0;
      for (const [key, timestamp] of entries) {
        if (timestamp < nowMs - 3_600_000) expired.push(key);
        else recent += 1;
      }
      if (expired.length) await transaction.delete(expired);
      const key = `event:${eventHash}`;
      if (entries.has(key)) return "reserved";
      if (recent >= HOURLY_LIMIT) return "limited";
      await transaction.put(key, nowMs);
      return "accepted";
    });
    if (rate === "limited") return jsonResponse({ detail: "rate limit reached" }, 429);

    const timestamp = new Date().toISOString();
    const receipt = randomId("central_feedback_");
    const content = envelope.snapshot.public_content;
    const fingerprint = await digest({
      category: content.category,
      component: content.component,
      title: content.title.trim().toLocaleLowerCase(),
      description: content.description.trim().toLocaleLowerCase()
    });
    try {
      await this.env.DB.batch([
        this.env.DB.prepare(`INSERT INTO central_feedback
          (receipt_id,installation_hash,source_event_hash,snapshot_json,snapshot_hash,fingerprint,status,created_at,updated_at)
          VALUES(?,?,?,?,?,?,'received',?,?)`).bind(
          receipt, installationHash, eventHash, canonical(envelope.snapshot), envelope.snapshot_hash,
          fingerprint, timestamp, timestamp
        ),
        await auditStatement(this.env, receipt, "receive", null, "received", { snapshot_hash: envelope.snapshot_hash }, timestamp)
      ]);
    } catch (error) {
      const raced = await this.env.DB.prepare(`SELECT receipt_id,snapshot_hash,status FROM central_feedback
        WHERE installation_hash=? AND source_event_hash=?`).bind(installationHash, eventHash).first<FeedbackRow>();
      if (!raced || !timingSafeEqual(raced.snapshot_hash, envelope.snapshot_hash)) throw error;
      return jsonResponse({
        schema_version: "central-feedback-receipt.v1",
        receipt_id: raced.receipt_id,
        status_token: await statusToken(this.env, raced.receipt_id),
        status: raced.status
      }, 202);
    }
    return jsonResponse({
      schema_version: "central-feedback-receipt.v1",
      receipt_id: receipt,
      status_token: await statusToken(this.env, receipt),
      status: "received"
    }, 202);
  }
}

export class FeedbackGate extends DurableObject<HubEnv> {
  constructor(ctx: DurableObjectState, env: HubEnv) {
    super(ctx, env);
  }

  async fetch(request: Request): Promise<Response> {
    const body = await request.json() as Record<string, unknown>;
    const operation = String(body.operation ?? "");
    if (operation === "moderate") return this.moderate(body);
    if (operation === "claim") return this.claim(body);
    if (operation === "complete") return this.complete(body);
    if (operation === "retry") return this.retry(body);
    return jsonResponse({ detail: "operation is invalid" }, 422);
  }

  private async moderate(body: Record<string, unknown>): Promise<Response> {
    const receipt = String(body.receipt ?? "");
    const action = String(body.action ?? "");
    const rationale = body.rationale;
    if (!RECEIPT.test(receipt) || typeof rationale !== "string" || rationale.length < 3 || rationale.length > 1000) {
      return jsonResponse({ detail: "moderation request is invalid" }, 422);
    }
    const transitions: Record<string, [string, string]> = {
      triage: ["received", "triaged"], accept: ["triaged", "accepted"],
      reject: ["triaged", "rejected"], duplicate: ["triaged", "duplicate"]
    };
    const transition = transitions[action];
    if (!transition) return jsonResponse({ detail: "action is invalid" }, 422);
    const [source, target] = transition;
    const row = await this.env.DB.prepare("SELECT * FROM central_feedback WHERE receipt_id=?")
      .bind(receipt).first<FeedbackRow>();
    if (!row) return jsonResponse({ detail: "feedback not found" }, 404);
    if (row.status !== source) return jsonResponse({ detail: "feedback state changed" }, 409);

    let duplicate: string | null = null;
    if (action === "duplicate") {
      duplicate = typeof body.duplicate_of === "string" ? body.duplicate_of : null;
      if (!duplicate || !RECEIPT.test(duplicate) || duplicate === receipt
          || !(await this.env.DB.prepare("SELECT receipt_id FROM central_feedback WHERE receipt_id=?").bind(duplicate).first())) {
        return jsonResponse({ detail: "duplicate target is invalid" }, 422);
      }
    }
    const timestamp = new Date().toISOString();
    const statements: D1PreparedStatement[] = [
      this.env.DB.prepare("UPDATE central_feedback SET status=?,duplicate_of=?,updated_at=? WHERE receipt_id=? AND status=?")
        .bind(target, duplicate, timestamp, receipt, source)
    ];
    if (action === "accept") {
      const snapshot = JSON.parse(row.snapshot_json) as IntakeEnvelope["snapshot"];
      const publication = {
        schema_version: "feedback-publication.v1",
        public_content: snapshot.public_content,
        redactions: snapshot.redactions
      };
      statements.push(this.env.DB.prepare(`INSERT INTO central_feedback_outbox
        (event_id,receipt_id,snapshot_json,snapshot_hash,state,attempt,next_attempt_at,lease_fence,created_at,updated_at)
        VALUES(?,?,?,?,'queued',0,?,0,?,?)`).bind(
        randomId("feedback_outbox_"), receipt, canonical(publication), await digest(publication), timestamp, timestamp, timestamp
      ));
    }
    statements.push(await auditStatement(this.env, receipt, action, source, target,
      { rationale, duplicate_of: duplicate }, timestamp));
    const result = await this.env.DB.batch(statements);
    if ((result[0]?.meta.changes ?? 0) !== 1) return jsonResponse({ detail: "feedback state changed" }, 409);
    return jsonResponse(statusProjection({ ...row, status: target }));
  }

  private async claim(body: Record<string, unknown>): Promise<Response> {
    const eventId = String(body.event_id ?? "");
    const worker = String(body.worker_id ?? "");
    const seconds = Number(body.lease_seconds ?? 60);
    if (!OUTBOX_EVENT.test(eventId) || worker.length < 3 || worker.length > 80
        || !Number.isInteger(seconds) || seconds < 15 || seconds > 300) {
      return jsonResponse({ detail: "claim request is invalid" }, 422);
    }
    const row = await this.env.DB.prepare("SELECT * FROM central_feedback_outbox WHERE event_id=?")
      .bind(eventId).first<OutboxRow>();
    if (!row) return jsonResponse({ detail: "publication not found" }, 404);
    if (["published", "failed_terminal"].includes(row.state)) return new Response(null, { status: 204 });
    if (row.attempt >= MAX_PUBLISH_ATTEMPTS) {
      await this.env.DB.prepare("UPDATE central_feedback_outbox SET state='failed_terminal',last_error_category='retry_exhausted',updated_at=? WHERE event_id=?")
        .bind(new Date().toISOString(), eventId).run();
      return new Response(null, { status: 204 });
    }
    const now = new Date();
    const eligible = row.state === "enqueued"
      || (row.state === "publishing" && row.lease_expires_at !== null && row.lease_expires_at < now.toISOString());
    if (!eligible) return jsonResponse({ detail: "publication is not claimable" }, 409);
    const expiry = new Date(now.getTime() + seconds * 1000).toISOString();
    const timestamp = now.toISOString();
    const updated = await this.env.DB.prepare(`UPDATE central_feedback_outbox SET state='publishing',attempt=attempt+1,
      lease_owner=?,lease_expires_at=?,lease_fence=lease_fence+1,updated_at=?
      WHERE event_id=? AND state=? AND lease_fence=?`).bind(
      worker, expiry, timestamp, eventId, row.state, row.lease_fence
    ).run();
    if ((updated.meta.changes ?? 0) !== 1) return jsonResponse({ detail: "publication lease changed" }, 409);
    await this.env.DB.prepare("UPDATE central_feedback SET status='publishing',updated_at=? WHERE receipt_id=?")
      .bind(timestamp, row.receipt_id).run();
    return jsonResponse({
      event_id: eventId,
      feedback_id: row.receipt_id,
      publication_id: row.receipt_id,
      snapshot_hash: row.snapshot_hash,
      snapshot: JSON.parse(row.snapshot_json),
      attempt: row.attempt + 1,
      lease_fence: row.lease_fence + 1,
      lease_expires_at: expiry
    } satisfies PublicationEvent);
  }

  private async complete(body: Record<string, unknown>): Promise<Response> {
    const eventId = String(body.event_id ?? "");
    const worker = String(body.worker_id ?? "");
    const fence = Number(body.lease_fence);
    const issue = Number(body.issue_number);
    const repository = String(body.repository ?? "");
    const expectedUrl = `https://github.com/${REPOSITORY}/issues/${issue}`;
    if (!OUTBOX_EVENT.test(eventId) || worker.length < 3 || worker.length > 80
        || !Number.isInteger(fence) || fence < 1 || repository !== REPOSITORY
        || !Number.isInteger(issue) || issue < 1 || body.html_url !== expectedUrl
        || typeof body.provider_identity !== "string" || body.provider_identity.length < 1
        || body.provider_identity.length > 100) {
      return jsonResponse({ detail: "publication result is invalid" }, 422);
    }
    const row = await this.env.DB.prepare("SELECT * FROM central_feedback_outbox WHERE event_id=?")
      .bind(eventId).first<OutboxRow>();
    if (!row) return jsonResponse({ detail: "publication not found" }, 404);
    if (row.state !== "publishing" || row.lease_owner !== worker || row.lease_fence !== fence) {
      return jsonResponse({ detail: "publication lease is stale" }, 409);
    }
    const timestamp = new Date().toISOString();
    const result = await this.env.DB.batch([
      this.env.DB.prepare(`UPDATE central_feedback_outbox SET state='published',lease_owner=NULL,
        lease_expires_at=NULL,updated_at=? WHERE event_id=? AND state='publishing' AND lease_owner=? AND lease_fence=?`)
        .bind(timestamp, eventId, worker, fence),
      this.env.DB.prepare(`UPDATE central_feedback SET status='published',github_repository=?,github_issue_number=?,
        github_html_url=?,github_provider_identity=?,updated_at=? WHERE receipt_id=?`).bind(
        REPOSITORY, issue, expectedUrl, body.provider_identity, timestamp, row.receipt_id
      ),
      await auditStatement(this.env, row.receipt_id, "publish", "publishing", "published",
        { event_id: eventId, issue_number: issue }, timestamp)
    ]);
    if ((result[0]?.meta.changes ?? 0) !== 1) return jsonResponse({ detail: "publication lease is stale" }, 409);
    return jsonResponse({ schema_version: "feedback-publisher-result.v1", status: "published", issue_number: issue, html_url: expectedUrl });
  }

  private async retry(body: Record<string, unknown>): Promise<Response> {
    const eventId = String(body.event_id ?? "");
    const worker = String(body.worker_id ?? "");
    const fence = Number(body.lease_fence);
    const category = String(body.error_category ?? "provider_unavailable");
    const retrySeconds = Number(body.retry_after_seconds ?? 30);
    if (!OUTBOX_EVENT.test(eventId) || worker.length < 3 || worker.length > 80
        || !Number.isInteger(fence) || fence < 1 || !PUBLISHER_ERRORS.has(category)
        || !Number.isInteger(retrySeconds) || retrySeconds < 5 || retrySeconds > 3600) {
      return jsonResponse({ detail: "publication retry is invalid" }, 422);
    }
    const row = await this.env.DB.prepare("SELECT * FROM central_feedback_outbox WHERE event_id=?")
      .bind(eventId).first<OutboxRow>();
    if (!row) return jsonResponse({ detail: "publication not found" }, 404);
    if (row.state !== "publishing" || row.lease_owner !== worker || row.lease_fence !== fence) {
      return jsonResponse({ detail: "publication lease is stale" }, 409);
    }
    const terminal = TERMINAL_ERRORS.has(category) || row.attempt >= MAX_PUBLISH_ATTEMPTS;
    const state = terminal ? "failed_terminal" : "retry_wait";
    const timestamp = new Date().toISOString();
    const next = new Date(Date.now() + retrySeconds * 1000).toISOString();
    const result = await this.env.DB.batch([
      this.env.DB.prepare(`UPDATE central_feedback_outbox SET state=?,next_attempt_at=?,lease_owner=NULL,
        lease_expires_at=NULL,last_error_category=?,updated_at=?
        WHERE event_id=? AND state='publishing' AND lease_owner=? AND lease_fence=?`).bind(
        state, next, category, timestamp, eventId, worker, fence
      ),
      this.env.DB.prepare("UPDATE central_feedback SET status='accepted',updated_at=? WHERE receipt_id=?")
        .bind(timestamp, row.receipt_id),
      await auditStatement(this.env, row.receipt_id, "publish_retry", "publishing", "accepted",
        { event_id: eventId, error_category: category, terminal }, timestamp)
    ]);
    if ((result[0]?.meta.changes ?? 0) !== 1) return jsonResponse({ detail: "publication lease is stale" }, 409);
    return jsonResponse({ schema_version: "feedback-publisher-result.v1", status: state, error_category: category, attempt: row.attempt });
  }
}

async function intake(request: Request, env: HubEnv): Promise<Response> {
  const envelope = await validateEnvelope(await requestJson(request));
  const installationHash = await hmacHex(env.BYQ_FEEDBACK_HUB_STATUS_SECRET, envelope.installation_id);
  const eventHash = await hmacHex(env.BYQ_FEEDBACK_HUB_STATUS_SECRET, envelope.event_id);
  const gate = env.INSTALLATION_GATE.getByName(installationHash);
  return gate.fetch("https://installation-gate/intake", {
    method: "POST",
    body: JSON.stringify({ envelope, installation_hash: installationHash, event_hash: eventHash })
  });
}

async function publicStatus(request: Request, env: HubEnv, receipt: string): Promise<Response> {
  if (!RECEIPT.test(receipt)) return jsonResponse({ detail: "feedback not found" }, 404);
  if (!bearer(request, await statusToken(env, receipt))) return jsonResponse({ detail: "feedback status authentication failed" }, 401);
  const row = await env.DB.prepare(`SELECT receipt_id,status,github_repository,github_issue_number,github_html_url
    FROM central_feedback WHERE receipt_id=?`).bind(receipt).first<FeedbackRow>();
  return row ? jsonResponse(statusProjection(row)) : jsonResponse({ detail: "feedback not found" }, 404);
}

async function adminList(url: URL, env: HubEnv): Promise<Response> {
  const status = url.searchParams.get("status") ?? "received";
  const allowed = new Set([...PUBLIC_STATUSES, "all"]);
  if (!allowed.has(status)) return jsonResponse({ detail: "status is invalid" }, 422);
  const limit = Math.min(Math.max(Number(url.searchParams.get("limit") ?? 20), 1), 100);
  const offset = Math.max(Number(url.searchParams.get("offset") ?? 0), 0);
  if (!Number.isInteger(limit) || !Number.isInteger(offset)) return jsonResponse({ detail: "pagination is invalid" }, 422);
  const where = status === "all" ? "1=1" : "status=?";
  const countStatement = status === "all"
    ? env.DB.prepare("SELECT COUNT(*) AS count FROM central_feedback")
    : env.DB.prepare("SELECT COUNT(*) AS count FROM central_feedback WHERE status=?").bind(status);
  const listStatement = status === "all"
    ? env.DB.prepare(`SELECT receipt_id,status,snapshot_json,snapshot_hash,fingerprint,duplicate_of,
      github_repository,github_issue_number,github_html_url,created_at,updated_at FROM central_feedback
      WHERE ${where} ORDER BY created_at,receipt_id LIMIT ? OFFSET ?`).bind(limit, offset)
    : env.DB.prepare(`SELECT receipt_id,status,snapshot_json,snapshot_hash,fingerprint,duplicate_of,
      github_repository,github_issue_number,github_html_url,created_at,updated_at FROM central_feedback
      WHERE ${where} ORDER BY created_at,receipt_id LIMIT ? OFFSET ?`).bind(status, limit, offset);
  const [count, rows] = await env.DB.batch([countStatement, listStatement]);
  const rawItems = (rows?.results ?? []) as Array<Record<string, unknown>>;
  const items = rawItems.map((item) => ({
    ...item,
    snapshot_json: JSON.parse(String(item.snapshot_json))
  }));
  const countRow = (count?.results[0] ?? {}) as Record<string, unknown>;
  return jsonResponse({
    schema_version: "central-feedback-admin-catalog.v1",
    items,
    total: Number(countRow.count ?? 0),
    limit,
    offset
  });
}

async function moderate(request: Request, env: HubEnv, receipt: string, action: string): Promise<Response> {
  const payload = await requestJson(request, 4 * 1024);
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    return jsonResponse({ detail: "moderation request is invalid" }, 422);
  }
  const gate = env.FEEDBACK_GATE.getByName(receipt);
  const values = payload as Record<string, unknown>;
  const allowed = action === "duplicate" ? ["rationale", "duplicate_of"] : ["rationale"];
  if (!hasOnlyKeys(values, allowed)) return jsonResponse({ detail: "moderation request is invalid" }, 422);
  return gate.fetch("https://feedback-gate/moderate", {
    method: "POST",
    body: JSON.stringify({ ...values, operation: "moderate", receipt, action })
  });
}

async function publisherMutation(request: Request, env: HubEnv, eventId: string, operation: string): Promise<Response> {
  if (!OUTBOX_EVENT.test(eventId)) return jsonResponse({ detail: "publication not found" }, 404);
  const outbox = await env.DB.prepare("SELECT receipt_id FROM central_feedback_outbox WHERE event_id=?")
    .bind(eventId).first<{ receipt_id: string }>();
  if (!outbox) return jsonResponse({ detail: "publication not found" }, 404);
  const body = await requestJson(request, 8 * 1024);
  if (typeof body !== "object" || body === null || Array.isArray(body)) return jsonResponse({ detail: "publisher request is invalid" }, 422);
  const values = body as Record<string, unknown>;
  const allowed: Record<string, readonly string[]> = {
    claim: ["worker_id", "lease_seconds"],
    complete: ["worker_id", "lease_fence", "repository", "issue_number", "html_url", "provider_identity"],
    retry: ["worker_id", "lease_fence", "error_category", "retry_after_seconds"]
  };
  if (!hasOnlyKeys(values, allowed[operation] ?? [])) return jsonResponse({ detail: "publisher request is invalid" }, 422);
  return env.FEEDBACK_GATE.getByName(outbox.receipt_id).fetch("https://feedback-gate/publisher", {
    method: "POST",
    body: JSON.stringify({ ...values, operation, event_id: eventId })
  });
}

export async function dispatchDue(env: HubEnv): Promise<void> {
  const now = new Date().toISOString();
  const due = await env.DB.prepare(`SELECT event_id,state,lease_fence FROM central_feedback_outbox
    WHERE state IN ('queued','retry_wait','enqueued','dispatching') AND next_attempt_at<=?
    ORDER BY next_attempt_at,event_id LIMIT 25`).bind(now).all<Pick<OutboxRow, "event_id" | "state" | "lease_fence">>();
  for (const row of due.results) {
    const dispatchDeadline = new Date(Date.now() + 5 * 60_000).toISOString();
    const claimed = await env.DB.prepare(`UPDATE central_feedback_outbox SET state='dispatching',next_attempt_at=?,updated_at=?
      WHERE event_id=? AND state=? AND lease_fence=?`).bind(dispatchDeadline, now, row.event_id, row.state, row.lease_fence).run();
    if ((claimed.meta.changes ?? 0) !== 1) continue;
    try {
      await env.PUBLISH_QUEUE.send({ schema_version: "feedback-publish-queue.v1", event_id: row.event_id }, { contentType: "json" });
      await env.DB.prepare(`UPDATE central_feedback_outbox SET state='enqueued',next_attempt_at=?,updated_at=?
        WHERE event_id=? AND state='dispatching'`).bind(
        new Date(Date.now() + 15 * 60_000).toISOString(), new Date().toISOString(), row.event_id
      ).run();
    } catch {
      await env.DB.prepare(`UPDATE central_feedback_outbox SET state='retry_wait',next_attempt_at=?,
        last_error_category='queue_unavailable',updated_at=? WHERE event_id=? AND state='dispatching'`).bind(
        new Date(Date.now() + 60_000).toISOString(), new Date().toISOString(), row.event_id
      ).run();
    }
  }
}

async function route(request: Request, env: HubEnv): Promise<Response> {
  const url = new URL(request.url);
  const consoleAsset = request.method === "GET" ? adminConsoleAsset(url.pathname) : null;
  if (consoleAsset) return consoleAsset;
  if (url.pathname === "/healthz" && request.method === "GET") {
    const error = configurationError(env);
    return jsonResponse({ service: "central-feedback-hub", status: error ? "unconfigured" : "ok" }, error ? 503 : 200);
  }
  const error = configurationError(env);
  if (error) return jsonResponse({ detail: error }, 503);
  if (url.pathname === "/v1/intake" && request.method === "POST") return intake(request, env);
  const statusMatch = url.pathname.match(/^\/v1\/status\/(central_feedback_[0-9a-f]{32})$/);
  if (statusMatch && request.method === "GET") return publicStatus(request, env, statusMatch[1]!);
  if (url.pathname === "/v1/admin/session" && request.method === "POST") return createAdminSession(request, env);
  if (url.pathname === "/v1/admin/session" && request.method === "GET") return inspectAdminSession(request, env);
  if (url.pathname === "/v1/admin/session" && request.method === "DELETE") return deleteAdminSession(request);
  if (url.pathname === "/v1/admin/feedback" && request.method === "GET") {
    if (!await adminAuthentication(request, env)) return jsonResponse({ detail: "feedback administrator authentication failed" }, 401);
    return adminList(url, env);
  }
  const adminMatch = url.pathname.match(/^\/v1\/admin\/feedback\/(central_feedback_[0-9a-f]{32})\/(triage|accept|reject|duplicate)$/);
  if (adminMatch && request.method === "POST") {
    const authentication = await adminAuthentication(request, env);
    if (!authentication) return jsonResponse({ detail: "feedback administrator authentication failed" }, 401);
    if (authentication === "session" && !sameOriginUiRequest(request)) {
      return jsonResponse({ detail: "feedback administrator request origin is invalid" }, 403);
    }
    return moderate(request, env, adminMatch[1]!, adminMatch[2]!);
  }
  if (url.pathname === "/internal/feedback-publications/heartbeat" && request.method === "POST") {
    if (!publisherAuthenticated(request, env)) return jsonResponse({ detail: "publisher authentication failed" }, 401);
    const body = await requestJson(request, 2 * 1024) as Record<string, unknown>;
    if (body.configured !== true || body.repository !== REPOSITORY) return jsonResponse({ detail: "publisher destination is not fixed repository" }, 409);
    return jsonResponse({ schema_version: "feedback-publisher-heartbeat.v1", accepted: true, configured: true });
  }
  const publisherMatch = url.pathname.match(/^\/internal\/feedback-publications\/(feedback_outbox_[0-9a-f]{32})\/(claim|complete|retry)$/);
  if (publisherMatch && request.method === "POST") {
    if (!publisherAuthenticated(request, env)) return jsonResponse({ detail: "publisher authentication failed" }, 401);
    return publisherMutation(request, env, publisherMatch[1]!, publisherMatch[2]!);
  }
  return jsonResponse({ detail: "not found" }, 404);
}

export default {
  async fetch(request: Request, env: HubEnv): Promise<Response> {
    try {
      return await route(request, env);
    } catch (error) {
      if (error instanceof ContractError) return jsonResponse({ detail: error.message }, error.status);
      console.error("feedback hub request failed", { category: "internal_error" });
      return jsonResponse({ detail: "internal error" }, 500);
    }
  },
  scheduled(_controller: ScheduledController, env: HubEnv, ctx: ExecutionContext): void {
    ctx.waitUntil(dispatchDue(env));
  }
} satisfies ExportedHandler<HubEnv>;
