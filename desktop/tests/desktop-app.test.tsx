import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConsoleSurface } from "@beacon-console/client/ConsoleSurface.js";
import { ConsoleStore } from "@beacon-console/client/console-store.js";

import { DesktopApp } from "../src/app/DesktopApp.js";
import { createFixtureConsoleDataSource } from "../src/data/fixture-source.js";

describe("Beacon Desktop read-only workflow", () => {
  it("starts offline in fake/local/read-only mode and renders the shared projection", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<DesktopApp />);

    expect(await screen.findByRole("heading", { name: "Sessions", level: 1 })).toBeTruthy();
    expect(screen.getByText("DEMO DATASET")).toBeTruthy();
    expect(screen.getByText("Synthetic examples — not activity from this computer.")).toBeTruthy();
    expect(screen.getByText("LOCAL")).toBeTruthy();
    expect(screen.getByText("READ ONLY")).toBeTruthy();
    expect(screen.getByText("Bounded activity projection")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Settings" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "DEMO DATASET" })).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("selects a session and presents compound identity, mapping, source, and recovery semantics", async () => {
    const user = userEvent.setup();
    render(<DesktopApp />);

    await screen.findByRole("heading", { name: "Sessions", level: 1 });
    await user.click(screen.getByRole("button", { name: "Codex · shared-native-01" }));

    const detail = screen.getByRole("article", { name: /Codex · shared-native-01/u });
    expect(within(detail).getByText("Native session ID — not guaranteed resumable.")).toBeTruthy();
    expect(within(detail).getByText("codex-handle-01")).toBeTruthy();
    expect(within(detail).getByText("Beacon mapping, not Provider-native identity.")).toBeTruthy();
    expect(within(detail).getByText("Codex builder")).toBeTruthy();
    expect(within(detail).getByText("Synthetic fixture")).toBeTruthy();

    await user.click(within(detail).getByRole("button", { name: "Clear selection" }));
    expect(screen.getByRole("heading", { name: "No session selected" })).toBeTruthy();
    expect(screen.queryByRole("article", { name: /Codex · shared-native-01/u })).toBeNull();
  });

  it("switches to a loopback external Gateway and exposes a safe disconnected diagnostic", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    const user = userEvent.setup();
    render(<DesktopApp />);

    await screen.findByRole("heading", { name: "Sessions", level: 1 });
    await user.click(screen.getByRole("button", { name: "Settings" }));
    await user.click(screen.getByRole("tab", { name: "Connection" }));
    await user.click(screen.getByRole("button", { name: /External Gateway/u }));
    await user.click(screen.getByRole("button", { name: "Apply settings" }));

    await waitFor(() => {
      expect(screen.getAllByText("Gateway disconnected").length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText(/No provider operation attempted/u).length).toBeGreaterThan(0);
    expect(screen.getByText("GET-only · loopback · redirects denied")).toBeTruthy();
  });

  it("applies and persists language, theme, contrast, and finite text scale from one settings entry", async () => {
    const user = userEvent.setup();
    render(<DesktopApp />);

    await screen.findByRole("heading", { name: "Sessions", level: 1 });
    await user.click(screen.getByRole("button", { name: "Settings" }));
    await user.click(screen.getByRole("button", { name: "简体中文" }));
    await user.click(screen.getByRole("button", { name: "Dark" }));
    await user.click(screen.getByRole("button", { name: "Enhanced" }));
    await user.click(screen.getByRole("button", { name: "110%" }));
    await user.click(screen.getByRole("button", { name: "Apply settings" }));

    expect(await screen.findByRole("heading", { name: "会话", level: 1 })).toBeTruthy();
    const app = document.querySelector<HTMLElement>(".bcd-app");
    expect(app?.dataset.theme).toBe("dark");
    expect(app?.dataset.contrast).toBe("enhanced");
    expect(app?.dataset.textScale).toBe("110");
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(localStorage.getItem("beacon.ui.preferences.v1")).not.toMatch(/token|credential|transcript/iu);
  });

  it("surfaces truncation and a projection-requested timeline rebuild", async () => {
    const source = createFixtureConsoleDataSource();
    const store = new ConsoleStore({
      ...source,
      async getWorkspaceView(workspaceId, cursor, limit) {
        const view = await source.getWorkspaceView(workspaceId, cursor, limit);
        view.timeline.page.truncated = true;
        view.timeline.page.rebuildRequired = true;
        return view;
      },
    });
    const rendered = render(<ConsoleSurface presentation="desktop" store={store} />);

    expect(await screen.findByText(/Timeline is truncated/u)).toBeTruthy();
    expect(screen.getByText(/Timeline rebuild required/u)).toBeTruthy();

    rendered.unmount();
    store.stop();
  });
});
