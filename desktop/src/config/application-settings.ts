import type { AppearanceMode } from "@beacon-console/client/console-store.js";
import type { ConsoleLocale } from "@beacon-console/client/i18n.js";

export type ContrastMode = "enhanced" | "standard";
export type TextScale = "100" | "110" | "90";

export interface ApplicationSettings {
  appearance: AppearanceMode;
  contrast: ContrastMode;
  locale: ConsoleLocale;
  textScale: TextScale;
}

const SETTINGS_KEY = "beacon.ui.preferences.v1";
const APPEARANCE = new Set<AppearanceMode>(["dark", "light", "system"]);
const TEXT_SCALES = new Set<TextScale>(["90", "100", "110"]);

export const readApplicationSettings = (): ApplicationSettings => {
  if (typeof localStorage === "undefined") {
    return defaults();
  }
  try {
    const value = JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? "null") as unknown;
    if (!isRecord(value)) {
      return defaults();
    }
    return {
      appearance: typeof value.appearance === "string" && APPEARANCE.has(value.appearance as AppearanceMode)
        ? value.appearance as AppearanceMode
        : "system",
      contrast: value.contrast === "enhanced" ? "enhanced" : "standard",
      locale: value.locale === "zh-CN" ? "zh-CN" : "en-US",
      textScale: typeof value.textScale === "string" && TEXT_SCALES.has(value.textScale as TextScale)
        ? value.textScale as TextScale
        : "100",
    };
  } catch {
    return defaults();
  }
};

export const writeApplicationSettings = (settings: ApplicationSettings): void => {
  if (typeof localStorage === "undefined") {
    return;
  }
  const safe: ApplicationSettings & { schema: "beacon.ui.preferences.v1" } = {
    schema: "beacon.ui.preferences.v1",
    appearance: APPEARANCE.has(settings.appearance) ? settings.appearance : "system",
    contrast: settings.contrast === "enhanced" ? "enhanced" : "standard",
    locale: settings.locale === "zh-CN" ? "zh-CN" : "en-US",
    textScale: TEXT_SCALES.has(settings.textScale) ? settings.textScale : "100",
  };
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(safe));
};

const defaults = (): ApplicationSettings => ({
  appearance: "system",
  contrast: "standard",
  locale: "en-US",
  textScale: "100",
});

const isRecord = (value: unknown): value is Record<string, unknown> => (
  typeof value === "object" && value !== null && !Array.isArray(value)
);
