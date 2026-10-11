import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createHttpConsoleDataSource,
} from "@beacon-console/client/console-store.js";
import { ConsoleProtocolError } from "@beacon-console/shared/protocol.js";

const workspaceList = {
  schema: "beacon.console.v1",
  schemaMajor: 1,
  authority: "beacon",
  displayShell: "beacon_read_only_projection",
  readOnly: true,
  items: [],
  count: 0,
  sort: "displayName_asc_workspaceId_asc",
};

const gatewayHealth = {
  schema: "beacon.console.health.v1",
  schemaMajor: 1,
  consoleSchema: "beacon.console.v1",
  apiVersion: "1.0",
  status: "ready",
  authority: "beacon",
  source: "gateway",
  readOnly: true,
};

afterEach(() => {
  vi.useRealTimers();
});

describe("external Gateway GET-only source", () => {
  it("performs an explicit bounded Gateway version and health handshake", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(gatewayHealth));
    vi.stubGlobal("fetch", fetchMock);
    const source = createHttpConsoleDataSource({ baseUrl: "http://127.0.0.1:4311/api/console/v1" });

    await expect(source.checkHealth()).resolves.toEqual(gatewayHealth);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:4311/api/console/v1/health",
      expect.objectContaining({ method: "GET", credentials: "omit", redirect: "manual" }),
    );
  });

  it("sends a bounded credential-free GET and validates schema v1", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(workspaceList));
    vi.stubGlobal("fetch", fetchMock);
    const source = createHttpConsoleDataSource({ baseUrl: "http://127.0.0.1:4311/api/console/v1" });

    await expect(source.listWorkspaces()).resolves.toMatchObject({ schemaMajor: 1, readOnly: true });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:4311/api/console/v1/workspaces",
      expect.objectContaining({
        method: "GET",
        credentials: "omit",
        redirect: "manual",
      }),
    );
  });

  it("rejects incompatible schema, permission denial, redirect, oversize, and disconnect", async () => {
    const source = createHttpConsoleDataSource({ baseUrl: "http://127.0.0.1:4311/api/console/v1" });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ ...gatewayHealth, apiVersion: "2.0" })));
    await expect(source.checkHealth()).rejects.toMatchObject({ kind: "version" });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ ...gatewayHealth, status: "starting" })));
    await expect(source.checkHealth()).rejects.toMatchObject({ kind: "disconnected" });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ ...workspaceList, schemaMajor: 2 })));
    await expect(source.listWorkspaces()).rejects.toMatchObject({ kind: "version" });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 403 })));
    await expect(source.listWorkspaces()).rejects.toMatchObject({ kind: "permission" });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", {
      status: 302,
      headers: { location: "https://example.com" },
    })));
    await expect(source.listWorkspaces()).rejects.toMatchObject({ kind: "redirect" });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", {
      headers: { "content-length": "1048577" },
    })));
    await expect(source.listWorkspaces()).rejects.toMatchObject({ kind: "oversized" });

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await expect(source.listWorkspaces()).rejects.toMatchObject({ kind: "disconnected" });
  });

  it("aborts a stalled loopback read at the configured timeout", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((_: string, init: RequestInit) => (
      new Promise<Response>((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => {
          reject(new DOMException("aborted", "AbortError"));
        });
      })
    )));
    const source = createHttpConsoleDataSource({
      baseUrl: "http://127.0.0.1:4311/api/console/v1",
      timeoutMs: 5,
    });

    await expect(source.listWorkspaces()).rejects.toEqual(
      expect.objectContaining<Partial<ConsoleProtocolError>>({ kind: "timeout" }),
    );
  });
});

const jsonResponse = (payload: object): Response => new Response(JSON.stringify(payload), {
  headers: {
    "content-length": String(JSON.stringify(payload).length),
    "content-type": "application/json",
  },
  status: 200,
});
