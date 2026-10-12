import type {
  ConsoleGatewayHealthResponse,
  ConsoleProviderBackendListResponse,
  ConsoleTimelineEvent,
  ConsoleTimelinePage,
  ConsoleWorkspaceListResponse,
  ConsoleWorkspaceProjectionResponse,
} from "./contracts.js";

export const MAX_RESPONSE_BYTES = 1_048_576;
export const MAX_TIMELINE_EVENTS = 200;

const SENSITIVE_KEYS = new Set([
  "apikey",
  "api_key",
  "auth",
  "authorization",
  "content",
  "cookie",
  "credential",
  "credentials",
  "environment",
  "message",
  "messages",
  "password",
  "prompt",
  "secret",
  "token",
  "tooloutput",
  "tool_output",
  "transcript",
]);

export type ProtocolFailureKind =
  | "malformed"
  | "oversized"
  | "sensitive"
  | "version"
  | "permission"
  | "disconnected"
  | "timeout"
  | "redirect";

export class ConsoleProtocolError extends Error {
  public constructor(
    public readonly kind: ProtocolFailureKind,
    message: string,
  ) {
    super(message);
    this.name = "ConsoleProtocolError";
  }
}

export const parseWorkspaceList = (
  payload: unknown,
): ConsoleWorkspaceListResponse => {
  validateEnvelope(payload);
  const record = asRecord(payload);
  boundedArray(record.items, 500, "items");
  return payload as ConsoleWorkspaceListResponse;
};

export const parseGatewayHealth = (
  payload: unknown,
): ConsoleGatewayHealthResponse => {
  const record = asRecord(payload);
  if (
    record.schema !== "beacon.console.health.v1"
    || record.schemaMajor !== 1
    || record.consoleSchema !== "beacon.console.v1"
    || record.apiVersion !== "1.0"
  ) {
    throw new ConsoleProtocolError("version", "Unsupported Beacon Gateway console version.");
  }
  if (record.status !== "ready") {
    throw new ConsoleProtocolError("disconnected", "Beacon Gateway console health is not ready.");
  }
  if (
    record.authority !== "beacon"
    || !["gateway", "synthetic"].includes(String(record.source))
    || record.readOnly !== true
  ) {
    throw new ConsoleProtocolError("malformed", "Gateway health authority/read-only invariant failed.");
  }
  inspectPayload(record);
  return payload as ConsoleGatewayHealthResponse;
};

export const parseProviderBackends = (
  payload: unknown,
): ConsoleProviderBackendListResponse => {
  validateEnvelope(payload);
  const record = asRecord(payload);
  boundedArray(record.items, 50, "items");
  return payload as ConsoleProviderBackendListResponse;
};

export const parseWorkspaceProjection = (
  payload: unknown,
): ConsoleWorkspaceProjectionResponse => {
  validateEnvelope(payload);
  const record = asRecord(payload);
  boundedArray(record.agents, 500, "agents");
  boundedArray(record.sessions, 1_000, "sessions");
  boundedArray(record.providerBackends, 50, "providerBackends");
  boundedArray(record.dispatches, 500, "dispatches");
  const timeline = asRecord(record.timeline);
  const events = boundedArray(timeline.events, MAX_TIMELINE_EVENTS, "timeline.events");
  for (const value of events) {
    const event = asRecord(value);
    requiredString(event.eventId, "timeline.events[].eventId");
  }
  return payload as ConsoleWorkspaceProjectionResponse;
};

const validateEnvelope = (payload: unknown): void => {
  const record = asRecord(payload);
  if (record.schema !== "beacon.console.v1") {
    throw new ConsoleProtocolError("version", "Unsupported console schema.");
  }
  if (record.schemaMajor !== 1) {
    throw new ConsoleProtocolError("version", "Unsupported console schema major.");
  }
  if (record.authority !== "beacon" || record.readOnly !== true) {
    throw new ConsoleProtocolError(
      "malformed",
      "Projection authority/read-only invariant failed.",
    );
  }
  inspectPayload(record);
};

const inspectPayload = (root: Record<string, unknown>): void => {
  const pending: unknown[] = [root];
  let visited = 0;
  while (pending.length > 0) {
    const value = pending.pop();
    visited += 1;
    if (visited > 20_000) {
      throw new ConsoleProtocolError("oversized", "Projection object graph is too large.");
    }
    if (typeof value === "string") {
      if (value.length > 2_048) {
        throw new ConsoleProtocolError("oversized", "Projection string exceeded its bound.");
      }
      continue;
    }
    if (Array.isArray(value)) {
      if (value.length > 1_000) {
        throw new ConsoleProtocolError("oversized", "Projection array exceeded its bound.");
      }
      pending.push(...value);
      continue;
    }
    if (typeof value !== "object" || value === null) {
      continue;
    }
    for (const [key, child] of Object.entries(value)) {
      const normalized = key.toLowerCase().replaceAll("-", "_");
      if (SENSITIVE_KEYS.has(normalized) || SENSITIVE_KEYS.has(normalized.replaceAll("_", ""))) {
        throw new ConsoleProtocolError(
          "sensitive",
          `Projection contained forbidden field ${key}.`,
        );
      }
      pending.push(child);
    }
  }
};

const boundedArray = (
  value: unknown,
  maximum: number,
  field: string,
): unknown[] => {
  if (!Array.isArray(value)) {
    throw new ConsoleProtocolError("malformed", `${field} must be an array.`);
  }
  if (value.length > maximum) {
    throw new ConsoleProtocolError("oversized", `${field} exceeded its bound.`);
  }
  return value;
};

const asRecord = (value: unknown): Record<string, unknown> => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new ConsoleProtocolError("malformed", "Projection value must be an object.");
  }
  return value as Record<string, unknown>;
};

const requiredString = (value: unknown, field: string): string => {
  if (typeof value !== "string" || value.length === 0) {
    throw new ConsoleProtocolError("malformed", `${field} must be a non-empty string.`);
  }
  return value;
};

export interface TimelineAccumulator {
  events: ConsoleTimelineEvent[];
  nextCursor: string;
  rebuildToken: string;
  gapDetected: boolean;
  rebuildRequired: boolean;
  truncated: boolean;
}

export const rebuildTimeline = (page: ConsoleTimelinePage): TimelineAccumulator => {
  return mergeTimeline(
    {
      events: [],
      nextCursor: "ord:0",
      rebuildToken: page.replay.rebuildToken,
      gapDetected: false,
      rebuildRequired: false,
      truncated: false,
    },
    page,
    true,
  );
};

export const mergeTimeline = (
  current: TimelineAccumulator,
  page: ConsoleTimelinePage,
  replace = false,
): TimelineAccumulator => {
  const rebuildRequired = page.page.rebuildRequired
    || current.rebuildToken !== page.replay.rebuildToken;
  const rebuild = replace || rebuildRequired;
  const source = rebuild ? page.events : [...current.events, ...page.events];
  const byId = new Map<string, ConsoleTimelineEvent>();
  for (const event of [...source].sort(compareTimelineEvents)) {
    if (!byId.has(event.eventId)) {
      byId.set(event.eventId, event);
    }
  }
  const events = [...byId.values()].sort(compareTimelineEvents);
  let gapDetected = false;
  for (let index = 1; index < events.length; index += 1) {
    const previous = events[index - 1];
    const currentEvent = events[index];
    if (previous === undefined || currentEvent === undefined) {
      continue;
    }
    if (currentEvent.workspaceOrdinal !== previous.workspaceOrdinal + 1) {
      gapDetected = true;
      break;
    }
  }
  return {
    events,
    nextCursor: page.page.nextCursor,
    rebuildToken: page.replay.rebuildToken,
    gapDetected,
    rebuildRequired,
    truncated: page.page.truncated,
  };
};

const compareTimelineEvents = (
  left: ConsoleTimelineEvent,
  right: ConsoleTimelineEvent,
): number => {
  return left.workspaceOrdinal - right.workspaceOrdinal
    || left.eventId.localeCompare(right.eventId);
};
