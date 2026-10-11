import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const launcher = readFileSync(resolve(process.cwd(), "..", "start-beacon-browser.cmd"), "utf8");

describe("Windows browser entrypoint", () => {
  it("resolves the Beacon and desktop directories from its own location", () => {
    expect(launcher).toContain('set "BEACON_ROOT=%~dp0"');
    expect(launcher).toContain('set "DESKTOP_DIR=%BEACON_ROOT%desktop"');
    expect(launcher).not.toMatch(/\b[A-Za-z]:[\\/]/u);
  });

  it("fails closed when local tools, dependencies, or port 1420 are unavailable", () => {
    expect(launcher).toContain("where node.exe");
    expect(launcher).toContain("where npm.cmd");
    expect(launcher).toContain("node_modules\\.bin\\vite.cmd");
    expect(launcher).toContain("Get-NetTCPConnection -State Listen -LocalPort 1420");
    expect(launcher).toContain("Port 1420 is already in use");
    expect(launcher).toContain("did not become ready within 20 seconds");
  });

  it("uses the existing foreground package script and owns only the started host", () => {
    expect(launcher).toContain("call npm.cmd run browser:dev");
    expect(launcher).toContain("Invoke-WebRequest -UseBasicParsing -Uri $url");
    expect(launcher).toContain("AddSeconds(20)");
    expect(launcher).toContain("Stop-OwnedProcessTree");
    expect(launcher).toContain("Start-Process -FilePath $url");
    expect(launcher).not.toMatch(/npm\s+(?:ci|install)|start\s+\/b|taskkill\s+\/im/iu);
  });

  it("does not add a remote listener or start another Beacon subsystem", () => {
    expect(launcher).toContain("http://127.0.0.1:1420/");
    expect(launcher).not.toMatch(/0\.0\.0\.0|gateway|python|provider|tauri|dsh/iu);
  });
});
