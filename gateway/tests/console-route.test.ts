import assert from "node:assert/strict";
import test from "node:test";

import type {
  ConsoleProjectionAdapter,
  ConsoleProviderBackendListResponse,
  ConsoleWorkspaceListResponse,
  ConsoleWorkspaceProjectionRequest,
  ConsoleWorkspaceProjectionResponse,
} from "../src/application/dto/console-api-contract.js";
import { DisconnectedConsoleProjectionAdapter } from "../src/application/services/console-api-service.js";
import { createConsoleProjectionRoutes } from "../src/infrastructure/http/routes/console-route.js";
import { createHttpServer } from "../src/infrastructure/http/server.js";

test("console route surface is GET-only and forwards bounded projection reads", async () => {
  const received: ConsoleWorkspaceProjectionRequest[] = [];
  const routes = createConsoleProjectionRoutes(fakeAdapter(received));
  assert.deepEqual(
    routes.map((route) => [route.method, route.path]),
    [
      ["GET", "/api/console/v1/health"],
      ["GET", "/api/console/v1/workspaces"],
      ["GET", "/api/console/v1/provider-backends"],
      ["GET", "/api/console/v1/workspaces/:workspaceId"],
    ],
  );
  assert.equal(routes.every((route) => route.method === "GET"), true);

  const server = createHttpServer("127.0.0.1", 0);
  for (const route of routes) {
    await server.registerRoute(route);
  }

  const health = await server.raw().inject({
    method: "GET",
    url: "/api/console/v1/health",
    headers: { origin: "http://tauri.localhost" },
  });
  assert.equal(health.statusCode, 200);
  assert.equal(health.headers["access-control-allow-origin"], "http://tauri.localhost");
  assert.deepEqual(health.json(), {
    schema: "beacon.console.health.v1",
    schemaMajor: 1,
    consoleSchema: "beacon.console.v1",
    apiVersion: "1.0",
    status: "ready",
    authority: "beacon",
    source: "gateway",
    readOnly: true,
  });

  const workspaces = await server.raw().inject({
    method: "GET",
    url: "/api/console/v1/workspaces",
    headers: { origin: "http://tauri.localhost" },
  });
  assert.equal(workspaces.statusCode, 200);
  assert.equal(workspaces.headers["cache-control"], "no-store");
  assert.equal(workspaces.headers["x-beacon-console-mode"], "local-read-only");
  assert.equal(workspaces.headers["access-control-allow-origin"], "http://tauri.localhost");
  assert.equal(workspaces.json().readOnly, true);

  const remoteOrigin = await server.raw().inject({
    method: "GET",
    url: "/api/console/v1/workspaces",
    headers: { origin: "https://example.com" },
  });
  assert.equal(remoteOrigin.statusCode, 200);
  assert.equal(remoteOrigin.headers["access-control-allow-origin"], undefined);

  const capabilities = await server.raw().inject({
    method: "GET",
    url: "/api/console/v1/provider-backends",
  });
  assert.equal(capabilities.statusCode, 200);

  const view = await server.raw().inject({
    method: "GET",
    url: "/api/console/v1/workspaces/workspace-fake?cursor=ord%3A4&communicationCursor=ledger%3A7&limit=25",
  });
  assert.equal(view.statusCode, 200);
  assert.deepEqual(received, [
    { workspaceId: "workspace-fake", cursor: "ord:4", communicationCursor: "ledger:7", limit: 25 },
  ]);

  for (const method of ["POST", "PUT", "DELETE", "PATCH"] as const) {
    const denied = await server.raw().inject({
      method,
      url: "/api/console/v1/workspaces/workspace-fake",
      payload: { prompt: "must not be accepted" },
    });
    assert.equal(denied.statusCode, 404);
  }

  const invalid = await server.raw().inject({
    method: "GET",
    url: "/api/console/v1/workspaces/workspace-fake?limit=201",
  });
  assert.equal(invalid.statusCode, 400);
  assert.equal(invalid.json().error.code, "invalid_request");

  await server.raw().close();
});

test("console routes fail closed when the Beacon bridge is disconnected", async () => {
  const server = createHttpServer("127.0.0.1", 0);
  for (const route of createConsoleProjectionRoutes(
    new DisconnectedConsoleProjectionAdapter(),
  )) {
    await server.registerRoute(route);
  }

  const response = await server.raw().inject({
    method: "GET",
    url: "/api/console/v1/workspaces",
  });
  assert.equal(response.statusCode, 503);
  assert.deepEqual(response.json(), {
    schema: "beacon.console.error.v1",
    readOnly: true,
    error: {
      code: "bridge_disconnected",
      message: "Local platform runtime bridge is not connected.",
    },
  });

  await server.raw().close();
});

const fakeAdapter = (
  received: ConsoleWorkspaceProjectionRequest[],
): ConsoleProjectionAdapter => ({
  async listWorkspaces(): Promise<ConsoleWorkspaceListResponse> {
    return {
      schema: "beacon.console.v1",
      schemaMajor: 1,
      authority: "beacon",
      displayShell: "beacon_read_only_projection",
      readOnly: true,
      items: [],
      count: 0,
      sort: "displayName_asc_workspaceId_asc",
    };
  },
  async listProviderBackends(): Promise<ConsoleProviderBackendListResponse> {
    return {
      schema: "beacon.console.v1",
      schemaMajor: 1,
      authority: "beacon",
      readOnly: true,
      items: [],
      count: 0,
      sort: "backendId_asc",
    };
  },
  async getWorkspaceView(
    request: ConsoleWorkspaceProjectionRequest,
  ): Promise<ConsoleWorkspaceProjectionResponse> {
    received.push(request);
    return {
      schema: "beacon.console.v1",
      schemaMajor: 1,
      authority: "beacon",
      displayShell: "beacon_read_only_projection",
      readOnly: true,
      workspace: {
        schema: "console_workspace_view.v1",
        workspaceId: request.workspaceId,
        displayName: "Fake workspace",
        rootSummary: "…/Demo Workspace",
        status: { value: "active", rawValue: "active", known: true },
        updatedAt: "2026-08-24T00:00:00Z",
        sourceEventSequence: 1,
      },
      agents: [],
      sessions: [],
      providerBackends: [],
      dispatches: [],
      timeline: {
        schema: "console_timeline_page.v1",
        events: [],
        page: {
          cursor: request.cursor ?? null,
          nextCursor: request.cursor ?? "ord:0",
          limit: request.limit ?? 50,
          returned: 0,
          total: 0,
          hasMore: false,
          truncated: false,
          cursorOutOfRange: false,
          rebuildRequired: false,
        },
        replay: {
          order: "workspaceOrdinal_asc_eventId_asc",
          duplicateEventIdPolicy: "first_sequence_wins",
          reconnect: "resume_from_nextCursor_or_rebuild_on_token_change",
          rebuildToken: "fixture",
          deterministicRebuild: true,
          polling: "bounded_get_polling_no_stream_claim",
        },
      },
      limitations: [],
    };
  },
});
