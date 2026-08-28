import assert from "node:assert/strict";

import { Context } from "@deepseek-ai/cordis";
import SystemPrompt, { renderContextSnapshot } from "@deepseek-ai/dsh-system-prompt";
import * as TimeContext from "file:///opt/byq/runtime/byq-runtime-time-context.js";

const root = new Context();
try {
  await root.plugin(SystemPrompt);
  await root.plugin(TimeContext, { timezone: "Asia/Shanghai" });
  const snapshot = renderContextSnapshot(await root.systemPrompt.assemble());
  assert.match(snapshot, /可信运行时钟/);
  assert.match(snapshot, /当前 UTC 时间：\d{4}-\d{2}-\d{2}T/);
  assert.match(snapshot, /当前时区：Asia\/Shanghai/);
  assert.match(snapshot, /当前当地日期：\d{4}-\d{2}-\d{2}/);
  assert.match(snapshot, /不得据此推断交易日/);
} finally {
  await root.fiber.dispose();
}
