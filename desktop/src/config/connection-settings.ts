export type DesktopMode = "external" | "fake";
export type FakeScenario =
  | "empty-sessions"
  | "empty-workspaces"
  | "normal"
  | "rebuild-required"
  | "truncated";

export interface ConnectionSettings {
  fakeScenario: FakeScenario;
  mode: DesktopMode;
  gatewayUrl: string;
}

export type GatewayValidationCode =
  | "accepted"
  | "host"
  | "http"
  | "origin"
  | "parse"
  | "port"
  | "userinfo";

export interface GatewayUrlValidation {
  code: GatewayValidationCode;
  normalizedUrl: string | null;
  valid: boolean;
  message: string;
}

export const DEFAULT_GATEWAY_URL = "http://127.0.0.1:4311";

const SETTINGS_KEY = "beacon.ui.connection.v2";
const LEGACY_SETTINGS_KEY = "beacon.desktop.connection.v1";
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost"]);
const FAKE_SCENARIOS = new Set<FakeScenario>([
  "empty-sessions",
  "empty-workspaces",
  "normal",
  "rebuild-required",
  "truncated",
]);

export const validateGatewayUrl = (input: string): GatewayUrlValidation => {
  let url: URL;
  try {
    url = new URL(input.trim());
  } catch {
    return failure("parse", "Enter a complete loopback HTTP URL with an explicit port.");
  }
  if (url.protocol !== "http:") {
    return failure("http", "Only plain HTTP on local loopback is allowed.");
  }
  if (url.username !== "" || url.password !== "") {
    return failure("userinfo", "User information is not allowed in the Gateway URL.");
  }
  if (!LOOPBACK_HOSTS.has(url.hostname.toLowerCase())) {
    return failure("host", "Only 127.0.0.1 or localhost is allowed.");
  }
  if (url.port === "") {
    return failure("port", "An explicit loopback port is required.");
  }
  const port = Number(url.port);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    return failure("port", "The loopback port must be between 1 and 65535.");
  }
  if (url.pathname !== "/" || url.search !== "" || url.hash !== "") {
    return failure("origin", "Use only the Gateway origin; paths, queries, and fragments are not allowed.");
  }
  return {
    code: "accepted",
    normalizedUrl: url.origin,
    valid: true,
    message: "Loopback endpoint accepted. Redirects remain disabled.",
  };
};

export const readConnectionSettings = (): ConnectionSettings => {
  if (typeof localStorage === "undefined") {
    return defaults();
  }
  try {
    const parsed = JSON.parse(
      localStorage.getItem(SETTINGS_KEY)
      ?? localStorage.getItem(LEGACY_SETTINGS_KEY)
      ?? "null",
    ) as unknown;
    if (!isRecord(parsed)) {
      return defaults();
    }
    const mode = parsed.mode === "external" ? "external" : "fake";
    const candidate = typeof parsed.gatewayUrl === "string"
      ? parsed.gatewayUrl
      : DEFAULT_GATEWAY_URL;
    const validation = validateGatewayUrl(candidate);
    return {
      fakeScenario: readScenario(parsed.fakeScenario),
      mode,
      gatewayUrl: validation.normalizedUrl ?? DEFAULT_GATEWAY_URL,
    };
  } catch {
    return defaults();
  }
};

export const writeConnectionSettings = (settings: ConnectionSettings): void => {
  if (typeof localStorage === "undefined") {
    return;
  }
  const validation = validateGatewayUrl(settings.gatewayUrl);
  const safe = {
    schema: "beacon.ui.connection.v2",
    fakeScenario: settings.fakeScenario,
    mode: settings.mode,
    gatewayUrl: validation.normalizedUrl ?? DEFAULT_GATEWAY_URL,
  };
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(safe));
};

const defaults = (): ConnectionSettings => ({
  fakeScenario: "normal",
  mode: "fake",
  gatewayUrl: DEFAULT_GATEWAY_URL,
});

const failure = (code: GatewayValidationCode, message: string): GatewayUrlValidation => ({
  code,
  normalizedUrl: null,
  valid: false,
  message,
});

const isRecord = (value: unknown): value is Record<string, unknown> => (
  typeof value === "object" && value !== null && !Array.isArray(value)
);

const readScenario = (value: unknown): FakeScenario => (
  typeof value === "string" && FAKE_SCENARIOS.has(value as FakeScenario)
    ? value as FakeScenario
    : "normal"
);
