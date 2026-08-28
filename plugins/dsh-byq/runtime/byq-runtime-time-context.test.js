import assert from "node:assert/strict";
import test from "node:test";

import { apply, formatRuntimeClockContext } from "./byq-runtime-time-context.js";

test("formats UTC and Asia/Shanghai as distinct trusted clock facts", () => {
  const now = new Date("2026-08-28T05:37:55.123Z");
  const text = formatRuntimeClockContext(now, "Asia/Shanghai");

  assert.match(text, /2026-08-28T05:37:55\.123Z/);
  assert.match(text, /Asia\/Shanghai/);
  assert.match(text, /2026-08-28T13:37:55\+08:00/);
  assert.match(text, /当前当地日期：2026-08-28/);
  assert.match(text, /不得据此推断交易日/);
});

test("uses IANA timezone rules, including daylight-saving offsets", () => {
  const winter = formatRuntimeClockContext(new Date("2026-01-15T12:00:00Z"), "America/New_York");
  const summer = formatRuntimeClockContext(new Date("2026-07-15T12:00:00Z"), "America/New_York");

  assert.match(winter, /2026-01-15T07:00:00-05:00/);
  assert.match(summer, /2026-07-15T08:00:00-04:00/);
});

test("registers a per-assembly dynamic context and rejects invalid zones", () => {
  let registered;
  apply({ systemPrompt: { context(value) { registered = value; } } }, { timezone: "Asia/Shanghai" });

  assert.equal(registered.name, "runtime:trusted-clock");
  assert.equal(registered.order, -50);
  assert.equal(typeof registered.text, "function");
  assert.match(registered.text(), /可信运行时钟/);
  assert.throws(
    () => apply({ systemPrompt: { context() {} } }, { timezone: "Mars/Olympus" }),
    /invalid IANA timezone/,
  );
});
