import type { FastifyReply, FastifyRequest, RouteHandlerMethod } from "fastify";

import {
  CONSOLE_API_VERSION,
  CONSOLE_HEALTH_SCHEMA,
  CONSOLE_SCHEMA,
  CONSOLE_SCHEMA_MAJOR,
  CONSOLE_TIMELINE_MAX_LIMIT,
  type ConsoleProjectionAdapter,
} from "../../../application/dto/console-api-contract.js";
import {
  LocalPlatformApiBridgeError,
  LocalPlatformApiNotConnectedError,
} from "../../../application/services/local-platform-api-service.js";
import type { HttpRouteDefinition } from "../server.js";

export const createConsoleProjectionRoutes = (
  adapter: ConsoleProjectionAdapter,
): HttpRouteDefinition[] => [
  {
    method: "GET",
    path: "/api/console/v1/health",
    handler: consoleHandler(async () => ({
      schema: CONSOLE_HEALTH_SCHEMA,
      schemaMajor: CONSOLE_SCHEMA_MAJOR,
      consoleSchema: CONSOLE_SCHEMA,
      apiVersion: CONSOLE_API_VERSION,
      status: "ready",
      authority: "beacon",
      source: "gateway",
      readOnly: true,
    })),
  },
  {
    method: "GET",
    path: "/api/console/v1/workspaces",
    handler: consoleHandler(async () => adapter.listWorkspaces()),
  },
  {
    method: "GET",
    path: "/api/console/v1/provider-backends",
    handler: consoleHandler(async () => adapter.listProviderBackends()),
  },
  {
    method: "GET",
    path: "/api/console/v1/workspaces/:workspaceId",
    handler: consoleHandler(async (request) => {
      const params = objectRecord(request.params);
      const query = objectRecord(request.query);
      const workspaceId = requiredText(params.workspaceId, "workspaceId");
      const cursor = optionalText(query.cursor, "cursor");
      const communicationCursor = optionalText(query.communicationCursor, "communicationCursor");
      const limit = optionalLimit(query.limit);
      return adapter.getWorkspaceView({
        workspaceId,
        ...(cursor === undefined ? {} : { cursor }),
        ...(communicationCursor === undefined ? {} : { communicationCursor }),
        ...(limit === undefined ? {} : { limit }),
      });
    }),
  },
];

const consoleHandler = (
  callback: (request: FastifyRequest) => Promise<object>,
): RouteHandlerMethod => {
  return async (request, reply) => {
    setReadOnlyHeaders(request, reply);
    try {
      return reply.code(200).send(await callback(request));
    } catch (error) {
      return sendConsoleError(reply, error);
    }
  };
};

const DESKTOP_CONSOLE_ORIGINS = new Set([
  "http://127.0.0.1:1420",
  "http://localhost:1420",
  "http://tauri.localhost",
  "https://tauri.localhost",
  "tauri://localhost",
]);

const setReadOnlyHeaders = (
  request: FastifyRequest,
  reply: FastifyReply,
): void => {
  reply.header("cache-control", "no-store");
  reply.header("x-content-type-options", "nosniff");
  reply.header("x-beacon-console-mode", "local-read-only");
  const origin = request.headers.origin;
  if (origin !== undefined && DESKTOP_CONSOLE_ORIGINS.has(origin)) {
    reply.header("access-control-allow-origin", origin);
    reply.header("vary", "origin");
  }
};

const sendConsoleError = (reply: FastifyReply, error: unknown): FastifyReply => {
  if (error instanceof ConsoleRequestError) {
    return reply.code(400).send(errorPayload("invalid_request", error.message));
  }
  if (error instanceof LocalPlatformApiNotConnectedError) {
    return reply.code(503).send(errorPayload("bridge_disconnected", error.message));
  }
  if (error instanceof LocalPlatformApiBridgeError) {
    return reply
      .code(error.statusCode)
      .send(errorPayload(error.errorType, error.message));
  }
  return reply
    .code(500)
    .send(errorPayload("console_projection_failed", "Console projection failed."));
};

const errorPayload = (code: string, message: string): object => ({
  schema: "beacon.console.error.v1",
  readOnly: true,
  error: { code, message },
});

class ConsoleRequestError extends Error {
  public constructor(message: string) {
    super(message);
    this.name = "ConsoleRequestError";
  }
}

const objectRecord = (value: unknown): Record<string, unknown> => {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
};

const requiredText = (value: unknown, fieldName: string): string => {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new ConsoleRequestError(`${fieldName} must be a non-empty string.`);
  }
  return value.trim();
};

const optionalText = (
  value: unknown,
  fieldName: string,
): string | undefined => {
  if (value === undefined) {
    return undefined;
  }
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new ConsoleRequestError(`${fieldName} must be a non-empty string.`);
  }
  return value.trim();
};

const optionalLimit = (value: unknown): number | undefined => {
  if (value === undefined) {
    return undefined;
  }
  if (typeof value !== "string" || !/^\d+$/u.test(value)) {
    throw new ConsoleRequestError("limit must be an integer.");
  }
  const parsed = Number(value);
  if (parsed < 1 || parsed > CONSOLE_TIMELINE_MAX_LIMIT) {
    throw new ConsoleRequestError(
      `limit must be between 1 and ${CONSOLE_TIMELINE_MAX_LIMIT}.`,
    );
  }
  return parsed;
};
