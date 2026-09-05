import assert from "node:assert/strict";
import test from "node:test";
import { deployHub, hubDeploymentCommands } from "./deploy-hub.mjs";

const create = ["d1", "create", "byq-feedback-hub", "--config", "wrangler.hub.jsonc"];
const migrate = ["d1", "migrations", "apply", "DB", "--remote", "--config", "wrangler.hub.jsonc"];
const deploy = ["deploy", "--config", "wrangler.hub.jsonc"];

test("first deployment creates D1 before migration and activation", () => {
  assert.deepEqual(hubDeploymentCommands([]), [create, migrate, deploy]);
});

test("later deployments reuse D1 and remain migration-first", () => {
  assert.deepEqual(hubDeploymentCommands([{ name: "byq-feedback-hub", uuid: "account-owned" }]), [migrate, deploy]);
});

test("deployment executes the planned commands without a shell", async () => {
  const calls = [];
  await deployHub({
    capture: async (args, options) => {
      calls.push([args, options]);
      return "[]";
    },
    run: async (args) => { calls.push([args]); }
  });
  assert.deepEqual(calls, [
    [["d1", "list", "--json", "--config", "wrangler.hub.jsonc"], { capture: true }],
    [create],
    [migrate],
    [deploy]
  ]);
});

test("invalid inventory fails closed before account mutation", async () => {
  const calls = [];
  await assert.rejects(
    deployHub({ capture: async () => "not-json", run: async (args) => { calls.push(args); } }),
    /invalid JSON/
  );
  assert.deepEqual(calls, []);
});

