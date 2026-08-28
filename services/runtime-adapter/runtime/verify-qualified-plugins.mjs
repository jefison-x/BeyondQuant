import assert from "node:assert/strict";

import {
  apply as applyRepeatReminder,
  name as repeatReminderName,
} from "@deepseek-ai/dsh-repeat-tool-reminder";
import {
  apply as applyTimeoutPolicy,
  name as timeoutPolicyName,
} from "@deepseek-ai/dsh-tool-call-timeout-policy";
import compactionPlugin, {
  BasicCompactionEngine,
} from "@deepseek-ai/dsh-compaction-basic";
import pruningPlugin, {
  ToolResultPruner,
} from "@deepseek-ai/dsh-compaction-tool-result-pruner";
import { name as webToolName } from "@deepseek-ai/dsh-tool-web";

function listenerContext(services = {}) {
  const listeners = new Map();
  return {
    ...services,
    listeners,
    on(event, listener) {
      listeners.set(event, listener);
    },
  };
}

assert.equal(repeatReminderName, "repeat-tool-reminder");
assert.equal(timeoutPolicyName, "timeout-policy");
assert.equal(typeof compactionPlugin, "function");
assert.equal(typeof BasicCompactionEngine, "function");
assert.equal(typeof pruningPlugin, "function");
assert.equal(typeof ToolResultPruner, "function");
assert.equal(webToolName, "tool-web");

const repeatContext = listenerContext();
applyRepeatReminder(repeatContext, {
  thresholds: [2],
  include: [],
  exclude: [],
  argumentsPreviewChars: 200,
});
const postExecute = repeatContext.listeners.get("tools/post-execute");
assert.equal(typeof postExecute, "function");
const agent = {};
const execution = { agent, name: "byq_test", arguments: { b: 2, a: 1 } };
const firstDecision = await postExecute(execution, { domain: "unchanged" }, async () => ({
  kind: "accept",
}));
assert.equal(firstDecision.additionalContexts, undefined);
const secondDecision = await postExecute(execution, { domain: "unchanged" }, async () => ({
  kind: "accept",
}));
assert.equal(secondDecision.kind, "accept");
assert.equal(secondDecision.additionalContexts.length, 1);
assert.equal(secondDecision.additionalContexts[0].source.plugin, "repeat-tool-reminder");
const blockedDecision = await postExecute(execution, { domain: "unchanged" }, async () => ({
  kind: "block",
  feedback: "authorization denied",
}));
assert.equal(blockedDecision.kind, "block");
assert.equal(blockedDecision.feedback, "authorization denied");

const timeoutContext = listenerContext({
  tools: {
    get(name) {
      return name === "bounded" ? { timeoutMs: 5 } : {};
    },
  },
});
applyTimeoutPolicy(timeoutContext);
const execute = timeoutContext.listeners.get("tools/execute");
assert.equal(typeof execute, "function");
const upstreamSignal = new AbortController().signal;
const timedExecution = { name: "bounded", agent, signal: upstreamSignal };
const timeoutResult = await execute(timedExecution, async () => {
  await new Promise((resolve) => {
    timedExecution.signal.addEventListener("abort", resolve, { once: true });
  });
  return { content: [{ type: "text", text: "late success" }] };
});
assert.equal(timeoutResult.isError, true);
assert.equal(timeoutResult.error.info.code, "TOOL_TIMEOUT");
assert.equal(timedExecution.signal, upstreamSignal);

const ordinaryResult = { content: [{ type: "text", text: "ok" }] };
const ordinaryExecution = { name: "unbounded", agent, signal: upstreamSignal };
assert.equal(await execute(ordinaryExecution, async () => ordinaryResult), ordinaryResult);

console.log("qualified plugin behavior verification passed");
