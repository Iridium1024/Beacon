import { readFileSync } from "node:fs";

import { expect, test, type Page, type Route } from "@playwright/test";

const fixture = JSON.parse(readFileSync(
  new URL("../../session-console/fixtures/console-demo.json", import.meta.url),
  "utf8",
)) as {
  providerBackends: Record<string, unknown>;
  workspaces: Record<string, unknown>;
  workspaceViews: Record<string, Record<string, unknown>>;
};

test("session-first view makes source, identity, and read-only boundaries explicit", async ({ page }) => {
  const logs = watchConsole(page);
  const gatewayRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().startsWith("http://127.0.0.1:4311/")) gatewayRequests.push(request.url());
  });
  await page.goto("/");

  await expect(page).toHaveTitle(/Beacon · Local read-only console/u);
  await expect(page.getByRole("heading", { name: "Sessions", level: 1 })).toBeVisible();
  await expect(page.getByText("DEMO DATASET", { exact: true })).toBeVisible();
  await expect(page.getByText("Synthetic examples — not activity from this computer.", { exact: true })).toBeVisible();
  await expect(page.getByText("LOCAL", { exact: true })).toBeVisible();
  await expect(page.getByText("READ ONLY", { exact: true })).toBeVisible();

  const detail = page.getByRole("article", { name: /Claude · shared-native-01/u });
  await expect(detail).toBeVisible();
  await expect(detail.getByText("claude-handle-01", { exact: false })).toBeVisible();
  await expect(detail.getByText("Beacon mapping, not Provider-native identity.", { exact: true })).toBeVisible();
  await expect(detail.getByText("Native session ID — not guaranteed resumable.", { exact: true })).toBeVisible();
  await expect(detail.getByText("Synthetic fixture", { exact: false })).toBeVisible();
  await expect(page.getByText("Bounded activity projection", { exact: true })).toBeVisible();
  await expect(page.getByText("Redacted Beacon events — not chat or transcript.", { exact: true })).toBeVisible();

  await expect(page.getByRole("button", { name: "Settings" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^(Create|Send|Queue|Resume|Cancel|Steer|Supplement|Approve|Approval|Reply)$/iu })).toHaveCount(0);
  await expect(page.locator("textarea")).toHaveCount(0);
  await expect(page.locator(".bc-secondary details[open]")).toHaveCount(0);
  await assertNoHorizontalOverflow(page);
  expect(gatewayRequests).toEqual([]);
  expect(logs).toEqual([]);
});

test("workspace, provider, and session controls are keyboard reachable and session selection updates detail", async ({ page }) => {
  const logs = watchConsole(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const workspace = page.getByRole("combobox", { name: "Workspace" }).first();
  await workspace.focus();
  await expect(workspace).toBeFocused();
  expect(await workspace.evaluate((node) => getComputedStyle(node).appearance)).not.toBe("none");

  const codexFilter = page.getByRole("button", { name: /Codex 2$/u });
  await codexFilter.focus();
  await page.keyboard.press("Enter");
  await expect(codexFilter).toHaveAttribute("aria-pressed", "true");

  const codexSession = page.getByRole("button", { name: "Codex · shared-native-01" });
  await codexSession.focus();
  await page.keyboard.press("Enter");
  await expect(codexSession).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("article", { name: "Codex · shared-native-01" })).toBeVisible();

  const clearSelection = page.getByRole("button", { name: "Clear selection" });
  await clearSelection.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "No session selected" })).toBeVisible();
  await expect(codexSession).toHaveAttribute("aria-pressed", "false");
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByRole("heading", { name: "No session selected" })).toBeVisible();
  await codexSession.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("article", { name: "Codex · shared-native-01" })).toBeVisible();

  const activity = page.locator(".bc-activity-projection > summary");
  await activity.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".bc-activity-projection")).toHaveAttribute("open", "");

  const eventTechnical = page.locator(".bc-event-technical").first();
  await eventTechnical.locator("> summary").focus();
  await page.keyboard.press("Enter");
  await expect(eventTechnical).toHaveAttribute("open", "");

  const help = page.locator(".bc-help-panel > summary");
  await help.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".bc-help-panel")).toHaveAttribute("open", "");

  const settings = page.getByRole("button", { name: "Settings", exact: true });
  await settings.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Settings" });
  const close = page.getByRole("button", { name: "Close", exact: true });
  await expect(dialog).toBeVisible();
  await expect(close).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("tab", { name: "General" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(settings).toBeFocused();
  expect(logs).toEqual([]);
});

test("header icons share an undistorted primitive and source/workspace/session anchors remain visible", async ({ page }) => {
  const logs = watchConsole(page);
  await page.goto("/");

  for (const name of ["Refresh", "Settings"]) {
    const button = page.getByRole("button", { name });
    const icon = button.locator("svg");
    await expect(icon).toHaveAttribute("viewBox", "0 0 24 24");
    const metrics = await icon.evaluate((node) => {
      const rect = node.getBoundingClientRect();
      return { height: rect.height, transform: getComputedStyle(node).transform, width: rect.width };
    });
    expect(metrics).toEqual({ height: 24, transform: "none", width: 24 });
  }

  await expect(page.getByRole("combobox", { name: "Workspace" }).first()).toBeVisible();
  await expect(page.getByRole("article", { name: /shared-native-01/u })).toBeVisible();
  await expect(page.getByRole("region", { name: "Data source" })).toBeVisible();
  expect(logs).toEqual([]);
});

test("settings localize source and failure copy and persist theme, contrast, and 90/100/110 text scales", async ({ page }) => {
  const logs = watchConsole(page);
  await page.goto("/");
  await expect(page.locator(".bcd-app")).toHaveAttribute("data-theme", "light");
  await expect(page.locator(".bcd-app")).toHaveAttribute("data-contrast", "standard");
  await expect(page.locator(".bcd-app")).toHaveAttribute("data-text-scale", "100");
  const heading = page.getByRole("heading", { name: "Sessions", level: 1 });
  const size100 = await heading.evaluate((node) => node.getBoundingClientRect().height);

  await applyGeneralSettings(page, { scale: "90%" });
  const size90 = await page.getByRole("heading", { name: "Sessions", level: 1 }).evaluate((node) => node.getBoundingClientRect().height);
  expect(size90).toBeLessThan(size100);

  await applyGeneralSettings(page, { scale: "100%" });
  expect(await page.getByRole("heading", { name: "Sessions", level: 1 }).evaluate((node) => node.getBoundingClientRect().height)).toBe(size100);

  await page.getByRole("button", { name: "Settings" }).click();
  await page.getByRole("button", { name: "简体中文" }).click();
  await page.getByRole("button", { name: "Dark" }).click();
  await page.getByRole("button", { name: "Enhanced" }).click();
  await page.getByRole("button", { name: "110%" }).click();
  await page.getByRole("button", { name: "Apply settings" }).click();

  const localizedHeading = page.getByRole("heading", { name: "会话", level: 1 });
  await expect(localizedHeading).toBeVisible();
  await expect(page.getByText("合成样例数据", { exact: true })).toBeVisible();
  await expect(page.getByText("合成示例，不是此计算机上的真实活动。", { exact: true })).toBeVisible();
  await expect(page.locator(".bcd-app")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator(".bcd-app")).toHaveAttribute("data-contrast", "enhanced");
  await expect(page.locator(".bcd-app")).toHaveAttribute("data-text-scale", "110");
  expect(await localizedHeading.evaluate((node) => node.getBoundingClientRect().height)).toBeGreaterThan(size100);
  await page.locator(".bcd-health").evaluate((node) => { (node as HTMLElement).style.visibility = "hidden"; });
  await expect(page).toHaveScreenshot("beacon-browser-dark-zh.png", snapshotOptions);

  await page.reload();
  await expect(page.getByRole("heading", { name: "会话", level: 1 })).toBeVisible();
  await expect(page.locator(".bcd-app")).toHaveAttribute("data-theme", "dark");
  expect(await page.evaluate(() => localStorage.getItem("beacon.ui.preferences.v1"))).not.toMatch(/credential|token|transcript|providerConfig|path/iu);
  await assertNoHorizontalOverflow(page);
  expect(logs).toEqual([]);
});

test("checked-in Fake scenarios explain empty, truncated, and rebuild states without claiming machine activity", async ({ page }) => {
  const logs = watchConsole(page);
  await page.goto("/");

  await chooseFakeScenario(page, "Empty workspaces — No workspace is available in the synthetic list.");
  await expect(page.getByRole("heading", { name: "No workspace projection" })).toBeVisible();
  await expect(page.getByText("Synthetic examples — not activity from this computer.", { exact: true })).toBeVisible();

  await chooseFakeScenario(page, "Empty sessions — Workspace data without session handles or activity.");
  await expect(page.getByText("No session handles in this workspace.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "No session selected" })).toBeVisible();

  await chooseFakeScenario(page, "Truncated timeline — The current timeline page is intentionally bounded.");
  await openActivity(page);
  await expect(page.getByText(/Timeline is truncated at the current page bound/u)).toBeVisible();

  await chooseFakeScenario(page, "Rebuild required — The projection asks the client to rebuild its bounded timeline.");
  await openActivity(page);
  await expect(page.getByText(/Timeline rebuild required by the projection/u)).toBeVisible();
  expect(logs).toEqual([]);
});

test("External mode accepts a compatible GET-only projection and localizes disconnected/version states", async ({ page }) => {
  const logs = watchConsole(page);
  const methods: string[] = [];
  await page.route("http://127.0.0.1:4311/**", async (route) => {
    methods.push(route.request().method());
    await fulfillGateway(route);
  });
  await page.goto("/");
  await chooseExternalMode(page);

  await expect(page.getByText("LOCAL BEACON GATEWAY", { exact: true })).toBeVisible();
  await expect(page.getByText("Read-only local Beacon Gateway projection; no Provider operation is performed.", { exact: true })).toBeVisible();
  await expect(page.getByText("Connected", { exact: true }).first()).toBeVisible();
  expect(new Set(methods)).toEqual(new Set(["GET"]));
  expect(methods.length).toBeGreaterThanOrEqual(4);

  await page.unroute("http://127.0.0.1:4311/**");
  await page.route("http://127.0.0.1:4311/**", async (route) => { await fulfillGateway(route, { status: "starting" }); });
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByText("Gateway disconnected", { exact: true }).first()).toBeVisible();

  await page.unroute("http://127.0.0.1:4311/**");
  await page.route("http://127.0.0.1:4311/**", async (route) => { await fulfillGateway(route, { apiVersion: "2.0" }); });
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("status").getByText("Version gate failed", { exact: true })).toBeVisible();
  expect(logs).toEqual([]);
});

test("wide, compact, narrow, and 125%-equivalent layouts stay overflow-free", async ({ page }) => {
  const logs = watchConsole(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sessions", level: 1 })).toBeVisible();
  await page.locator(".bcd-health").evaluate((node) => { (node as HTMLElement).style.visibility = "hidden"; });
  await assertNoHorizontalOverflow(page);
  await expect(page).toHaveScreenshot("beacon-browser-wide.png", snapshotOptions);

  await page.getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("dialog", { name: "Settings" })).toBeVisible();
  await expect(page).toHaveScreenshot("beacon-browser-settings.png", snapshotOptions);
  await page.getByRole("button", { name: "Close" }).click();

  await page.setViewportSize({ width: 1024, height: 768 });
  await assertNoHorizontalOverflow(page);
  await expect(page).toHaveScreenshot("beacon-browser-compact.png", snapshotOptions);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "Settings" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Providers" })).toBeVisible();
  await expect(page.getByRole("article", { name: /shared-native-01/u })).toBeVisible();
  await assertNoHorizontalOverflow(page);
  await expect(page).toHaveScreenshot("beacon-browser-narrow.png", snapshotOptions);

  await page.setViewportSize({ width: 819, height: 614 });
  await assertNoHorizontalOverflow(page);
  expect(logs).toEqual([]);
});

const applyGeneralSettings = async (page: Page, { scale }: { scale: "90%" | "100%" | "110%" }): Promise<void> => {
  await page.getByRole("button", { name: "Settings" }).click();
  await page.getByRole("button", { name: scale }).click();
  await page.getByRole("button", { name: "Apply settings" }).click();
};

const openActivity = async (page: Page): Promise<void> => {
  const detail = page.locator(".bc-activity-projection");
  if (await detail.getAttribute("open") === null) await detail.locator("> summary").click();
};

const chooseFakeScenario = async (page: Page, label: string): Promise<void> => {
  await page.getByRole("button", { name: "Settings" }).click();
  await page.getByRole("tab", { name: "Connection" }).click();
  await page.getByRole("combobox", { name: "Fake scenario" }).selectOption({ label });
  await page.getByRole("button", { name: "Apply settings" }).click();
};

const chooseExternalMode = async (page: Page): Promise<void> => {
  await page.getByRole("button", { name: "Settings" }).click();
  await page.getByRole("tab", { name: "Connection" }).click();
  await page.getByRole("button", { name: /External Gateway/u }).click();
  await page.getByRole("button", { name: "Apply settings" }).click();
};

const fulfillGateway = async (route: Route, healthOverride: Record<string, unknown> = {}): Promise<void> => {
  const url = new URL(route.request().url());
  const common = { headers: { "access-control-allow-origin": "http://127.0.0.1:1420", "content-type": "application/json" }, status: 200 };
  if (url.pathname.endsWith("/health")) {
    await route.fulfill({ ...common, json: { schema: "beacon.console.health.v1", schemaMajor: 1, consoleSchema: "beacon.console.v1", apiVersion: "1.0", status: "ready", authority: "beacon", source: "gateway", readOnly: true, ...healthOverride } });
    return;
  }
  if (url.pathname.endsWith("/workspaces")) { await route.fulfill({ ...common, json: fixture.workspaces }); return; }
  if (url.pathname.endsWith("/provider-backends")) { await route.fulfill({ ...common, json: fixture.providerBackends }); return; }
  const view = structuredClone(fixture.workspaceViews["workspace-demo"] ?? {});
  view.providerBackends = fixture.providerBackends.items ?? [];
  await route.fulfill({ ...common, json: view });
};

const assertNoHorizontalOverflow = async (page: Page): Promise<void> => {
  expect(await page.evaluate(() => ({ body: document.body.scrollWidth <= document.body.clientWidth, document: document.documentElement.scrollWidth <= document.documentElement.clientWidth }))).toEqual({ body: true, document: true });
};

const watchConsole = (page: Page): string[] => {
  const logs: string[] = [];
  page.on("console", (message) => { if (["error", "warning"].includes(message.type())) logs.push(`${message.type()}: ${message.text()}`); });
  page.on("pageerror", (error) => { logs.push(`pageerror: ${error.message}`); });
  return logs;
};

const snapshotOptions = { animations: "disabled", caret: "hide" } as const;
