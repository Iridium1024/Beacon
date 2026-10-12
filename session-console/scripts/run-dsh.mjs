import { access, readFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";

import { packageRoot, prepareProfile, runtimeHome } from "./prepare-profile.mjs";

const mode = process.argv[2] ?? "fake";
if (mode !== "fake" && mode !== "gateway") {
  throw new Error("run-dsh mode must be fake or gateway");
}
await access(resolve(packageRoot, "lib/client.js"));
await prepareProfile();

const require = createRequire(import.meta.url);
const dshPackagePath = require.resolve("@deepseek-ai/dsh/package.json");
const dshPackage = JSON.parse(await readFile(dshPackagePath, "utf8"));
const binPath = resolve(dirname(dshPackagePath), dshPackage.bin.dsh);
const child = spawn(
  process.execPath,
  [binPath, "--profile", "beacon-console", "--host", "127.0.0.1", "--port", "4179", "--no-open"],
  {
    cwd: packageRoot,
    env: {
      ...process.env,
      DSH_HOME: runtimeHome,
      BEACON_CONSOLE_MODE: mode,
      BEACON_CONSOLE_GATEWAY_URL: process.env.BEACON_CONSOLE_GATEWAY_URL ?? "http://127.0.0.1:4311",
    },
    stdio: "inherit",
    windowsHide: true,
  },
);

const stop = () => {
  if (!child.killed) child.kill("SIGTERM");
};
process.once("SIGINT", stop);
process.once("SIGTERM", stop);
child.once("error", (error) => { throw error; });
child.once("exit", (code, signal) => {
  process.exitCode = code ?? (signal === null ? 1 : 0);
});

