import fixturePayload from "../../../session-console/fixtures/console-demo.json";

import type {
  ConsoleGatewayHealthResponse,
  ConsoleProviderBackendListResponse,
  ConsoleWorkspaceListResponse,
  ConsoleWorkspaceProjectionResponse,
} from "@beacon-console/shared/contracts.js";
import {
  ConsoleProtocolError,
  parseGatewayHealth,
  parseProviderBackends,
  parseWorkspaceList,
  parseWorkspaceProjection,
} from "@beacon-console/shared/protocol.js";
import type { ConsoleProjectionDataSource } from "@beacon-console/client/console-store.js";
import type { FakeScenario } from "../config/connection-settings.js";

interface DemoFixture {
  providerBackends: ConsoleProviderBackendListResponse;
  workspaces: ConsoleWorkspaceListResponse;
  workspaceViews: Record<string, ConsoleWorkspaceProjectionResponse>;
}

const fixture = fixturePayload as DemoFixture;

export const createFixtureConsoleDataSource = ({
  scenario = "normal",
}: {
  scenario?: FakeScenario;
} = {}): ConsoleProjectionDataSource => ({
  checkHealth() {
    return Promise.resolve(parseGatewayHealth(fakeHealth()));
  },
  listWorkspaces() {
    const workspaces = structuredClone(fixture.workspaces);
    if (scenario === "empty-workspaces") {
      workspaces.items = [];
      workspaces.count = 0;
    }
    return Promise.resolve(parseWorkspaceList(workspaces));
  },
  listProviderBackends() {
    return Promise.resolve(parseProviderBackends(structuredClone(fixture.providerBackends)));
  },
  getWorkspaceView(workspaceId, cursor, limit = 50) {
    const source = fixture.workspaceViews[workspaceId];
    if (source === undefined) {
      throw new ConsoleProtocolError("malformed", "Synthetic workspace was not found.");
    }
    const view = structuredClone(source);
    applyScenario(view, scenario);
    const events = view.timeline.events;
    const ordinal = parseCursor(cursor);
    const outOfRange = ordinal > events.length;
    const start = outOfRange ? 0 : ordinal;
    const boundedLimit = Math.min(200, Math.max(1, limit));
    const selected = events.slice(start, start + boundedLimit);
    view.providerBackends = structuredClone(fixture.providerBackends.items);
    view.timeline.events = selected;
    view.timeline.page = {
      cursor: cursor ?? null,
      nextCursor: `ord:${start + selected.length}`,
      limit: boundedLimit,
      returned: selected.length,
      total: events.length,
      hasMore: start + selected.length < events.length,
      truncated: scenario === "truncated" || start + selected.length < events.length,
      cursorOutOfRange: outOfRange,
      rebuildRequired: scenario === "rebuild-required" || outOfRange,
    };
    return Promise.resolve(parseWorkspaceProjection(view));
  },
});

const applyScenario = (
  view: ConsoleWorkspaceProjectionResponse,
  scenario: FakeScenario,
): void => {
  if (scenario !== "empty-sessions") {
    return;
  }
  view.sessions = [];
  view.dispatches = [];
  view.timeline.events = [];
  view.timeline.page.total = 0;
  view.limitations = [
    "Synthetic empty-session scenario: the workspace remains visible while session and activity collections are empty.",
  ];
};

const fakeHealth = (): ConsoleGatewayHealthResponse => ({
  schema: "beacon.console.health.v1",
  schemaMajor: 1,
  consoleSchema: "beacon.console.v1",
  apiVersion: "1.0",
  status: "ready",
  authority: "beacon",
  source: "synthetic",
  readOnly: true,
});

const parseCursor = (cursor: string | undefined): number => {
  if (cursor === undefined) {
    return 0;
  }
  const match = /^ord:(\d+)$/u.exec(cursor);
  if (match?.[1] === undefined) {
    throw new ConsoleProtocolError("malformed", "Synthetic cursor is invalid.");
  }
  return Number(match[1]);
};
