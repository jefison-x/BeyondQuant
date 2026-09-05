export const MAX_BYTES = 32 * 1024;
export const HOURLY_LIMIT = 5;
export const MAX_PUBLISH_ATTEMPTS = 6;
export const REPOSITORY = "jefison-x/BeyondQuant";
export const PREVIEW_SCHEMA = "feedback-publication-preview.v1";

const CATEGORIES = new Set(["bug", "feature", "performance", "usability", "other"]);
const COMPONENTS = new Set([
  "xiaoba", "stock_pool", "strategy", "model_research", "backtest",
  "data_center", "system_settings", "auth", "runtime", "other"
]);
const SEVERITIES = new Set(["low", "normal", "high"]);
const ENVIRONMENT_FIELDS = new Set([
  "product_version", "deployment_kind", "browser_family", "os_family", "performance_summary"
]);
const UNSAFE = [
  /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i,
  /(?:https?:\/\/|www\.)\S+/i,
  /(?:password|passwd|secret|authorization|api[_ -]?key|access[_ -]?token)\s*[:=]\s*\S{4,}/i,
  /(?:gh[oprsu]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)/i,
  /(?:security vulnerability|remote code execution|credential leak|安全漏洞|远程代码执行|凭据泄露)/i
];

export interface PublicContent {
  category: string;
  component: string;
  title: string;
  description: string;
  reproduction_steps: string[];
  expected_behavior: string;
  actual_behavior: string;
  severity: string;
  environment: Record<string, string>;
}

export interface SubmittedSnapshot {
  schema_version: "submitted-feedback-snapshot.v1";
  public_content: PublicContent;
  redactions: { categories: string[]; count: number };
  preview_hash: string;
}

export interface IntakeEnvelope {
  schema_version: "central-feedback-intake.v1";
  installation_id: string;
  event_id: string;
  snapshot_hash: string;
  snapshot: SubmittedSnapshot;
}

export interface PublicationEvent {
  event_id: string;
  feedback_id: string;
  publication_id: string;
  snapshot_hash: string;
  snapshot: {
    schema_version: "feedback-publication.v1";
    public_content: PublicContent;
    redactions: { categories: string[]; count: number };
  };
  attempt: number;
  lease_fence: number;
  lease_expires_at: string;
}

export class ContractError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return actual.length === wanted.length && actual.every((key, index) => key === wanted[index]);
}

function stable(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stable);
  if (isRecord(value)) {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stable(value[key])]));
  }
  return value;
}

export function canonical(value: unknown): string {
  return JSON.stringify(stable(value));
}

export function bytesToHex(value: ArrayBuffer): string {
  return [...new Uint8Array(value)].map((item) => item.toString(16).padStart(2, "0")).join("");
}

export async function digest(value: unknown): Promise<string> {
  return bytesToHex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical(value))));
}

export async function hmacHex(secret: string, value: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  return bytesToHex(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value)));
}

export function timingSafeEqual(left: string, right: string): boolean {
  const a = new TextEncoder().encode(left);
  const b = new TextEncoder().encode(right);
  let different = a.length ^ b.length;
  const length = Math.max(a.length, b.length);
  const aLength = Math.max(a.length, 1);
  const bLength = Math.max(b.length, 1);
  for (let index = 0; index < length; index += 1) {
    different |= (a[index % aLength] ?? 0) ^ (b[index % bLength] ?? 0);
  }
  return different === 0;
}

function boundedText(value: unknown, minimum: number, maximum: number): value is string {
  return typeof value === "string" && value.length >= minimum && value.length <= maximum;
}

export async function validateEnvelope(value: unknown): Promise<IntakeEnvelope> {
  if (!isRecord(value) || !exactKeys(value, [
    "schema_version", "installation_id", "event_id", "snapshot_hash", "snapshot"
  ]) || value.schema_version !== "central-feedback-intake.v1") {
    throw new ContractError(422, "intake is invalid");
  }
  if (!/^byq-installation-[0-9a-f]{32}$/.test(String(value.installation_id))) {
    throw new ContractError(422, "installation id is invalid");
  }
  if (!/^feedback_hub_event_[0-9a-f]{32}$/.test(String(value.event_id))) {
    throw new ContractError(422, "event id is invalid");
  }
  const snapshot = value.snapshot;
  if (!isRecord(snapshot) || !exactKeys(snapshot, ["schema_version", "public_content", "redactions", "preview_hash"])
      || snapshot.schema_version !== "submitted-feedback-snapshot.v1") {
    throw new ContractError(422, "snapshot shape is invalid");
  }
  const publicContent = snapshot.public_content;
  if (!isRecord(publicContent) || !exactKeys(publicContent, [
    "category", "component", "title", "description", "reproduction_steps",
    "expected_behavior", "actual_behavior", "severity", "environment"
  ])) {
    throw new ContractError(422, "public content shape is invalid");
  }
  if (!CATEGORIES.has(String(publicContent.category)) || !COMPONENTS.has(String(publicContent.component))
      || !SEVERITIES.has(String(publicContent.severity))) {
    throw new ContractError(422, "feedback classification is invalid");
  }
  if (!boundedText(publicContent.title, 4, 160) || !boundedText(publicContent.description, 1, 8000)
      || !boundedText(publicContent.expected_behavior, 0, 2000)
      || !boundedText(publicContent.actual_behavior, 0, 2000)) {
    throw new ContractError(422, "feedback text is invalid");
  }
  const steps = publicContent.reproduction_steps;
  if (!Array.isArray(steps) || steps.length > 12
      || steps.some((step) => !boundedText(step, 1, 500))) {
    throw new ContractError(422, "steps are invalid");
  }
  const environment = publicContent.environment;
  if (!isRecord(environment) || Object.keys(environment).some((key) => !ENVIRONMENT_FIELDS.has(key))
      || Object.values(environment).some((item) => !boundedText(item, 1, 80))) {
    throw new ContractError(422, "environment is invalid");
  }
  const redactions = snapshot.redactions;
  if (!isRecord(redactions) || !exactKeys(redactions, ["categories", "count"])
      || !Array.isArray(redactions.categories) || !Number.isInteger(redactions.count)
      || redactions.count !== redactions.categories.length
      || redactions.categories.some((item) => typeof item !== "string" || item.length > 80)) {
    throw new ContractError(422, "redactions are invalid");
  }
  if (UNSAFE.some((pattern) => pattern.test(canonical(publicContent)))) {
    throw new ContractError(422, "content cannot enter a public issue");
  }
  const expectedPreview = await digest({ schema_version: PREVIEW_SCHEMA, public_content: publicContent });
  if (typeof snapshot.preview_hash !== "string" || !timingSafeEqual(snapshot.preview_hash, expectedPreview)) {
    throw new ContractError(422, "preview hash is invalid");
  }
  const expectedSnapshot = await digest(snapshot);
  if (typeof value.snapshot_hash !== "string" || !timingSafeEqual(value.snapshot_hash, expectedSnapshot)) {
    throw new ContractError(422, "snapshot hash does not match");
  }
  return value as unknown as IntakeEnvelope;
}

export function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff"
    }
  });
}

export function randomId(prefix: string): string {
  return `${prefix}${crypto.randomUUID().replaceAll("-", "")}`;
}
