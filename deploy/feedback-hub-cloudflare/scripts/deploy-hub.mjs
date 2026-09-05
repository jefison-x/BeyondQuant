import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const config = "wrangler.hub.jsonc";
const databaseName = "byq-feedback-hub";
const wrangler = "./node_modules/wrangler/bin/wrangler.js";

export function hubDeploymentCommands(databases) {
  if (!Array.isArray(databases)) throw new Error("wrangler d1 list did not return an array");
  const commands = [];
  if (!databases.some((database) => database?.name === databaseName)) {
    commands.push(["d1", "create", databaseName, "--config", config]);
  }
  commands.push(["d1", "migrations", "apply", "DB", "--remote", "--config", config]);
  commands.push(["deploy", "--config", config]);
  return commands;
}

function runWrangler(args, { capture = false } = {}) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(process.execPath, [wrangler, ...args], {
      cwd: new URL("..", import.meta.url),
      stdio: capture ? ["ignore", "pipe", "inherit"] : "inherit"
    });
    let stdout = "";
    if (capture) child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0) resolvePromise(stdout);
      else reject(new Error(`wrangler ${args.join(" ")} exited with ${code}`));
    });
  });
}

export async function deployHub({ capture = runWrangler, run = runWrangler } = {}) {
  const rawDatabases = await capture(["d1", "list", "--json", "--config", config], { capture: true });
  let databases;
  try {
    databases = JSON.parse(rawDatabases);
  } catch (error) {
    throw new Error("wrangler d1 list returned invalid JSON", { cause: error });
  }
  for (const command of hubDeploymentCommands(databases)) await run(command);
}

const entrypoint = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : "";
if (entrypoint === import.meta.url) await deployHub();

