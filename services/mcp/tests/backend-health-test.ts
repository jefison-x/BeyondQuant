import assert from "node:assert/strict";

import { fetchByqHealth } from "../src/backend-health.js";

const connectionFailure = await fetchByqHealth("http://backend:8000", async () => {
  throw new Error("connect ECONNREFUSED");
});
assert.equal(connectionFailure.isError, true);
assert.match(connectionFailure.content[0].text, /unreachable/);

const invalidResponse = await fetchByqHealth("http://backend:8000", async () =>
  new Response("not-json", { status: 200 }),
);
assert.equal(invalidResponse.isError, true);
assert.match(invalidResponse.content[0].text, /invalid_response/);

const timeoutSignal = await fetchByqHealth("http://backend:8000", async (_url, init) => {
  assert.ok(init?.signal);
  throw new DOMException("The operation timed out", "TimeoutError");
});
assert.equal(timeoutSignal.isError, true);
assert.match(timeoutSignal.content[0].text, /unreachable/);

console.log("Backend health failure handling PASS: connection, invalid response, timeout");
