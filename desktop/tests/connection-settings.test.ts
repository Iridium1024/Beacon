import { describe, expect, it } from "vitest";

import {
  DEFAULT_GATEWAY_URL,
  readConnectionSettings,
  validateGatewayUrl,
  writeConnectionSettings,
} from "../src/config/connection-settings.js";

describe("external Gateway URL fence", () => {
  it.each([
    ["http://127.0.0.1:4311", "http://127.0.0.1:4311"],
    ["http://localhost:4311", "http://localhost:4311"],
  ])("accepts the explicit loopback origin %s", (input, normalized) => {
    expect(validateGatewayUrl(input)).toEqual({
      code: "accepted",
      normalizedUrl: normalized,
      valid: true,
      message: "Loopback endpoint accepted. Redirects remain disabled.",
    });
  });

  it.each([
    "https://127.0.0.1:4311",
    "http://0.0.0.0:4311",
    "http://192.168.1.5:4311",
    "http://[::1]:4311",
    "http://example.com:4311",
    "http://user:secret@127.0.0.1:4311",
    "http://127.0.0.1",
    "http://127.0.0.1:4311/api/console/v1",
    "http://127.0.0.1:4311/?token=secret",
    "file:///C:/Beacon",
  ])("rejects unsafe endpoint %s", (input) => {
    expect(validateGatewayUrl(input).valid).toBe(false);
  });

  it("persists only the schema, mode, and normalized loopback URL", () => {
    writeConnectionSettings({
      fakeScenario: "truncated",
      mode: "external",
      gatewayUrl: "http://LOCALHOST:4311",
    });
    expect(readConnectionSettings()).toEqual({
      fakeScenario: "truncated",
      mode: "external",
      gatewayUrl: "http://localhost:4311",
    });
    const serialized = localStorage.getItem("beacon.ui.connection.v2") ?? "";
    expect(serialized).toContain('"schema":"beacon.ui.connection.v2"');
    expect(serialized).not.toMatch(/token|credential|password|transcript/iu);
  });

  it("fails closed to fake mode when stored settings are malformed", () => {
    localStorage.setItem("beacon.desktop.connection.v1", "not-json");
    expect(readConnectionSettings()).toEqual({
      fakeScenario: "normal",
      mode: "fake",
      gatewayUrl: DEFAULT_GATEWAY_URL,
    });
  });
});
