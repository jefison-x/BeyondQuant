import { env } from "cloudflare:workers";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import hub, { dispatchDue } from "../../../services/feedback-hub-cloudflare/src/index";
import { IntakeEnvelope, PublicationEvent, digest, hmacHex, timingSafeEqual } from "../../../services/feedback-hub-cloudflare/src/contracts";
import publisher, { classifyGitHubStatus, marker, privateKeyDer, render } from "../../../workers/feedback-publisher-cloudflare/src/index";

interface TestEnv {
  DB: D1Database;
  INSTALLATION_GATE: DurableObjectNamespace;
  FEEDBACK_GATE: DurableObjectNamespace;
  PUBLISH_QUEUE: Queue;
  BYQ_FEEDBACK_HUB_STATUS_SECRET: string;
  BYQ_FEEDBACK_HUB_ADMIN_TOKEN: string;
  BYQ_FEEDBACK_PUBLISHER_TOKEN: string;
  BYQ_FEEDBACK_GITHUB_REPOSITORY: string;
}

const testEnv = env as unknown as TestEnv;
const adminHeaders = () => ({
  authorization: `Bearer ${testEnv.BYQ_FEEDBACK_HUB_ADMIN_TOKEN}`,
  "content-type": "application/json"
});
const publisherHeaders = () => ({
  "x-byq-feedback-publisher-token": testEnv.BYQ_FEEDBACK_PUBLISHER_TOKEN,
  "content-type": "application/json"
});

function hexId(): string {
  return crypto.randomUUID().replaceAll("-", "");
}

async function envelope(installation = `byq-installation-${hexId()}`, suffix = hexId()): Promise<IntakeEnvelope> {
  const publicContent = {
    category: "bug",
    component: "xiaoba",
    title: `测试反馈 ${suffix.slice(0, 8)}`,
    description: "审批完成后会话没有继续执行。",
    reproduction_steps: ["在会话中创建反馈", "前往审批中心批准"],
    expected_behavior: "自动返回原会话继续提交。",
    actual_behavior: "会话保持等待状态。",
    severity: "normal",
    environment: { product_version: "0.1.0", deployment_kind: "self-hosted" }
  };
  const snapshot = {
    schema_version: "submitted-feedback-snapshot.v1" as const,
    public_content: publicContent,
    redactions: { categories: [], count: 0 },
    preview_hash: await digest({ schema_version: "feedback-publication-preview.v1", public_content: publicContent })
  };
  return {
    schema_version: "central-feedback-intake.v1",
    installation_id: installation,
    event_id: `feedback_hub_event_${suffix}`,
    snapshot_hash: await digest(snapshot),
    snapshot
  };
}

async function call(path: string, init: RequestInit = {}): Promise<Response> {
  return hub.fetch(new Request(`https://hub.example${path}`, init), testEnv as never);
}

async function submit(value: IntakeEnvelope): Promise<{ receipt_id: string; status_token: string; status: string }> {
  const response = await call("/v1/intake", {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(value)
  });
  expect(response.status).toBe(202);
  return response.json();
}

async function adminSession(token = testEnv.BYQ_FEEDBACK_HUB_ADMIN_TOKEN): Promise<{ response: Response; cookie: string }> {
  const response = await call("/v1/admin/session", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "origin": "https://hub.example",
      "x-byq-feedback-admin-request": "ui-v1"
    },
    body: JSON.stringify({ token })
  });
  return { response, cookie: (response.headers.get("set-cookie") ?? "").split(";", 1)[0]! };
}

beforeAll(() => {
  expect(testEnv.BYQ_FEEDBACK_GITHUB_REPOSITORY).toBe("jefison-x/BeyondQuant");
});

afterEach(() => vi.restoreAllMocks());

describe("Cloudflare central feedback Hub", () => {
  it("serves a self-contained, non-cacheable central moderation console", async () => {
    const page = await call("/admin");
    expect(page.status).toBe(200);
    expect(page.headers.get("content-type")).toContain("text/html");
    expect(page.headers.get("cache-control")).toBe("no-store");
    expect(page.headers.get("x-frame-options")).toBe("DENY");
    expect(page.headers.get("content-security-policy")).toContain("default-src 'none'");
    expect(page.headers.get("content-security-policy")).toContain("script-src 'self'");
    const html = await page.text();
    expect(html).toContain("BeyondQuant 中央反馈审核");
    expect(html).toContain('src="/admin/assets/app.js"');
    expect(html).not.toContain("BYQ_FEEDBACK_HUB_ADMIN_TOKEN");
    expect(html).not.toMatch(/<(?:script|link)[^>]+(?:src|href)=["']https?:\/\//i);

    const script = await call("/admin/assets/app.js");
    expect(script.headers.get("content-type")).toContain("text/javascript");
    expect(script.headers.get("cache-control")).toBe("no-store");
    const source = await script.text();
    expect(source).toContain("textContent");
    expect(source).not.toContain("innerHTML");
    expect(source).not.toContain("localStorage");
    expect(source).not.toContain("sessionStorage");
    expect(source).not.toContain("BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY");
    expect(source).not.toMatch(/https?:\/\//);

    const styles = await call("/admin/assets/app.css");
    expect(styles.headers.get("content-type")).toContain("text/css");
    expect(styles.headers.get("cache-control")).toBe("no-store");
  });

  it("exchanges the admin token for a bounded HttpOnly session without persisting the token", async () => {
    const wrong = await adminSession("wrong-admin-token-that-is-at-least-32-bytes");
    expect(wrong.response.status).toBe(401);
    expect(wrong.response.headers.get("set-cookie")).toBeNull();

    const crossOrigin = await call("/v1/admin/session", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "origin": "https://attacker.example",
        "x-byq-feedback-admin-request": "ui-v1"
      },
      body: JSON.stringify({ token: testEnv.BYQ_FEEDBACK_HUB_ADMIN_TOKEN })
    });
    expect(crossOrigin.status).toBe(403);

    const created = await adminSession();
    expect(created.response.status).toBe(200);
    const setCookie = created.response.headers.get("set-cookie") ?? "";
    expect(setCookie).toContain("__Host-byq_feedback_admin=v1.");
    expect(setCookie).toContain("Max-Age=28800");
    expect(setCookie).toContain("Secure");
    expect(setCookie).toContain("HttpOnly");
    expect(setCookie).toContain("SameSite=Strict");
    expect(setCookie).not.toContain(testEnv.BYQ_FEEDBACK_HUB_ADMIN_TOKEN);
    expect(await created.response.json()).toMatchObject({ authenticated: true });

    const inspected = await call("/v1/admin/session", { headers: { cookie: created.cookie } });
    expect(await inspected.json()).toMatchObject({ authenticated: true });
    const tamperedCookie = `${created.cookie.slice(0, -1)}${created.cookie.endsWith("0") ? "1" : "0"}`;
    expect((await call("/v1/admin/feedback?status=all", { headers: { cookie: tamperedCookie } })).status).toBe(401);

    const expired = Math.floor(Date.now() / 1000) - 1;
    const expiredSignature = await hmacHex(testEnv.BYQ_FEEDBACK_HUB_ADMIN_TOKEN,
      `central-feedback-admin-session.v1:${expired}`);
    const expiredCookie = `__Host-byq_feedback_admin=v1.${expired}.${expiredSignature}`;
    expect((await call("/v1/admin/feedback?status=all", { headers: { cookie: expiredCookie } })).status).toBe(401);

    const deleted = await call("/v1/admin/session", {
      method: "DELETE",
      headers: { origin: "https://hub.example", "x-byq-feedback-admin-request": "ui-v1" }
    });
    expect(deleted.status).toBe(200);
    expect(deleted.headers.get("set-cookie")).toContain("Max-Age=0");
  });

  it("allows cookie moderation only for exact same-origin UI requests", async () => {
    const receipt = await submit(await envelope());
    const created = await adminSession();
    expect(created.response.status).toBe(200);

    const list = await call("/v1/admin/feedback?status=received&limit=1&offset=0", {
      headers: { cookie: created.cookie }
    });
    expect(list.status).toBe(200);
    expect(await list.json()).toMatchObject({ schema_version: "central-feedback-admin-catalog.v1", limit: 1, offset: 0 });

    const missingGuard = await call(`/v1/admin/feedback/${receipt.receipt_id}/triage`, {
      method: "POST",
      headers: { cookie: created.cookie, "content-type": "application/json" },
      body: JSON.stringify({ rationale: "信息完整" })
    });
    expect(missingGuard.status).toBe(403);

    const wrongOrigin = await call(`/v1/admin/feedback/${receipt.receipt_id}/triage`, {
      method: "POST",
      headers: {
        cookie: created.cookie, "content-type": "application/json",
        origin: "https://attacker.example", "x-byq-feedback-admin-request": "ui-v1"
      },
      body: JSON.stringify({ rationale: "信息完整" })
    });
    expect(wrongOrigin.status).toBe(403);

    const triaged = await call(`/v1/admin/feedback/${receipt.receipt_id}/triage`, {
      method: "POST",
      headers: {
        cookie: created.cookie, "content-type": "application/json",
        origin: "https://hub.example", "x-byq-feedback-admin-request": "ui-v1"
      },
      body: JSON.stringify({ rationale: "信息完整" })
    });
    expect(triaged.status).toBe(200);
    expect(await triaged.json()).toMatchObject({ status: "triaged" });
  });

  it("compares empty and non-empty capabilities without an empty-buffer edge case", () => {
    expect(timingSafeEqual("", "")).toBe(true);
    expect(timingSafeEqual("", "secret")).toBe(false);
    expect(timingSafeEqual("secret", "")).toBe(false);
  });

  it("accepts the existing relay envelope and returns an idempotent capability receipt", async () => {
    const value = await envelope();
    const first = await submit(value);
    const second = await submit(value);
    expect(second.receipt_id).toBe(first.receipt_id);
    expect(second.status_token).toBe(first.status_token);

    const unauthorized = await call(`/v1/status/${first.receipt_id}`);
    expect(unauthorized.status).toBe(401);
    const status = await call(`/v1/status/${first.receipt_id}`, {
      headers: { authorization: `Bearer ${first.status_token}` }
    });
    expect(await status.json()).toMatchObject({ status: "received", github_issue: null });
  });

  it("fails closed on tampering, unsafe content, and a sixth hourly event", async () => {
    const tampered = await envelope();
    tampered.snapshot.public_content.description = "changed after hashing";
    expect((await call("/v1/intake", {
      method: "POST", body: JSON.stringify(tampered), headers: { "content-type": "application/json" }
    })).status).toBe(422);

    const unsafe = await envelope();
    unsafe.snapshot.public_content.description = "api_key=sk-123456789012345678901234";
    unsafe.snapshot.preview_hash = await digest({
      schema_version: "feedback-publication-preview.v1", public_content: unsafe.snapshot.public_content
    });
    unsafe.snapshot_hash = await digest(unsafe.snapshot);
    expect((await call("/v1/intake", {
      method: "POST", body: JSON.stringify(unsafe), headers: { "content-type": "application/json" }
    })).status).toBe(422);

    const installation = `byq-installation-${hexId()}`;
    for (let index = 0; index < 5; index += 1) await submit(await envelope(installation));
    const limited = await call("/v1/intake", {
      method: "POST", body: JSON.stringify(await envelope(installation)), headers: { "content-type": "application/json" }
    });
    expect(limited.status).toBe(429);
  });

  it("keeps accept plus outbox durable and completes the fixed repository publication", async () => {
    const receipt = await submit(await envelope());
    const triage = await call(`/v1/admin/feedback/${receipt.receipt_id}/triage`, {
      method: "POST", headers: adminHeaders(), body: JSON.stringify({ rationale: "信息完整" })
    });
    expect(triage.status).toBe(200);
    const accepted = await call(`/v1/admin/feedback/${receipt.receipt_id}/accept`, {
      method: "POST", headers: adminHeaders(), body: JSON.stringify({ rationale: "批准进入公开发布队列" })
    });
    expect(accepted.status).toBe(200);

    const outbox = await testEnv.DB.prepare("SELECT event_id,state FROM central_feedback_outbox WHERE receipt_id=?")
      .bind(receipt.receipt_id).first<{ event_id: string; state: string }>();
    expect(outbox?.state).toBe("queued");
    await dispatchDue(testEnv as never);
    const dispatched = await testEnv.DB.prepare("SELECT state FROM central_feedback_outbox WHERE event_id=?")
      .bind(outbox!.event_id).first<{ state: string }>();
    expect(dispatched?.state).toBe("enqueued");

    const claim = await call(`/internal/feedback-publications/${outbox!.event_id}/claim`, {
      method: "POST", headers: publisherHeaders(), body: JSON.stringify({ worker_id: "test-worker", lease_seconds: 60 })
    });
    expect(claim.status).toBe(200);
    const event = await claim.json<PublicationEvent>();
    const complete = await call(`/internal/feedback-publications/${outbox!.event_id}/complete`, {
      method: "POST",
      headers: publisherHeaders(),
      body: JSON.stringify({
        worker_id: "test-worker", lease_fence: event.lease_fence,
        repository: "jefison-x/BeyondQuant", issue_number: 42,
        html_url: "https://github.com/jefison-x/BeyondQuant/issues/42", provider_identity: "9001"
      })
    });
    expect(complete.status).toBe(200);
    const status = await call(`/v1/status/${receipt.receipt_id}`, {
      headers: { authorization: `Bearer ${receipt.status_token}` }
    });
    expect(await status.json()).toMatchObject({
      status: "published",
      github_issue: { repository: "jefison-x/BeyondQuant", issue_number: 42 }
    });
  });

  it("requires central administrator and publisher credentials", async () => {
    expect((await call("/v1/admin/feedback?status=all")).status).toBe(401);
    const missing = `feedback_outbox_${hexId()}`;
    expect((await call(`/internal/feedback-publications/${missing}/claim`, {
      method: "POST", body: "{}", headers: { "content-type": "application/json" }
    })).status).toBe(401);
  });

  it("rejects caller fields that could override moderation or publication routing", async () => {
    const receipt = await submit(await envelope());
    const overriddenModeration = await call(`/v1/admin/feedback/${receipt.receipt_id}/triage`, {
      method: "POST",
      headers: adminHeaders(),
      body: JSON.stringify({ rationale: "信息完整", action: "accept" })
    });
    expect(overriddenModeration.status).toBe(422);

    const triage = await call(`/v1/admin/feedback/${receipt.receipt_id}/triage`, {
      method: "POST", headers: adminHeaders(), body: JSON.stringify({ rationale: "信息完整" })
    });
    expect(triage.status).toBe(200);
    const accepted = await call(`/v1/admin/feedback/${receipt.receipt_id}/accept`, {
      method: "POST", headers: adminHeaders(), body: JSON.stringify({ rationale: "批准发布" })
    });
    expect(accepted.status).toBe(200);
    const outbox = await testEnv.DB.prepare("SELECT event_id FROM central_feedback_outbox WHERE receipt_id=?")
      .bind(receipt.receipt_id).first<{ event_id: string }>();
    await dispatchDue(testEnv as never);
    const overriddenEvent = await call(`/internal/feedback-publications/${outbox!.event_id}/claim`, {
      method: "POST",
      headers: publisherHeaders(),
      body: JSON.stringify({ worker_id: "test-worker", lease_seconds: 60, event_id: `feedback_outbox_${hexId()}` })
    });
    expect(overriddenEvent.status).toBe(422);
  });
});

describe("isolated Cloudflare GitHub publisher", () => {
  it("renders the immutable marker and classifies provider failures", async () => {
    const value = await envelope();
    const event: PublicationEvent = {
      event_id: `feedback_outbox_${hexId()}`,
      feedback_id: `central_feedback_${hexId()}`,
      publication_id: `central_feedback_${hexId()}`,
      snapshot_hash: await digest(value.snapshot),
      snapshot: {
        schema_version: "feedback-publication.v1",
        public_content: value.snapshot.public_content,
        redactions: value.snapshot.redactions
      },
      attempt: 1,
      lease_fence: 1,
      lease_expires_at: new Date(Date.now() + 60_000).toISOString()
    };
    const output = render(event);
    expect(output.title).toContain("[Bug]");
    expect(output.body).toContain(marker(event));
    expect(classifyGitHubStatus(429, new Headers({ "retry-after": "70" }))).toMatchObject({
      category: "rate_limited", retryAfter: 70
    });
  });

  it("wraps GitHub PKCS#1 keys as WebCrypto PKCS#8", () => {
    const wrapped = privateKeyDer("-----BEGIN RSA PRIVATE KEY-----\nAQIDBA==\n-----END RSA PRIVATE KEY-----");
    expect(wrapped[0]).toBe(0x30);
    expect(wrapped.length).toBeGreaterThan(4);
  });

  it("uses only the fixed GitHub Issue route and acknowledges after Hub completion", async () => {
    const value = await envelope();
    const event: PublicationEvent = {
      event_id: `feedback_outbox_${hexId()}`,
      feedback_id: `central_feedback_${hexId()}`,
      publication_id: `central_feedback_${hexId()}`,
      snapshot_hash: await digest(value.snapshot),
      snapshot: {
        schema_version: "feedback-publication.v1",
        public_content: value.snapshot.public_content,
        redactions: value.snapshot.redactions
      },
      attempt: 1,
      lease_fence: 2,
      lease_expires_at: new Date(Date.now() + 60_000).toISOString()
    };
    const key = await crypto.subtle.generateKey(
      { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
      true,
      ["sign", "verify"]
    );
    const der = new Uint8Array(await crypto.subtle.exportKey("pkcs8", key.privateKey));
    const pem = `-----BEGIN PRIVATE KEY-----\n${btoa(String.fromCharCode(...der))}\n-----END PRIVATE KEY-----`;
    const hubCalls: string[] = [];
    const hubBinding = {
      async fetch(input: RequestInfo | URL): Promise<Response> {
        const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        hubCalls.push(url);
        if (url.endsWith("/claim")) return new Response(JSON.stringify(event), { status: 200 });
        return new Response(JSON.stringify({ status: "published" }), { status: 200 });
      }
    };
    const githubCalls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      githubCalls.push(url);
      if (url.includes("/app/installations/")) {
        return new Response(JSON.stringify({ token: "installation-token", expires_at: new Date(Date.now() + 3_600_000).toISOString() }), { status: 201 });
      }
      if (url.includes("?state=all")) return new Response("[]", { status: 200 });
      return new Response(JSON.stringify({
        id: 8001, number: 77, html_url: "https://github.com/jefison-x/BeyondQuant/issues/77"
      }), { status: 201 });
    });
    const message = {
      id: "message-1",
      timestamp: new Date(),
      attempts: 1,
      body: { schema_version: "feedback-publish-queue.v1", event_id: event.event_id },
      ack: vi.fn(),
      retry: vi.fn()
    };
    await publisher.queue({
      queue: "byq-feedback-publish", messages: [message], ackAll: vi.fn(), retryAll: vi.fn()
    } as unknown as MessageBatch<{ schema_version: "feedback-publish-queue.v1"; event_id: string }>, {
      HUB: hubBinding,
      BYQ_FEEDBACK_PUBLISHER_TOKEN: "test-publisher-token-at-least-32-bytes",
      BYQ_FEEDBACK_GITHUB_APP_ID: "1234",
      BYQ_FEEDBACK_GITHUB_INSTALLATION_ID: "5678",
      BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY: pem,
      BYQ_FEEDBACK_GITHUB_REPOSITORY: "jefison-x/BeyondQuant"
    } as never);
    expect(message.ack).toHaveBeenCalledOnce();
    expect(message.retry).not.toHaveBeenCalled();
    expect(hubCalls.some((url) => url.endsWith("/complete"))).toBe(true);
    expect(githubCalls).toEqual([
      "https://api.github.com/app/installations/5678/access_tokens",
      "https://api.github.com/repos/jefison-x/BeyondQuant/issues?state=all&per_page=100&page=1",
      "https://api.github.com/repos/jefison-x/BeyondQuant/issues"
    ]);
    expect(githubCalls.some((url) => url.includes("/pulls") || url.includes("/contents"))).toBe(false);
  });
});
