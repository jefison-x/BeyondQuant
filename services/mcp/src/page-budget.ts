export type PageBudgetDecision = {
  allowed: boolean;
  limit: number;
  remaining: number;
};

export class PageCallBudget {
  private readonly calls = new Map<string, number[]>();
  private static readonly MAX_KEYS = 10_000;

  constructor(
    readonly limit: number,
    readonly windowMs: number,
    private readonly now: () => number = Date.now,
  ) {
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) {
      throw new Error("page call limit must be an integer between 1 and 100");
    }
    if (!Number.isSafeInteger(windowMs) || windowMs < 1_000 || windowMs > 3_600_000) {
      throw new Error("page call window must be between 1000 and 3600000 milliseconds");
    }
  }

  consume(key: string): PageBudgetDecision {
    const now = this.now();
    const cutoff = now - this.windowMs;
    if (!this.calls.has(key) && this.calls.size >= PageCallBudget.MAX_KEYS) {
      for (const [candidate, timestamps] of this.calls) {
        if (timestamps.every((timestamp) => timestamp <= cutoff)) this.calls.delete(candidate);
      }
      if (this.calls.size >= PageCallBudget.MAX_KEYS) {
        const oldest = this.calls.keys().next().value as string | undefined;
        if (oldest !== undefined) this.calls.delete(oldest);
      }
    }
    const recent = (this.calls.get(key) ?? []).filter((timestamp) => timestamp > cutoff);
    if (recent.length >= this.limit) {
      this.calls.set(key, recent);
      return { allowed: false, limit: this.limit, remaining: 0 };
    }
    recent.push(now);
    this.calls.set(key, recent);
    return { allowed: true, limit: this.limit, remaining: this.limit - recent.length };
  }
}

export function boundedIntegerEnvironment(
  name: string, fallback: number, minimum: number, maximum: number,
): number {
  const raw = process.env[name];
  if (raw === undefined) return fallback;
  const parsed = Number(raw);
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${name} must be an integer between ${minimum} and ${maximum}`);
  }
  return parsed;
}
