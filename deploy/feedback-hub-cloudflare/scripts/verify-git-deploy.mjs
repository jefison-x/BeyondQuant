import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { hubDeploymentCommands } from "./deploy-hub.mjs";

const readJson = async (name) => JSON.parse(await readFile(new URL(`../${name}`, import.meta.url), "utf8"));
const packageJson = await readJson("package.json");
const hub = await readJson("wrangler.hub.jsonc");
const publisher = await readJson("wrangler.publisher.jsonc");

assert.equal(hub.name, "byq-feedback-hub");
assert.equal(publisher.name, "byq-feedback-publisher");
assert.equal(hub.d1_databases?.[0]?.binding, "DB");
assert.equal(hub.d1_databases?.[0]?.database_name, "byq-feedback-hub");
assert.equal("database_id" in hub.d1_databases[0], false, "D1 must remain eligible for automatic provisioning");
assert.deepEqual(hub.secrets?.required, [
  "BYQ_FEEDBACK_HUB_STATUS_SECRET",
  "BYQ_FEEDBACK_HUB_ADMIN_TOKEN",
  "BYQ_FEEDBACK_PUBLISHER_TOKEN"
]);
assert.deepEqual(publisher.secrets?.required, [
  "BYQ_FEEDBACK_PUBLISHER_TOKEN",
  "BYQ_FEEDBACK_GITHUB_APP_ID",
  "BYQ_FEEDBACK_GITHUB_INSTALLATION_ID",
  "BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY"
]);
assert.equal(hub.queues?.producers?.[0]?.queue, "byq-feedback-publish");
assert.equal(publisher.queues?.consumers?.[0]?.queue, "byq-feedback-publish");
assert.equal(publisher.queues?.consumers?.[0]?.dead_letter_queue, "byq-feedback-publish-dlq");
assert.deepEqual(publisher.services?.[0], { binding: "HUB", service: "byq-feedback-hub" });
assert.equal(publisher.workers_dev, false);
assert.equal(hub.workers_dev, false);
assert.deepEqual(hub.durable_objects?.bindings?.find((binding) => binding.name === "ADMIN_LOGIN_GATE"),
  { name: "ADMIN_LOGIN_GATE", class_name: "AdminLoginGate" });
assert.deepEqual(hub.migrations?.at(-1), { tag: "v2", new_sqlite_classes: ["AdminLoginGate"] });
assert.equal(hub.vars.BYQ_FEEDBACK_GITHUB_REPOSITORY, "jefison-x/BeyondQuant");
assert.equal(publisher.vars.BYQ_FEEDBACK_GITHUB_REPOSITORY, "jefison-x/BeyondQuant");

const scripts = packageJson.scripts ?? {};
assert.equal(scripts["cloudflare:deploy:hub"], "node scripts/deploy-hub.mjs");
assert.deepEqual(hubDeploymentCommands([]).map((command) => command.slice(0, 3)), [
  ["d1", "create", "byq-feedback-hub"],
  ["d1", "migrations", "apply"],
  ["deploy", "--config", "wrangler.hub.jsonc"]
]);
assert.deepEqual(hubDeploymentCommands([{ name: "byq-feedback-hub" }]).map((command) => command[0]), ["d1", "deploy"]);
assert.equal(scripts["cloudflare:deploy:publisher"], "wrangler deploy --config wrangler.publisher.jsonc");
for (const command of Object.values(scripts)) {
  assert.doesNotMatch(String(command), /(?:secret put|secret bulk|--secrets-file .*production)/);
}

console.log("Cloudflare Git deployment contract PASS");
