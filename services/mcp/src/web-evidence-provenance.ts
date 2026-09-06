import { readFileSync } from "node:fs";
import { resolve } from "node:path";

export type WebEvidenceProducer = {
  plugin_id: "web-search";
  plugin_version: string;
  release_id: string;
  qualification_state: "QUALIFIED" | "CANDIDATE";
  attestation_sha256: string;
};

type WebEvidencePolicy = {
  schema_version: "web-evidence-provenance-policy.v1";
  mode: "qualified" | "candidate";
  active_producer: WebEvidenceProducer;
  recognized_producers: WebEvidenceProducer[];
};

const PRODUCER_FIELDS = [
  "attestation_sha256", "plugin_id", "plugin_version", "qualification_state", "release_id",
].sort();

function policyPath(): string {
  return process.env.BYQ_WEB_EVIDENCE_PROVENANCE_POLICY
    ?? (process.cwd() === "/app"
      ? "/app/web-evidence-provenance.json"
      : resolve(process.cwd(), "../../config/dsh/generated/web-evidence-provenance.json"));
}

function producer(value: unknown): WebEvidenceProducer {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("web evidence producer must be an object");
  }
  const item = value as Record<string, unknown>;
  if (JSON.stringify(Object.keys(item).sort()) !== JSON.stringify(PRODUCER_FIELDS)
      || item.plugin_id !== "web-search"
      || typeof item.plugin_version !== "string" || !item.plugin_version
      || typeof item.release_id !== "string" || !item.release_id
      || !["QUALIFIED", "CANDIDATE"].includes(String(item.qualification_state))
      || typeof item.attestation_sha256 !== "string"
      || !/^sha256:[0-9a-f]{64}$/.test(item.attestation_sha256)) {
    throw new Error("web evidence producer is invalid");
  }
  return item as WebEvidenceProducer;
}

export function loadWebEvidencePolicy(): WebEvidencePolicy {
  const value = JSON.parse(readFileSync(policyPath(), "utf8")) as Record<string, unknown>;
  if (JSON.stringify(Object.keys(value).sort()) !== JSON.stringify([
    "active_producer", "mode", "recognized_producers", "schema_version",
  ]) || value.schema_version !== "web-evidence-provenance-policy.v1"
      || !["qualified", "candidate"].includes(String(value.mode))
      || !Array.isArray(value.recognized_producers) || value.recognized_producers.length === 0) {
    throw new Error("web evidence provenance policy is invalid");
  }
  const active = producer(value.active_producer);
  const recognized = value.recognized_producers.map(producer);
  const identities = new Set(recognized.map((item) => `${item.plugin_id}\u0000${item.plugin_version}`));
  if (identities.size !== recognized.length || !recognized.some((item) => PRODUCER_FIELDS.every((field) => item[field as keyof WebEvidenceProducer] === active[field as keyof WebEvidenceProducer]))) {
    throw new Error("web evidence provenance policy producer set is invalid");
  }
  if (value.mode === "qualified" && recognized.some((item) => item.qualification_state !== "QUALIFIED")) {
    throw new Error("qualified web evidence policy contains an unqualified producer");
  }
  if ((value.mode === "qualified" && active.qualification_state !== "QUALIFIED")
      || (value.mode === "candidate" && active.qualification_state !== "CANDIDATE")) {
    throw new Error("web evidence provenance policy mode is inconsistent");
  }
  return { schema_version: value.schema_version, mode: value.mode, active_producer: active, recognized_producers: recognized } as WebEvidencePolicy;
}

export function bindActiveWebEvidenceProducer(content: Record<string, unknown>): Record<string, unknown> {
  const search = content.search;
  if (search === null || typeof search !== "object" || Array.isArray(search)) return content;
  const active = loadWebEvidencePolicy().active_producer;
  const supplied = search as Record<string, unknown>;
  for (const field of ["plugin_id", "plugin_version"] as const) {
    if (field in supplied && supplied[field] !== active[field]) {
      throw new Error("web evidence producer claim does not match trusted deployment");
    }
  }
  return {
    ...content,
    search: { ...supplied, plugin_id: active.plugin_id, plugin_version: active.plugin_version },
  };
}
