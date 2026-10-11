import { readFile } from "node:fs/promises";
import type { IncomingMessage, ServerResponse } from "node:http";
import { fileURLToPath } from "node:url";

import type { Context } from "@deepseek-ai/cordis";
import type {} from "@deepseek-ai/dsh-host-webserver";

const ROUTE_PREFIX = "/beacon-console/api";
const GATEWAY_PREFIX = "/api/console/v1";
const DEFAULT_GATEWAY = "http://127.0.0.1:4311";
const DEFAULT_TIMEOUT_MS = 5_000;
const DEFAULT_MAX_RESPONSE_BYTES = 1_048_576;

export interface Config {
  mode?: "fake" | "gateway";
  bridgeBaseUrl?: string;
  fixturePath?: string;
  timeoutMs?: number;
  maxResponseBytes?: number;
}

export const inject = ["webServer"];

/** DSH Host half: one loopback-only, GET-only projection route. */
export function apply(ctx: Context, config: Config = {}): void {
  if (ctx.webServer.host !== "127.0.0.1") {
    throw new Error(
      "beacon-console: DSH Web must bind 127.0.0.1; host fencing is not authentication",
    );
  }
  const resolved = resolveConfig(config);
  ctx.effect(
    () => ctx.webServer.register({
      kind: "prefix",
      path: ROUTE_PREFIX,
      handler: (request, response) => handleRequest(request, response, resolved),
    }),
    "beacon-console: read-only projection route",
  );
}

interface ResolvedConfig {
  mode: "fake" | "gateway";
  bridgeBaseUrl: URL;
  fixturePath: string;
  timeoutMs: number;
  maxResponseBytes: number;
}

const resolveConfig = (config: Config): ResolvedConfig => {
  const mode = config.mode ?? "fake";
  if (mode !== "fake" && mode !== "gateway") {
    throw new Error("beacon-console: mode must be fake or gateway");
  }
  const bridgeBaseUrl = new URL(config.bridgeBaseUrl ?? DEFAULT_GATEWAY);
  if (
    bridgeBaseUrl.protocol !== "http:"
    || !["127.0.0.1", "[::1]", "::1"].includes(bridgeBaseUrl.hostname)
  ) {
    throw new Error("beacon-console: bridgeBaseUrl must be an HTTP loopback URL");
  }
  const timeoutMs = boundedInteger(
    config.timeoutMs,
    DEFAULT_TIMEOUT_MS,
    250,
    30_000,
    "timeoutMs",
  );
  const maxResponseBytes = boundedInteger(
    config.maxResponseBytes,
    DEFAULT_MAX_RESPONSE_BYTES,
    16_384,
    2_097_152,
    "maxResponseBytes",
  );
  return {
    mode,
    bridgeBaseUrl,
    fixturePath: config.fixturePath
      ?? fileURLToPath(new URL("../fixtures/console-demo.json", import.meta.url)),
    timeoutMs,
    maxResponseBytes,
  };
};

const boundedInteger = (
  value: number | undefined,
  fallback: number,
  minimum: number,
  maximum: number,
  field: string,
): number => {
  const resolved = value ?? fallback;
  if (!Number.isInteger(resolved) || resolved < minimum || resolved > maximum) {
    throw new Error(
      `beacon-console: ${field} must be an integer between ${minimum} and ${maximum}`,
    );
  }
  return resolved;
};

const handleRequest = async (
  request: IncomingMessage,
  response: ServerResponse,
  config: ResolvedConfig,
): Promise<void> => {
  setHeaders(response);
  if (request.method !== "GET" && request.method !== "HEAD") {
    sendJson(response, 405, {
      schema: "beacon.console.error.v1",
      readOnly: true,
      error: { code: "method_not_allowed", message: "Only GET and HEAD are available." },
    }, request.method === "HEAD");
    return;
  }
  const url = new URL(request.url ?? ROUTE_PREFIX, "http://127.0.0.1");
  const suffix = url.pathname.slice(ROUTE_PREFIX.length) || "/workspaces";
  if (!validProjectionSuffix(suffix)) {
    sendJson(response, 404, {
      schema: "beacon.console.error.v1",
      readOnly: true,
      error: { code: "not_found", message: "Projection route not found." },
    }, request.method === "HEAD");
    return;
  }
  try {
    const payload = config.mode === "fake"
      ? await fakePayload(config.fixturePath, suffix, url.searchParams)
      : await gatewayPayload(config, suffix, url.searchParams);
    sendJson(response, 200, payload, request.method === "HEAD");
  } catch (error) {
    const status = error instanceof ProjectionError ? error.status : 502;
    const code = error instanceof ProjectionError ? error.code : "projection_unavailable";
    const message = error instanceof ProjectionError
      ? error.message
      : "Beacon projection is unavailable.";
    sendJson(response, status, {
      schema: "beacon.console.error.v1",
      readOnly: true,
      error: { code, message },
    }, request.method === "HEAD");
  }
};

const setHeaders = (response: ServerResponse): void => {
  response.setHeader("cache-control", "no-store");
  response.setHeader("content-type", "application/json; charset=utf-8");
  response.setHeader("x-content-type-options", "nosniff");
  response.setHeader("x-beacon-console-mode", "local-read-only");
  response.setHeader("content-security-policy", "default-src 'none'; frame-ancestors 'none'");
};

const sendJson = (
  response: ServerResponse,
  status: number,
  payload: object,
  headOnly: boolean,
): void => {
  const body = JSON.stringify(payload);
  response.statusCode = status;
  response.setHeader("content-length", Buffer.byteLength(body));
  response.end(headOnly ? undefined : body);
};

const validProjectionSuffix = (suffix: string): boolean => {
  if (suffix === "/health" || suffix === "/workspaces" || suffix === "/provider-backends") {
    return true;
  }
  return /^\/workspaces\/[^/]+$/u.test(suffix);
};

const gatewayPayload = async (
  config: ResolvedConfig,
  suffix: string,
  searchParams: URLSearchParams,
): Promise<object> => {
  const target = new URL(`${GATEWAY_PREFIX}${suffix}`, config.bridgeBaseUrl);
  target.search = searchParams.toString();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.timeoutMs);
  try {
    const response = await fetch(target, {
      method: "GET",
      headers: { accept: "application/json" },
      signal: controller.signal,
      redirect: "error",
    });
    const contentLength = Number(response.headers.get("content-length") ?? "0");
    if (contentLength > config.maxResponseBytes) {
      throw new ProjectionError(502, "response_too_large", "Projection response exceeded the local limit.");
    }
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength > config.maxResponseBytes) {
      throw new ProjectionError(502, "response_too_large", "Projection response exceeded the local limit.");
    }
    const payload: unknown = JSON.parse(new TextDecoder().decode(bytes));
    if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
      throw new ProjectionError(502, "malformed_projection", "Projection response was not a JSON object.");
    }
    if (!response.ok) {
      throw new ProjectionError(
        response.status,
        response.status === 403 ? "permission_denied" : "bridge_error",
        response.status === 403 ? "Projection permission was denied." : "Beacon Gateway rejected the projection read.",
      );
    }
    return payload as object;
  } catch (error) {
    if (error instanceof ProjectionError) {
      throw error;
    }
    if (error instanceof SyntaxError) {
      throw new ProjectionError(502, "malformed_projection", "Projection response was malformed JSON.");
    }
    throw new ProjectionError(503, "bridge_disconnected", "Beacon Gateway is disconnected.");
  } finally {
    clearTimeout(timer);
  }
};

interface DemoFixture {
  workspaces: object;
  providerBackends: object;
  workspaceViews: Record<string, Record<string, unknown>>;
}

const fakePayload = async (
  fixturePath: string,
  suffix: string,
  searchParams: URLSearchParams,
): Promise<object> => {
  const fixture = JSON.parse(await readFile(fixturePath, "utf8")) as DemoFixture;
  if (suffix === "/health") {
    return {
      schema: "beacon.console.health.v1",
      schemaMajor: 1,
      consoleSchema: "beacon.console.v1",
      apiVersion: "1.0",
      status: "ready",
      authority: "beacon",
      source: "synthetic",
      readOnly: true,
    };
  }
  if (suffix === "/workspaces") {
    return fixture.workspaces;
  }
  if (suffix === "/provider-backends") {
    return fixture.providerBackends;
  }
  const workspaceId = decodeURIComponent(suffix.slice("/workspaces/".length));
  const view = fixture.workspaceViews[workspaceId];
  if (view === undefined) {
    throw new ProjectionError(404, "workspace_not_found", "Workspace projection not found.");
  }
  return {
    ...pageFixture(view, searchParams),
    providerBackends: asRecord(fixture.providerBackends).items ?? [],
  };
};

const pageFixture = (
  view: Record<string, unknown>,
  searchParams: URLSearchParams,
): object => {
  const timeline = asRecord(view.timeline);
  const events = Array.isArray(timeline.events) ? timeline.events : [];
  const cursor = parseCursor(searchParams.get("cursor"));
  const limit = parseLimit(searchParams.get("limit"));
  const outOfRange = cursor > events.length;
  const start = outOfRange ? 0 : cursor;
  const selected = events.slice(start, start + limit);
  const next = selected.length > 0 ? start + selected.length : start;
  return {
    ...view,
    timeline: {
      ...timeline,
      events: selected,
      page: {
        cursor: searchParams.get("cursor"),
        nextCursor: `ord:${next}`,
        limit,
        returned: selected.length,
        total: events.length,
        hasMore: start + selected.length < events.length,
        truncated: start + selected.length < events.length,
        cursorOutOfRange: outOfRange,
        rebuildRequired: outOfRange,
      },
    },
  };
};

const asRecord = (value: unknown): Record<string, unknown> => {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
};

const parseCursor = (value: string | null): number => {
  if (value === null || value === "") {
    return 0;
  }
  const match = /^ord:(\d+)$/u.exec(value);
  if (match === null) {
    throw new ProjectionError(400, "invalid_cursor", "Cursor must use ord:<number>.");
  }
  return Number(match[1]);
};

const parseLimit = (value: string | null): number => {
  if (value === null || value === "") {
    return 50;
  }
  if (!/^\d+$/u.test(value)) {
    throw new ProjectionError(400, "invalid_limit", "Limit must be an integer.");
  }
  const limit = Number(value);
  if (limit < 1 || limit > 200) {
    throw new ProjectionError(400, "invalid_limit", "Limit must be between 1 and 200.");
  }
  return limit;
};

class ProjectionError extends Error {
  public constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ProjectionError";
  }
}
