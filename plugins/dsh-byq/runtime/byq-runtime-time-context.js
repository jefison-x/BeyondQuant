const DEFAULT_TIMEZONE = "Asia/Shanghai";
const CONTEXT_NAME = "runtime:trusted-clock";

function validateTimezone(timezone) {
  if (typeof timezone !== "string" || timezone.trim() === "") {
    throw new TypeError("runtime time context requires a non-empty IANA timezone");
  }
  const normalized = timezone.trim();
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: normalized }).format(new Date(0));
  } catch {
    throw new TypeError(`runtime time context received an invalid IANA timezone: ${normalized}`);
  }
  return normalized;
}

function partsFor(now, timezone) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
    timeZoneName: "longOffset",
  }).formatToParts(now);
  return Object.fromEntries(parts.map(({ type, value }) => [type, value]));
}

function normalizeOffset(value) {
  if (value === "GMT" || value === "UTC") return "Z";
  return value.replace(/^(?:GMT|UTC)/, "");
}

export function formatRuntimeClockContext(now, timezone = DEFAULT_TIMEZONE) {
  if (!(now instanceof Date) || Number.isNaN(now.getTime())) {
    throw new TypeError("runtime time context requires a valid Date");
  }
  const resolvedTimezone = validateTimezone(timezone);
  const parts = partsFor(now, resolvedTimezone);
  const localDate = `${parts.year}-${parts.month}-${parts.day}`;
  const localTime = `${parts.hour}:${parts.minute}:${parts.second}`;
  const offset = normalizeOffset(parts.timeZoneName);
  return [
    "可信运行时钟（由部署环境提供，每轮模型调用前重新读取）：",
    `- 当前 UTC 时间：${now.toISOString()}`,
    `- 当前时区：${resolvedTimezone}`,
    `- 当前当地时间：${localDate}T${localTime}${offset}`,
    `- 当前当地日期：${localDate}`,
    "相对自然日必须以上述当地日期为基准。这里仅表示墙上时钟；不得据此推断交易日、市场是否开盘、最新完整行情或数据截止日。涉及这些问题时必须读取 BYQ 交易会话上下文。",
  ].join("\n");
}

export const name = "byq-runtime-time-context";
export const inject = ["systemPrompt"];

export function apply(ctx, config = {}) {
  const timezone = validateTimezone(config.timezone ?? DEFAULT_TIMEZONE);
  ctx.systemPrompt.context({
    name: CONTEXT_NAME,
    order: -50,
    text: () => formatRuntimeClockContext(new Date(), timezone),
  });
}
