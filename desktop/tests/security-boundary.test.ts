import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const root = resolve(import.meta.dirname, "..");

describe("local read-only Desktop/browser structural boundary", () => {
  it("grants the main window no Tauri command or plugin permission", () => {
    const capability = JSON.parse(read("src-tauri/capabilities/main-read-only.json")) as {
      permissions: unknown[];
      windows: string[];
    };
    const cargo = read("src-tauri/Cargo.toml");
    const rust = read("src-tauri/src/main.rs");

    expect(capability.windows).toEqual(["main"]);
    expect(capability.permissions).toEqual([]);
    expect(cargo).not.toMatch(/tauri-plugin-(shell|fs|sql|http|updater)/u);
    expect(rust).not.toContain("invoke_handler");
    expect(rust).toContain("on_navigation");
  });

  it("uses a restrictive CSP without unsafe-eval or remote navigation", () => {
    const config = JSON.parse(read("src-tauri/tauri.conf.json")) as {
      app: { security: { csp: string }; windows: Array<{ devtools: boolean }> };
    };
    const csp = config.app.security.csp;
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("connect-src 'self' http://127.0.0.1:*");
    expect(csp).toContain("object-src 'none'");
    expect(csp).not.toContain("unsafe-eval");
    expect(config.app.windows.every((window) => !window.devtools)).toBe(true);
  });

  it("contains no client write method or Provider-control surface", () => {
    const store = read("../session-console/src/client/console-store.ts");
    const desktop = read("src/app/DesktopApp.tsx");
    expect(store).toContain('method: "GET"');
    expect(store).not.toMatch(/method:\s*"(POST|PUT|PATCH|DELETE)"/u);
    expect(desktop).not.toMatch(/\b(send|queue|resume|cancel|steer|supplement|approval|replyWriteback)\s*\(/u);
  });
});

const read = (path: string): string => readFileSync(resolve(root, path), "utf8");
