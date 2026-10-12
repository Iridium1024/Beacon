import { cp, copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";

export const packageRoot = resolve(import.meta.dirname, "..");
const configuredRuntimeHome = process.env.BEACON_CONSOLE_DSH_HOME?.trim();
export const runtimeHome = configuredRuntimeHome
  ? resolve(configuredRuntimeHome)
  : resolve(packageRoot, ".runtime/dsh-home");
export const profileRoot = resolve(runtimeHome, "profiles/beacon-console");

export async function prepareProfile() {
  const packageCache = resolve(runtimeHome, "packages");
  await mkdir(profileRoot, { recursive: true });
  await mkdir(packageCache, { recursive: true });
  const packOutput = await runCapture(
    npmCommand,
    ["pack", packageRoot, "--pack-destination", packageCache, "--json"],
    packageRoot,
  );
  const packResult = JSON.parse(packOutput);
  const packedName = packResult?.[0]?.filename;
  if (typeof packedName !== "string" || !packedName.endsWith(".tgz")) {
    throw new Error("npm pack did not return a Beacon console tarball");
  }
  const packedPath = resolve(packageCache, packedName);
  const digest = createHash("sha256")
    .update(await readFile(packedPath))
    .digest("hex")
    .slice(0, 12);
  const tarballName = packedName.replace(/\.tgz$/u, `-${digest}.tgz`);
  await copyFile(packedPath, resolve(packageCache, tarballName));
  const manifest = {
    name: "@beacon-local/dsh-profile",
    version: "0.0.0-local",
    private: true,
    type: "module",
    dependencies: {
      "@beacon-local/dsh-session-console": `file:../../packages/${tarballName}`,
      "@deepseek-ai/dsh": "0.1.1-rc.2",
    },
    dsh: {
      profile: {
        bundles: [
          "@deepseek-ai/dsh-base",
          "@deepseek-ai/dsh-web-app",
          "@beacon-local/dsh-session-console",
        ],
      },
    },
  };
  await writeFile(
    resolve(profileRoot, "package.json"),
    `${JSON.stringify(manifest, null, 2)}\n`,
    "utf8",
  );
  await cp(resolve(packageRoot, "profile/cordis.patch.yml"), resolve(profileRoot, "cordis.patch.yml"));
  await run(
    npmCommand,
    ["install", "--ignore-scripts", "--no-audit", "--no-fund", "--legacy-peer-deps"],
    profileRoot,
  );
}

const npmCommand = [
  process.env.npm_execpath,
  resolve(dirname(process.execPath), "node_modules/npm/bin/npm-cli.js"),
].find((candidate) => typeof candidate === "string" && candidate.length > 0);

if (npmCommand === undefined) {
  throw new Error("Unable to resolve the project-local npm CLI");
}

const run = (command, args, cwd) => new Promise((resolvePromise, reject) => {
  const child = spawn(process.execPath, [command, ...args], {
    cwd,
    stdio: "inherit",
    windowsHide: true,
  });
  child.once("error", reject);
  child.once("exit", (code) => {
    if (code === 0) resolvePromise();
    else reject(new Error(`npm exited with ${code ?? "signal"}`));
  });
});

const runCapture = (command, args, cwd) => new Promise((resolvePromise, reject) => {
  const child = spawn(process.execPath, [command, ...args], {
    cwd,
    stdio: ["ignore", "pipe", "inherit"],
    windowsHide: true,
  });
  let stdout = "";
  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (chunk) => { stdout += chunk; });
  child.once("error", reject);
  child.once("exit", (code) => {
    if (code === 0) resolvePromise(stdout);
    else reject(new Error(`npm pack exited with ${code ?? "signal"}`));
  });
});

if (process.argv[1] !== undefined && resolve(process.argv[1]) === resolve(import.meta.filename)) {
  await prepareProfile();
  process.stdout.write(`${JSON.stringify({
    schema: "beacon.dsh_console_profile.v1",
    prepared: true,
    runtimeHome,
    profileRoot,
  }, null, 2)}\n`);
}
