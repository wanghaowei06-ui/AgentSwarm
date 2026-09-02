#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

const runtimeRoot = "/opt/agentteams/testweaver-native-worker/dsh-runtime";
const require = createRequire(import.meta.url);
const entrypoint = require.resolve("@deepseek-ai/dsh/lib/bin.js", {
  paths: [runtimeRoot],
});
const child = spawnSync(process.execPath, [entrypoint, ...process.argv.slice(2)], {
  stdio: "inherit",
});
if (child.error) {
  process.stderr.write(`dsh: ${child.error.message}\n`);
  process.exit(1);
}
process.exit(child.status ?? 1);
