import { describe, expect, it, vi } from "vitest";

import { createFixtureConsoleDataSource } from "../src/data/fixture-source.js";

describe("offline fake projection", () => {
  it("loads the checked-in four-provider fixture without network access", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const source = createFixtureConsoleDataSource();
    const [health, workspaces, backends] = await Promise.all([
      source.checkHealth(),
      source.listWorkspaces(),
      source.listProviderBackends(),
    ]);
    const view = await source.getWorkspaceView(workspaces.items[0]?.workspaceId ?? "", undefined, 200);

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(health).toMatchObject({ apiVersion: "1.0", status: "ready", source: "synthetic" });
    expect(view.schema).toBe("beacon.console.v1");
    expect(view.readOnly).toBe(true);
    expect(new Set(view.sessions.map((session) => session.identity.provider))).toEqual(
      new Set(["claude", "codex", "hermes", "deepseek_harness"]),
    );
    expect(backends.items.some((backend) => backend.provider === "future_agent")).toBe(true);
    expect(view.timeline.events).toHaveLength(10);
    expect(collectKeys(view)).not.toEqual(expect.arrayContaining([
      "prompt",
      "transcript",
      "credential",
      "tool_output",
    ]));
  });

  it("implements bounded paging and signals an out-of-range rebuild", async () => {
    const source = createFixtureConsoleDataSource();
    const first = await source.getWorkspaceView("workspace-demo", undefined, 2);
    const second = await source.getWorkspaceView(
      "workspace-demo",
      first.timeline.page.nextCursor,
      2,
    );
    const outOfRange = await source.getWorkspaceView("workspace-demo", "ord:999", 2);

    expect(first.timeline.page).toMatchObject({ returned: 2, hasMore: true, truncated: true });
    expect(second.timeline.events[0]?.workspaceOrdinal).toBe(3);
    expect(outOfRange.timeline.page).toMatchObject({ cursorOutOfRange: true, rebuildRequired: true });
  });

  it("provides deterministic empty, truncated, and rebuild scenarios", async () => {
    const emptyWorkspaces = await createFixtureConsoleDataSource({
      scenario: "empty-workspaces",
    }).listWorkspaces();
    expect(emptyWorkspaces).toMatchObject({ count: 0, items: [] });

    const emptySessions = await createFixtureConsoleDataSource({
      scenario: "empty-sessions",
    }).getWorkspaceView("workspace-demo");
    expect(emptySessions.sessions).toEqual([]);
    expect(emptySessions.dispatches).toEqual([]);
    expect(emptySessions.timeline.events).toEqual([]);

    const truncated = await createFixtureConsoleDataSource({
      scenario: "truncated",
    }).getWorkspaceView("workspace-demo");
    expect(truncated.timeline.page.truncated).toBe(true);

    const rebuild = await createFixtureConsoleDataSource({
      scenario: "rebuild-required",
    }).getWorkspaceView("workspace-demo");
    expect(rebuild.timeline.page.rebuildRequired).toBe(true);
  });
});

const collectKeys = (value: unknown): string[] => {
  const keys: string[] = [];
  const pending: unknown[] = [value];
  while (pending.length > 0) {
    const current = pending.pop();
    if (Array.isArray(current)) {
      pending.push(...(current as unknown[]));
    } else if (typeof current === "object" && current !== null) {
      for (const [key, child] of Object.entries(current)) {
        keys.push(key.toLowerCase());
        pending.push(child);
      }
    }
  }
  return keys;
};
