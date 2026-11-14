export const MAX_RESEARCH_PREPARATION_SYMBOLS = 20;
export const MAX_RESEARCH_PREPARATION_DAYS = 180;

export const VALUATION_FIELDS = [
  { value: "pe_ttm", label: "市盈率 TTM" },
  { value: "pb", label: "市净率" },
  { value: "ps_ttm", label: "市销率 TTM" },
  { value: "dv_ttm", label: "股息率 TTM" },
  { value: "dv_ratio", label: "股息率" },
  { value: "total_mv", label: "总市值" },
  { value: "turnover_rate", label: "换手率" },
] as const;

export const FINANCIAL_FIELDS = [
  { value: "eps", label: "每股收益" },
  { value: "roe", label: "净资产收益率" },
  { value: "roa", label: "总资产收益率" },
  { value: "grossprofit_margin", label: "毛利率" },
  { value: "debt_to_assets", label: "资产负债率" },
  { value: "or_yoy", label: "营业收入同比" },
  { value: "netprofit_yoy", label: "净利润同比" },
] as const;

export type ResearchDataRequirements = {
  daily_basic?: string[];
  fundamentals?: string[];
};

export interface ResearchPreparationScope {
  symbols: string[];
  start_date: string;
  end_date: string;
  use_case: "research";
  data_requirements: ResearchDataRequirements;
}

export function normalizeResearchPreparationScope(value: unknown): ResearchPreparationScope | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  if (!Array.isArray(item.symbols) || item.symbols.length < 1
      || item.symbols.length > MAX_RESEARCH_PREPARATION_SYMBOLS
      || item.use_case !== "research") return null;
  const symbols = [...new Set(item.symbols.map((symbol) =>
    typeof symbol === "string" ? symbol.trim().toUpperCase() : ""))];
  if (symbols.length !== item.symbols.length
      || symbols.some((symbol) => !/^\d{6}\.(SH|SZ|BJ)$/.test(symbol))) return null;
  const startDate = normalizeDate(item.start_date);
  const endDate = normalizeDate(item.end_date);
  if (!startDate || !endDate || dayDifference(startDate, endDate) < 0
      || dayDifference(startDate, endDate) + 1 > MAX_RESEARCH_PREPARATION_DAYS) return null;

  const rawRequirements = item.data_requirements ?? {};
  if (typeof rawRequirements !== "object" || rawRequirements === null || Array.isArray(rawRequirements)) return null;
  const requirements = rawRequirements as Record<string, unknown>;
  if (Object.keys(requirements).some((key) => !["daily_basic", "fundamentals"].includes(key))) return null;
  const dailyBasic = normalizeFieldList(requirements.daily_basic, VALUATION_FIELDS.map((field) => field.value));
  const fundamentals = normalizeFieldList(requirements.fundamentals, FINANCIAL_FIELDS.map((field) => field.value));
  if (dailyBasic === null || fundamentals === null) return null;
  return {
    symbols,
    start_date: startDate,
    end_date: endDate,
    use_case: "research",
    data_requirements: {
      ...(dailyBasic.length ? { daily_basic: dailyBasic } : {}),
      ...(fundamentals.length ? { fundamentals } : {}),
    },
  };
}

export function buildResearchPreparationHandoffUrl(
  scope: ResearchPreparationScope,
  origin = typeof window === "undefined" ? "http://localhost" : window.location.origin,
): string {
  const query = new URLSearchParams({ researchPreparation: JSON.stringify(scope) });
  return `${origin}/settings/system/data?${query.toString()}`;
}

export function researchPreparationScopeFromHandoffQuery(value: unknown): ResearchPreparationScope | null {
  if (typeof value !== "string" || value.length > 5000) return null;
  try {
    return normalizeResearchPreparationScope(JSON.parse(value));
  } catch {
    return null;
  }
}

export function formatResearchPreparationDate(value: string): string {
  const date = normalizeDate(value);
  return date ? `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}` : value;
}

function normalizeFieldList(value: unknown, allowed: readonly string[]): string[] | null {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > 12
      || value.some((field) => typeof field !== "string" || !allowed.includes(field))) return null;
  return [...new Set(value as string[])];
}

function normalizeDate(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const compact = value.replaceAll("-", "");
  if (!/^\d{8}$/.test(compact)) return null;
  const year = Number(compact.slice(0, 4));
  const month = Number(compact.slice(4, 6));
  const day = Number(compact.slice(6, 8));
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
    ? compact : null;
}

function dayDifference(start: string, end: string): number {
  const toUtc = (date: string) => Date.UTC(Number(date.slice(0, 4)), Number(date.slice(4, 6)) - 1, Number(date.slice(6, 8)));
  return Math.floor((toUtc(end) - toUtc(start)) / 86_400_000);
}
