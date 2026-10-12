import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const require = createRequire(import.meta.url);
const expectedVersion = "0.1.1-rc.2";
const expectedPackages = [
  "@deepseek-ai/dsh",
  "@deepseek-ai/dsh-web-app",
  "@deepseek-ai/dsh-client-runtime",
  "@deepseek-ai/dsh-client-modules",
  "@deepseek-ai/dsh-client-connection",
  "@deepseek-ai/dsh-client-ui-layout",
  "@deepseek-ai/dsh-client-ui-renderer",
  "@deepseek-ai/dsh-host-webserver",
];
const requiredRuntimePeerVersions = {
  "@deepseek-ai/cordis-plugin-group": "1.0.1",
  "@deepseek-ai/dsh-anonymous-user-id": expectedVersion,
  "@deepseek-ai/dsh-atomic-write": expectedVersion,
  "@deepseek-ai/dsh-authorization": expectedVersion,
  "@deepseek-ai/dsh-bash-local": expectedVersion,
  "@deepseek-ai/dsh-code-runtime": expectedVersion,
  "@deepseek-ai/dsh-compaction": expectedVersion,
  "@deepseek-ai/dsh-fs": expectedVersion,
  "@deepseek-ai/dsh-invariants": expectedVersion,
  "@deepseek-ai/dsh-output-retention": expectedVersion,
  "@deepseek-ai/dsh-sandbox": expectedVersion,
  "@deepseek-ai/dsh-scope": expectedVersion,
  "@deepseek-ai/dsh-session-telemetry": expectedVersion,
  "@deepseek-ai/dsh-session-title-llm": expectedVersion,
  "@deepseek-ai/dsh-shell": expectedVersion,
  "@deepseek-ai/dsh-spill": expectedVersion,
  "@deepseek-ai/dsh-subagent-in-process-driver": expectedVersion,
  "@deepseek-ai/dsh-timeout": expectedVersion,
  "@deepseek-ai/dsh-workflow": expectedVersion,
};
const requiredDisabledRows = [
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

const versions = {};
for (const packageName of expectedPackages) {
  const packageJsonPath = require.resolve(`${packageName}/package.json`);
  const packageJson = JSON.parse(await readFile(packageJsonPath, "utf8"));
  if (packageJson.version !== expectedVersion) {
    throw new Error(
      `DSH compatibility gate: ${packageName}=${packageJson.version}, expected ${expectedVersion}`,
    );
  }
  versions[packageName] = packageJson.version;
}

const dshPackage = JSON.parse(
  await readFile(require.resolve("@deepseek-ai/dsh/package.json"), "utf8"),
);
if (typeof dshPackage.bin !== "object" || typeof dshPackage.bin.dsh !== "string") {
  throw new Error("DSH compatibility gate: @deepseek-ai/dsh CLI export is missing");
}

for (const entrypoint of [
  "@deepseek-ai/dsh-client-runtime/client",
  "@deepseek-ai/dsh-client-ui-layout/client",
  "@deepseek-ai/dsh-host-webserver",
]) {
  require.resolve(entrypoint);
}

const ownPackage = JSON.parse(await readFile(resolve(root, "package.json"), "utf8"));
if (
  ownPackage.dsh?.client?.platform !== "web"
  || ownPackage.dsh?.bundle?.patch !== "./cordis.patch.yml"
) {
  throw new Error("DSH compatibility gate: Beacon client/bundle declaration drifted");
}
const runtimePeerVersions = {};
for (const [packageName, expected] of Object.entries(requiredRuntimePeerVersions)) {
  if (ownPackage.dependencies?.[packageName] !== expected) {
    throw new Error(`DSH compatibility gate: ${packageName} is not directly pinned to ${expected}`);
  }
  const packageJson = JSON.parse(
    await readFile(require.resolve(`${packageName}/package.json`), "utf8"),
  );
  if (packageJson.version !== expected) {
    throw new Error(
      `DSH compatibility gate: ${packageName}=${packageJson.version}, expected ${expected}`,
    );
  }
  runtimePeerVersions[packageName] = packageJson.version;
}

const patch = await readFile(resolve(root, "cordis.patch.yml"), "utf8");
for (const id of requiredDisabledRows) {
  const pattern = new RegExp(`- id: ${id}\\r?\\n  disabled: true`, "u");
  if (!pattern.test(patch)) {
    throw new Error(`DSH compatibility gate: write-capable row ${id} is not disabled`);
  }
}
for (const id of retainedRows) {
  if (new RegExp(`- id: ${id}\\r?\\n  disabled: true`, "u").test(patch)) {
    throw new Error(`DSH compatibility gate: required official row ${id} was disabled`);
  }
}
if ((patch.match(/id: beacon-session-console/gu) ?? []).length !== 1) {
  throw new Error("DSH compatibility gate: expected exactly one Beacon console row");
}

const builder = await readFile(resolve(root, "scripts/build-client.mjs"), "utf8");
if (!builder.includes("window.__ModuleLoader__.load") || !builder.includes("return module.exports")) {
  throw new Error("DSH compatibility gate: reviewed client bundle handoff drifted");
}

process.stdout.write(`${JSON.stringify({
  schema: "beacon.dsh_console_compatibility_gate.v1",
  compatible: true,
  reviewedUpstreamCommit: "b150a551b8d465e31e418e1b2eaf5e79bbb7d28e",
  expectedVersion,
  versions,
  runtimePeerVersions,
  readOnlyRowsDisabled: requiredDisabledRows,
  retainedOfficialRows: retainedRows,
}, null, 2)}\n`);
