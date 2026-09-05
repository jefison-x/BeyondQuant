import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { randomBytes } from "node:crypto";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn } from "node:child_process";

function run(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, ["./node_modules/wrangler/bin/wrangler.js", ...args], {
      cwd: new URL("..", import.meta.url),
      stdio: "inherit"
    });
    child.on("error", reject);
    child.on("exit", (code) => code === 0 ? resolve() : reject(new Error(`wrangler exited with ${code}`)));
  });
}

const directory = await mkdtemp(join(tmpdir(), "byq-feedback-dry-run-"));
try {
  const ephemeralSecret = () => randomBytes(32).toString("hex");
  const publisherToken = ephemeralSecret();
  const hubSecrets = join(directory, "hub.json");
  const publisherSecrets = join(directory, "publisher.json");
  await writeFile(hubSecrets, JSON.stringify({
    BYQ_FEEDBACK_HUB_STATUS_SECRET: ephemeralSecret(),
    BYQ_FEEDBACK_HUB_ADMIN_TOKEN: ephemeralSecret(),
    BYQ_FEEDBACK_PUBLISHER_TOKEN: publisherToken
  }), { mode: 0o600 });
  await writeFile(publisherSecrets, JSON.stringify({
    BYQ_FEEDBACK_PUBLISHER_TOKEN: publisherToken,
    BYQ_FEEDBACK_GITHUB_APP_ID: ephemeralSecret(),
    BYQ_FEEDBACK_GITHUB_INSTALLATION_ID: ephemeralSecret(),
    BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY: ephemeralSecret()
  }), { mode: 0o600 });
  await run(["deploy", "--config", "wrangler.hub.jsonc", "--dry-run", "--outdir", ".byq-build/hub", "--secrets-file", hubSecrets]);
  await run(["deploy", "--config", "wrangler.publisher.jsonc", "--dry-run", "--outdir", ".byq-build/publisher", "--secrets-file", publisherSecrets]);
} finally {
  await rm(directory, { recursive: true, force: true });
}
