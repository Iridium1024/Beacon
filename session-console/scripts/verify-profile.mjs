import { readFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";

import { profileRoot, runtimeHome } from "./prepare-profile.mjs";

const require = createRequire(import.meta.url);
const dshPackagePath = require.resolve("@deepseek-ai/dsh/package.json");
const dshPackage = JSON.parse(await readFile(dshPackagePath, "utf8"));
const binPath = resolve(dirname(dshPackagePath), dshPackage.bin.dsh);
const result = spawnSync(
  process.execPath,
  [binPath, "--profile", "beacon-console", "--dump-config"],
  {
    cwd: resolve(import.meta.dirname, ".."),
    env: { ...process.env, DSH_HOME: runtimeHome },
    encoding: "utf8",
    maxBuffer: 16 * 1024 * 1024,
    windowsHide: true,
  },
);
if (result.status !== 0) {
  throw new Error(
    `DSH profile dump failed (${result.status ?? "signal"}): ${result.stderr.trim()}`,
  );
}
const dump = result.stdout;
if (dump.includes("[object Object]")) {
  throw new Error("DSH profile dump contains a malformed JavaScript config node");
}

const disabledRows = [
  "ui-sidebar",
  "ui-conversation",
  "ui-workspace",
  "ui-input-trigger",
  "ui-commands",
  "ui-permission",
  "ui-plan",
  "ui-user-questions",
];
const retainedRows = [
  "webserver",
  "modules",
  "connection",
  "api-remotes",
  "client-runtime",
  "ui-settings",
  "ui-theme",
  "locale",
  "ui-layout",
  "ui-renderer",
];
for (const id of disabledRows) {
  const block = rowBlock(dump, id);
  if (!block.includes("disabled: true")) {
    throw new Error(`DSH profile gate: ${id} is not disabled in the composed dump`);
  }
}
for (const id of retainedRows) {
  const block = rowBlock(dump, id);
  if (block.includes("disabled: true")) {
    throw new Error(`DSH profile gate: ${id} is disabled in the composed dump`);
  }
}
const pluginCount = dump.match(/^- id: beacon-session-console$/gmu)?.length ?? 0;
if (pluginCount !== 1) {
  throw new Error(`DSH profile gate: expected one Beacon row, found ${pluginCount}`);
}

const lock = JSON.parse(
  await readFile(resolve(profileRoot, "package-lock.json"), "utf8"),
);
const resolvedDsh = lock.packages?.["node_modules/@deepseek-ai/dsh"]?.version;
const resolvedConsole = lock.packages?.["node_modules/@beacon-local/dsh-session-console"]?.version;
if (resolvedDsh !== "0.1.1-rc.2" || resolvedConsole !== "0.1.0-spike.1") {
  throw new Error(
    `DSH profile gate: unexpected lock versions dsh=${resolvedDsh}, console=${resolvedConsole}`,
  );
}

process.stdout.write(`${JSON.stringify({
  schema: "beacon.dsh_console_profile_gate.v1",
  compatible: true,
  runtimeHome,
  profileRoot,
  dshVersion: resolvedDsh,
  consoleVersion: resolvedConsole,
  composedRows: (dump.match(/^- id:/gmu) ?? []).length,
  disabledRows,
  retainedRows,
  beaconPluginRows: pluginCount,
  malformedConfigNodes: 0,
}, null, 2)}\n`);

function rowBlock(source, id) {
  const marker = `- id: ${id}`;
  const start = source.indexOf(marker);
  if (start < 0) {
    throw new Error(`DSH profile gate: ${id} is missing from the composed dump`);
  }
  const next = source.indexOf("\n- id:", start + marker.length);
  return source.slice(start, next < 0 ? source.length : next);
}
