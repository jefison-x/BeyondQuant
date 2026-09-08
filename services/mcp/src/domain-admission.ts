import { setTimeout as delay } from "node:timers/promises";

const REASONS = new Set(["call_evidence_pending", "prior_call_outcome_unknown", "unchanged_failed_input",
  "correction_budget_exhausted", "call_retention_bound", "domain_validation_failed", "correction_failed"]);

export function safeDomainAdmission(payload: unknown) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return undefined;
  const detail = (payload as Record<string, unknown>).detail;
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return undefined;
  const value = detail as Record<string, unknown>;
  if (value.schema_version !== "domain-call-admission.v1"
    || !Object.keys(value).every(key => ["schema_version", "state", "reason"].includes(key))) return undefined;
  if (value.state === "unknown" && value.reason === undefined) {
    return { schema_version: "domain-call-admission.v1", state: "unknown", stop: true };
  }
  if (!["blocked", "correctable_failure"].includes(String(value.state))
    || typeof value.reason !== "string" || !REASONS.has(value.reason)) return undefined;
  return { schema_version: "domain-call-admission.v1", state: value.state, reason: value.reason,
    stop: value.reason !== "domain_validation_failed" };
}

/** Only an exact pre-execution 425 can be re-sent. No timeout/409/5xx retry. */
export function evidenceBoundedFetcher(fetcher: typeof fetch, root: string | undefined): typeof fetch {
  return async (input, init) => {
    const headers = new Headers(init?.headers);
    if (root && /^[a-f0-9]{32}$/.test(root)) headers.set("x-byq-root-run-id", root);
    else headers.delete("x-byq-root-run-id");
    const bounded = { ...init, headers };
    for (let attempt = 0; ; attempt += 1) {
      const response = await fetcher(input, bounded);
      if (response.status !== 425 || attempt >= 4) return response;
      const admission = safeDomainAdmission(await response.clone().json().catch(() => undefined));
      if (admission?.state !== "blocked" || admission.reason !== "call_evidence_pending") return response;
      await delay([250, 500, 1000, 2000][attempt], undefined, { signal: init?.signal ?? undefined });
    }
  };
}
