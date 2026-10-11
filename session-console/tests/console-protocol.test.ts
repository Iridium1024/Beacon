import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import type {
  ConsoleProviderBackendListResponse,
  ConsoleWorkspaceProjectionResponse,
} from "../src/shared/contracts.js";
import {
  ConsoleProtocolError,
  mergeTimeline,
  parseGatewayHealth,
  parseProviderBackends,
  parseWorkspaceProjection,
  rebuildTimeline,
} from "../src/shared/protocol.js";
import { CONSOLE_STYLES } from "../src/client/styles.js";

const root = resolve(import.meta.dirname, "..");
const fixture = JSON.parse(
  readFileSync(resolve(root, "fixtures/console-demo.json"), "utf8"),
) as Fixture;
const workspaceId = "workspace-demo";

describe("P3-A fake acceptance matrix", () => {
  it("1. preserves compound identity across four platforms and collisions", () => {
    const view = projection();
    const colliding = view.sessions.filter(
      (session) => session.identity.nativeSessionId === "shared-native-01",
    );
    expect(new Set(colliding.map((session) => session.identity.provider))).toEqual(
      new Set(["claude", "codex", "hermes", "deepseek_harness"]),
    );
    expect(new Set(colliding.map((session) => (
      `${session.identity.provider}:${session.identity.nativeSessionId}`
    ))).size).toBe(4);
  });

  it("2. keeps exchange, delivery dispatch, and backend layers explicit", () => {
    const view = projection();
    expect(view.dispatches.length).toBeGreaterThan(0);
    for (const dispatch of view.dispatches) {
      expect(dispatch.exchangeRequestId).toMatch(/^request-/u);
      expect(dispatch.apiLayer).toBe("delivery-oriented");
      expect(dispatch.targetProvider).not.toBeNull();
    }
  });

  it("3. displays DSH persistent-session continuity without converting foreign sessions", () => {
    const view = projection();
    const dsh = view.sessions.filter(
      (session) => session.identity.provider === "deepseek_harness",
    );
    const foreign = view.sessions.filter(
      (session) => session.identity.provider !== "deepseek_harness",
    );
    expect(dsh.every((session) => session.nativeDshSession && !session.foreignProjectionOnly)).toBe(true);
    expect(foreign.every((session) => !session.nativeDshSession && session.foreignProjectionOnly)).toBe(true);
    expect(dsh.some((session) => session.continuity.state === "resume_required")).toBe(true);
    expect(dsh.every((session) => session.continuity.scope === "persistent_native_session")).toBe(true);
    expect(dsh.every((session) => session.continuity.resumeAcrossRuntimeRestart === true)).toBe(true);
  });

  it("4. exposes backend differences as Beacon implementation facts", () => {
    const backends = parseProviderBackends(fixture.providerBackends);
    const byId = new Map(backends.items.map((item) => [item.backendId, item]));
    expect(byId.get("codex_app_server_stdio")?.capabilities.canSupplementActiveTurn).toBe(true);
    expect(byId.get("codex_app_server_stdio")?.capabilities.canHandleApprovalRequests).toBe(true);
    expect(byId.get("hermes_tui_gateway_stdio")?.capabilities.canCancel).toBe(true);
    expect(byId.get("claude_agent_sdk")?.capabilities.canReadStatus).toBe(false);
    expect(byId.get("deepseek_harness_sdk_stdio")?.statusAuthority.value).toBe("owned_live");
    expect(byId.get("deepseek_harness_sdk_stdio")?.capabilities.canResumeAcrossProcess).toBe(true);
    expect(byId.get("deepseek_harness_sdk_stdio")?.existingSessionImport).toBe(true);
  });

  it("5. preserves unknown enum raw values without crashing", () => {
    const view = projection();
    const unknown = view.timeline.events.find((event) => !event.category.known);
    expect(unknown?.category.value).toBe("unknown");
    expect(unknown?.category.rawValue).toBe("future_runtime_note");
    const futureBackend = view.providerBackends.find(
      (backend) => backend.provider === "future_agent",
    );
    expect(futureBackend?.lifecycle).toEqual({
      value: "unknown",
      rawValue: "shared_runtime_v2",
      known: false,
    });
    expect(futureBackend?.capabilities.canReadStatus).toBeNull();
  });

  it("6. deduplicates replay, reports truncation, and detects page gaps", () => {
    const base = projection().timeline;
    const first = structuredClone(base);
    first.events = first.events.slice(0, 2);
    first.page.nextCursor = "ord:2";
    first.page.hasMore = true;
    first.page.truncated = true;
    const accumulated = rebuildTimeline(first);
    expect(accumulated.truncated).toBe(true);

    const replay = structuredClone(base);
    replay.events = [base.events[1]!, base.events[2]!];
    replay.page.nextCursor = "ord:3";
    const merged = mergeTimeline(accumulated, replay);
    expect(merged.events.map((event) => event.eventId)).toEqual([
      "demo-event-001",
      "demo-event-002",
      "demo-event-003",
    ]);

    const gap = structuredClone(base);
    gap.events = [base.events[4]!];
    gap.page.nextCursor = "ord:5";
    expect(mergeTimeline(accumulated, gap).gapDetected).toBe(true);

    const newGeneration = structuredClone(base);
    newGeneration.replay.rebuildToken = "replacement-generation";
    newGeneration.events = [base.events[0]!];
    const rebuiltGeneration = mergeTimeline(merged, newGeneration);
    expect(rebuiltGeneration.events).toHaveLength(1);
    expect(rebuiltGeneration.rebuildRequired).toBe(true);

    const explicitRebuild = structuredClone(base);
    explicitRebuild.page.rebuildRequired = true;
    expect(mergeTimeline(merged, explicitRebuild).rebuildRequired).toBe(true);
  });

  it("7. rejects malformed, oversized, and sensitive projections", () => {
    expect(parseGatewayHealth({
      schema: "beacon.console.health.v1",
      schemaMajor: 1,
      consoleSchema: "beacon.console.v1",
      apiVersion: "1.0",
      status: "ready",
      authority: "beacon",
      source: "gateway",
      readOnly: true,
    }).status).toBe("ready");
    expect(() => parseGatewayHealth({
      schema: "beacon.console.health.v1",
      schemaMajor: 1,
      consoleSchema: "beacon.console.v1",
      apiVersion: "2.0",
      status: "ready",
      authority: "beacon",
      source: "gateway",
      readOnly: true,
    })).toThrowError(/version/u);

    const malformed = structuredClone(fixture.workspaceViews[workspaceId]!);
    delete (malformed as Partial<ConsoleWorkspaceProjectionResponse>).timeline;
    expect(() => parseWorkspaceProjection(malformed)).toThrow(ConsoleProtocolError);

    const oversized = structuredClone(fixture.workspaceViews[workspaceId]!);
    oversized.workspace.displayName = "x".repeat(2_049);
    expect(() => parseWorkspaceProjection(oversized)).toThrowError(/exceeded/u);

    const sensitive = structuredClone(fixture.workspaceViews[workspaceId]!) as unknown as Record<string, unknown>;
    sensitive.prompt = "forbidden";
    expect(() => parseWorkspaceProjection(sensitive)).toThrowError(/forbidden field/u);
  });

  it("8. has no write route or client control method", () => {
    const host = readFileSync(resolve(root, "src/host/index.ts"), "utf8");
    const store = readFileSync(resolve(root, "src/client/console-store.ts"), "utf8");
    const patch = readFileSync(resolve(root, "cordis.patch.yml"), "utf8");
    expect(host).toContain('request.method !== "GET" && request.method !== "HEAD"');
    expect(store).not.toMatch(/\b(prompt|resume|cancel|steer|supplement|approve|reply|enqueue|dispatch)\s*=/u);
    for (const id of ["ui-conversation", "ui-input-trigger", "ui-commands", "ui-permission", "ui-plan"]) {
      expect(patch).toMatch(new RegExp(`- id: ${id}\\r?\\n  disabled: true`, "u"));
    }
  });

  it("9. includes light/dark/system, focus, narrow, contrast, and reduced-motion behavior", () => {
    expect(CONSOLE_STYLES).toContain('[data-theme="dark"]');
    expect(CONSOLE_STYLES).toContain(":focus-visible");
    expect(CONSOLE_STYLES).toContain("@media(max-width:620px)");
    expect(CONSOLE_STYLES).toContain("prefers-contrast:more");
    expect(CONSOLE_STYLES).toContain("prefers-reduced-motion:reduce");
    expect(CONSOLE_STYLES).toContain("prefers-reduced-transparency:reduce");
  });

  it("10. fails closed outside the exact reviewed DSH release", () => {
    const output = execFileSync(
      process.execPath,
      [resolve(root, "scripts/compatibility-gate.mjs")],
      { cwd: root, encoding: "utf8" },
    );
    const result = JSON.parse(output) as { compatible: boolean; expectedVersion: string };
    expect(result.compatible).toBe(true);
    expect(result.expectedVersion).toBe("0.1.1-rc.2");
  });
});

const projection = (): ConsoleWorkspaceProjectionResponse => {
  const view = structuredClone(fixture.workspaceViews[workspaceId]!);
  view.providerBackends = structuredClone(fixture.providerBackends.items);
  return parseWorkspaceProjection(view);
};

interface Fixture {
  providerBackends: ConsoleProviderBackendListResponse;
  workspaceViews: Record<string, ConsoleWorkspaceProjectionResponse>;
}
