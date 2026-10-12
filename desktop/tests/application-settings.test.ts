import { describe, expect, it } from "vitest";

import {
  readApplicationSettings,
  writeApplicationSettings,
} from "../src/config/application-settings.js";

describe("browser-local presentation preferences", () => {
  it("persists only the versioned language and appearance allowlist", () => {
    writeApplicationSettings({
      appearance: "dark",
      contrast: "enhanced",
      locale: "zh-CN",
      textScale: "110",
    });

    expect(readApplicationSettings()).toEqual({
      appearance: "dark",
      contrast: "enhanced",
      locale: "zh-CN",
      textScale: "110",
    });
    const serialized = localStorage.getItem("beacon.ui.preferences.v1") ?? "";
    expect(serialized).toContain('"schema":"beacon.ui.preferences.v1"');
    expect(serialized).not.toMatch(/credential|password|providerConfig|token|transcript|path/iu);
  });

  it("fails closed to finite defaults for malformed or unknown values", () => {
    localStorage.setItem("beacon.ui.preferences.v1", JSON.stringify({
      appearance: "neon",
      contrast: "maximum",
      locale: "fr-FR",
      textScale: "500",
    }));

    expect(readApplicationSettings()).toEqual({
      appearance: "system",
      contrast: "standard",
      locale: "en-US",
      textScale: "100",
    });
  });
});
