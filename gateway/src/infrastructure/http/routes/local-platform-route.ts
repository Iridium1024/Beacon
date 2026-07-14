import type { FastifyRequest, RouteHandlerMethod } from "fastify";

import type {
  AppendLocalConversationMessageRequest,
  AppendLocalContextUpdateRequest,
  CreateAgentRuntimeBindingRequest,
  CreateLocalConversationRequest,
  CreateLocalAgentRequest,
  CreateLocalWorkspaceRequest,
  CreateProviderConnectionRequest,
  InvokeLocalAgentRequest,
  ListLocalConversationMessagesRequest,
  LocalPlatformApiAccessPolicy,
  LocalPlatformApiCallContext,
  LocalPlatformApiAdapter,
  LocalPlatformErrorPayload,
  LocalPlatformRouteMetadata,
  LocalPlatformRouteResponse,
} from "../../../application/dto/local-platform-api-contract.js";
import {
  LocalPlatformApiBridgeError,
  LocalPlatformApiNotConnectedError,
} from "../../../application/services/local-platform-api-service.js";
import { buildApiSession } from "../context.js";
import type { HttpRouteDefinition } from "../server.js";

class LocalPlatformApiRequestError extends Error {
  public constructor(message: string) {
    super(message);
    this.name = "LocalPlatformApiRequestError";
  }
}

type RoutePayload = Record<string, unknown>;

export interface LocalPlatformApiRouteOptions {
  platformRuntimeWired?: LocalPlatformRouteMetadata["platformRuntimeWired"];
  accessPolicy?: LocalPlatformApiAccessPolicy;
}

export const createLocalPlatformApiRoutes = (
  adapter: LocalPlatformApiAdapter,
  options: LocalPlatformApiRouteOptions = {},
): HttpRouteDefinition[] => [
  {
    method: "POST",
    path: "/api/v1/workspaces",
    handler: localPlatformHandler(
      async (request, context) => adapter.createWorkspace(
        createWorkspaceRequest(request.body),
        context,
      ),
      options,
      201,
    ),
  },
  {
    method: "GET",
    path: "/api/v1/workspaces",
    handler: localPlatformHandler(
      async (_request, context) => adapter.listWorkspaces(context),
      options,
    ),
  },
  {
    method: "GET",
    path: "/api/v1/workspaces/:workspaceId",
    handler: localPlatformHandler(
      async (request, context) => adapter.openWorkspace(
        routeParam(request.params, "workspaceId"),
        context,
      ),
      options,
    ),
  },
  {
    method: "POST",
    path: "/api/v1/workspaces/:workspaceId/archive",
    handler: localPlatformHandler(
      async (request, context) => adapter.archiveWorkspace(
        routeParam(request.params, "workspaceId"),
        context,
      ),
      options,
    ),
  },
  {
    method: "GET",
    path: "/api/v1/workspaces/:workspaceId/context",
    handler: localPlatformHandler(
      async (request, context) => adapter.getContext(
        routeParam(request.params, "workspaceId"),
        context,
      ),
      options,
    ),
  },
  {
    method: "POST",
    path: "/api/v1/workspaces/:workspaceId/context-updates",
    handler: localPlatformHandler(
      async (request, context) => adapter.appendContextUpdate(
        routeParam(request.params, "workspaceId"),
        appendContextUpdateRequest(request.body),
        context,
      ),
      options,
      201,
    ),
  },
  {
    method: "GET",
    path: "/api/v1/workspaces/:workspaceId/agents",
    handler: localPlatformHandler(
      async (request, context) => adapter.listAgents(
        routeParam(request.params, "workspaceId"),
        context,
      ),
      options,
    ),
  },
  {
    method: "GET",
    path: "/api/v1/workspaces/:workspaceId/runtime-permissions",
    handler: localPlatformHandler(
      async (request, context) => adapter.listAgentRuntimePermissions(
        routeParam(request.params, "workspaceId"),
        context,
      ),
      options,
    ),
  },
  {
    method: "GET",
    path: "/api/v1/workspaces/:workspaceId/agents/:agentId/runtime-permissions",
    handler: localPlatformHandler(
      async (request, context) => adapter.getAgentRuntimePermissions(
        routeParam(request.params, "workspaceId"),
        routeParam(request.params, "agentId"),
        context,
      ),
      options,
    ),
  },
  {
    method: "POST",
    path: "/api/v1/workspaces/:workspaceId/agents",
    handler: localPlatformHandler(
      async (request, context) => adapter.createAgent(
        routeParam(request.params, "workspaceId"),
        createAgentRequest(request.body),
        context,
      ),
      options,
      201,
    ),
  },
  {
    method: "POST",
    path: "/api/v1/workspaces/:workspaceId/conversations",
    handler: localPlatformHandler(
      async (request, context) => adapter.createConversation(
        routeParam(request.params, "workspaceId"),
        createConversationRequest(request.body),
        context,
      ),
      options,
      201,
    ),
  },
  {
    method: "GET",
    path: "/api/v1/workspaces/:workspaceId/conversations",
    handler: localPlatformHandler(
      async (request, context) => adapter.listConversations(
        routeParam(request.params, "workspaceId"),
        context,
      ),
      options,
    ),
  },
  {
    method: "GET",
    path: "/api/v1/workspaces/:workspaceId/conversations/:conversationId",
    handler: localPlatformHandler(
      async (request, context) => adapter.getConversation(
        routeParam(request.params, "workspaceId"),
        routeParam(request.params, "conversationId"),
        context,
      ),
      options,
    ),
  },
  {
    method: "POST",
    path: "/api/v1/workspaces/:workspaceId/conversations/:conversationId/archive",
    handler: localPlatformHandler(
      async (request, context) => adapter.archiveConversation(
        routeParam(request.params, "workspaceId"),
        routeParam(request.params, "conversationId"),
        context,
      ),
      options,
    ),
  },
  {
    method: "POST",
    path: "/api/v1/workspaces/:workspaceId/conversations/:conversationId/messages",
    handler: localPlatformHandler(
      async (request, context) => adapter.appendConversationMessage(
        routeParam(request.params, "workspaceId"),
        routeParam(request.params, "conversationId"),
        appendConversationMessageRequest(request.body),
        context,
      ),
      options,
      201,
    ),
  },
  {
    method: "GET",
    path: "/api/v1/workspaces/:workspaceId/conversations/:conversationId/messages",
    handler: localPlatformHandler(
      async (request, context) => adapter.listConversationMessages(
        routeParam(request.params, "workspaceId"),
        routeParam(request.params, "conversationId"),
        listConversationMessagesRequest(request.query),
        context,
      ),
      options,
    ),
  },
  {
    method: "POST",
    path: "/api/v1/workspaces/:workspaceId/invocations",
    handler: localPlatformHandler(
      async (request, context) => {
        const workspaceId = routeParam(request.params, "workspaceId");
        return adapter.invokeAgent(
          workspaceId,
          invokeAgentRequest(workspaceId, request.body),
          context,
        );
      },
      options,
    ),
  },
  {
    method: "GET",
    path: "/api/v1/workspaces/:workspaceId/invocations",
    handler: localPlatformHandler(
      async (request, context) => adapter.listInvocationRecords(
        routeParam(request.params, "workspaceId"),
        context,
      ),
      options,
    ),
  },
  {
    method: "GET",
    path: "/api/v1/workspaces/:workspaceId/file-operations",
    handler: localPlatformHandler(
      async (request, context) => adapter.listFileOperationRecords(
        routeParam(request.params, "workspaceId"),
        context,
      ),
      options,
    ),
  },
  {
    method: "GET",
    path: "/api/v1/workspaces/:workspaceId/sessions/:sessionId/timeline",
    handler: localPlatformHandler(
      async (request, context) => adapter.getRunSessionTimeline(
        routeParam(request.params, "workspaceId"),
        routeParam(request.params, "sessionId"),
        context,
      ),
      options,
    ),
  },
  {
    method: "GET",
    path: "/api/v1/connections",
    handler: localPlatformHandler(
      async (_request, context) => adapter.listProviderConnections(context),
      options,
    ),
  },
  {
    method: "POST",
    path: "/api/v1/connections",
    handler: localPlatformHandler(
      async (request, context) => adapter.createProviderConnection(
        createProviderConnectionRequest(request.body),
        context,
      ),
      options,
      201,
    ),
  },
  {
    method: "GET",
    path: "/api/v1/agent-bindings",
    handler: localPlatformHandler(
      async (_request, context) => adapter.listAgentRuntimeBindings(context),
      options,
    ),
  },
  {
    method: "POST",
    path: "/api/v1/agent-bindings",
    handler: localPlatformHandler(
      async (request, context) => adapter.createAgentRuntimeBinding(
        createAgentRuntimeBindingRequest(request.body),
        context,
      ),
      options,
      201,
    ),
  },
];

const localPlatformHandler = (
  callback: (request: FastifyRequest, context: LocalPlatformApiCallContext) => Promise<object>,
  options: LocalPlatformApiRouteOptions,
  successStatus = 200,
): RouteHandlerMethod => {
  return async (request, reply) => {
    const session = buildApiSession(request);
    const accessPolicy = options.accessPolicy ?? defaultLocalApiAccessPolicy();
    const callContext: LocalPlatformApiCallContext = {
      sessionId: session.sessionId,
      correlationId: session.correlationId,
      actor: accessPolicy.actor,
      accessPolicy,
      metadata: session.metadata,
    };
    const platformRuntimeWired = options.platformRuntimeWired ?? "contract_only";
    try {
      const payload = await callback(request, callContext);
      return reply.code(successStatus).send(
        routeResponse(payload, {
          routeStatus: "ok",
          platformRuntimeWired,
          sessionId: session.sessionId,
          correlationId: session.correlationId,
          localApiPolicy: accessPolicy.policyMode,
          actorKind: accessPolicy.actor.actorKind,
          permissionScopes: accessPolicy.permissionScopes,
        }),
      );
    } catch (error) {
      const routeError = errorResponse(error);
      return reply.code(routeError.statusCode).send(
        routeResponse(routeError.payload, {
          routeStatus: routeError.routeStatus,
          platformRuntimeWired,
          sessionId: session.sessionId,
          correlationId: session.correlationId,
          localApiPolicy: accessPolicy.policyMode,
          actorKind: accessPolicy.actor.actorKind,
          permissionScopes: accessPolicy.permissionScopes,
        }),
      );
    }
  };
};

const defaultLocalApiAccessPolicy = (): LocalPlatformApiAccessPolicy => ({
  policyMode: "local_only",
  localOnly: true,
  lanExposureEnabled: false,
  accountSystemEnabled: false,
  actor: {
    actorKind: "local_process",
    actorId: "local-process",
  },
  permissionScopes: [
    "workspace.read",
    "workspace.write",
    "context.read",
    "context.append",
    "agent.read",
    "agent.write",
    "agent.invoke",
    "runtime_permission.read",
    "conversation.read",
    "conversation.write",
    "records.read",
    "provider_connection.reserve",
    "agent_binding.reserve",
  ],
});

const routeResponse = <TPayload extends object>(
  payload: TPayload,
  metadata: LocalPlatformRouteMetadata,
): LocalPlatformRouteResponse<TPayload> => ({
  ok: metadata.routeStatus === "ok",
  payload,
  metadata,
});

const errorResponse = (
  error: unknown,
): {
  statusCode: number;
  routeStatus: LocalPlatformRouteMetadata["routeStatus"];
  payload: LocalPlatformErrorPayload;
} => {
  if (error instanceof LocalPlatformApiRequestError) {
    return {
      statusCode: 400,
      routeStatus: "invalid_request",
      payload: {
        error: {
          type: "invalid_request",
          message: error.message,
        },
      },
    };
  }
  if (error instanceof LocalPlatformApiNotConnectedError) {
    return {
      statusCode: 501,
      routeStatus: "not_connected",
      payload: {
        error: {
          type: "not_connected",
          message: error.message,
        },
      },
    };
  }
  if (error instanceof LocalPlatformApiBridgeError) {
    return {
      statusCode: error.statusCode,
      routeStatus: "failed",
      payload: {
        error: {
          type: error.errorType,
          message: error.message,
        },
      },
    };
  }
  return {
    statusCode: 500,
    routeStatus: "failed",
    payload: {
      error: {
        type: "internal_error",
        message: "Local platform API request failed.",
      },
    },
  };
};

const createWorkspaceRequest = (body: unknown): CreateLocalWorkspaceRequest => {
  const payload = objectBody(body);
  return {
    workspaceId: optionalText(payload, "workspaceId"),
    contextId: optionalText(payload, "contextId"),
    agentId: optionalText(payload, "agentId"),
    displayName: requiredText(payload, "displayName"),
    rootPath: optionalText(payload, "rootPath"),
    metadata: optionalObject(payload, "metadata"),
  };
};

const appendContextUpdateRequest = (
  body: unknown,
): AppendLocalContextUpdateRequest => {
  const payload = objectBody(body);
  return {
    updateKind: optionalText(payload, "updateKind") as AppendLocalContextUpdateRequest["updateKind"],
    summary: requiredText(payload, "summary"),
    updateId: optionalText(payload, "updateId"),
    sourceAgentId: optionalText(payload, "sourceAgentId"),
    payload: optionalObject(payload, "payload"),
    materializedStatePatch: optionalObject(payload, "materializedStatePatch"),
    metadata: optionalObject(payload, "metadata"),
    sessionId: optionalText(payload, "sessionId"),
  };
};

const createAgentRequest = (body: unknown): CreateLocalAgentRequest => {
  const payload = objectBody(body);
  const request: CreateLocalAgentRequest = {
    name: requiredText(payload, "name"),
    description: requiredText(payload, "description"),
  };
  setOptional(request, "agentId", optionalText(payload, "agentId"));
  setOptional(request, "defaultModel", optionalText(payload, "defaultModel"));
  setOptional(request, "capabilities", optionalObjectList(payload, "capabilities"));
  setOptional(request, "toolPermissions", optionalStringList(payload, "toolPermissions"));
  setOptional(request, "runtimeConfig", optionalObject(payload, "runtimeConfig"));
  setOptional(request, "metadata", optionalObject(payload, "metadata"));
  return request;
};

const createConversationRequest = (body: unknown): CreateLocalConversationRequest => {
  const payload = objectBody(body);
  const request: CreateLocalConversationRequest = {
    title: requiredText(payload, "title"),
  };
  setOptional(request, "conversationId", optionalText(payload, "conversationId"));
  setOptional(request, "agentId", optionalText(payload, "agentId"));
  setOptional(request, "metadata", optionalObject(payload, "metadata"));
  return request;
};

const appendConversationMessageRequest = (
  body: unknown,
): AppendLocalConversationMessageRequest => {
  const payload = objectBody(body);
  const request: AppendLocalConversationMessageRequest = {
    role: requiredText(payload, "role") as AppendLocalConversationMessageRequest["role"],
    content: requiredText(payload, "content"),
  };
  setOptional(request, "messageId", optionalText(payload, "messageId"));
  setOptional(request, "agentId", optionalText(payload, "agentId"));
  setOptional(request, "invocationId", optionalText(payload, "invocationId"));
  setOptional(request, "contextUpdateId", optionalText(payload, "contextUpdateId"));
  setOptional(request, "runSessionId", optionalText(payload, "runSessionId"));
  setOptional(request, "metadata", optionalObject(payload, "metadata"));
  return request;
};

const listConversationMessagesRequest = (
  query: unknown,
): ListLocalConversationMessagesRequest => {
  const payload = queryObject(query);
  const request: ListLocalConversationMessagesRequest = {};
  setOptional(request, "limit", optionalInteger(payload, "limit"));
  setOptional(request, "offset", optionalInteger(payload, "offset"));
  return request;
};

const invokeAgentRequest = (
  workspaceId: string,
  body: unknown,
): InvokeLocalAgentRequest => {
  const payload = objectBody(body);
  return {
    ...payload,
    workspaceId,
    agentId: requiredText(payload, "agentId"),
    instruction: requiredText(payload, "instruction"),
  } as InvokeLocalAgentRequest;
};

const createProviderConnectionRequest = (
  body: unknown,
): CreateProviderConnectionRequest => {
  const payload = objectBody(body);
  const request: CreateProviderConnectionRequest = {
    providerKind: requiredText(payload, "providerKind") as CreateProviderConnectionRequest["providerKind"],
    authMode: requiredText(payload, "authMode") as CreateProviderConnectionRequest["authMode"],
  };
  setOptional(request, "connectionId", optionalText(payload, "connectionId"));
  setOptional(request, "accountAlias", optionalText(payload, "accountAlias"));
  setOptional(request, "displayName", optionalText(payload, "displayName"));
  setOptional(request, "metadata", optionalObject(payload, "metadata"));
  return request;
};

const createAgentRuntimeBindingRequest = (
  body: unknown,
): CreateAgentRuntimeBindingRequest => {
  const payload = objectBody(body);
  const request: CreateAgentRuntimeBindingRequest = {
    agentId: requiredText(payload, "agentId"),
    runtimeKind: requiredText(payload, "runtimeKind") as CreateAgentRuntimeBindingRequest["runtimeKind"],
  };
  setOptional(request, "bindingId", optionalText(payload, "bindingId"));
  setOptional(request, "connectionId", optionalText(payload, "connectionId"));
  setOptional(request, "remoteInstanceId", optionalText(payload, "remoteInstanceId"));
  setOptional(request, "capabilities", optionalStringList(payload, "capabilities"));
  setOptional(request, "metadata", optionalObject(payload, "metadata"));
  return request;
};

const routeParam = (params: unknown, fieldName: string): string => {
  if (typeof params !== "object" || params === null) {
    throw new LocalPlatformApiRequestError(`route parameter '${fieldName}' is required.`);
  }
  return requiredText(params as RoutePayload, fieldName);
};

const objectBody = (body: unknown): RoutePayload => {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    throw new LocalPlatformApiRequestError("request body must be an object.");
  }
  return body as RoutePayload;
};

const queryObject = (query: unknown): RoutePayload => {
  if (query === undefined || query === null) {
    return {};
  }
  if (typeof query !== "object" || Array.isArray(query)) {
    throw new LocalPlatformApiRequestError("request query must be an object.");
  }
  return query as RoutePayload;
};

const requiredText = (payload: RoutePayload, fieldName: string): string => {
  const value = payload[fieldName];
  if (typeof value !== "string" || value.trim() === "") {
    throw new LocalPlatformApiRequestError(`field '${fieldName}' must be a non-empty string.`);
  }
  return value.trim();
};

const optionalText = (
  payload: RoutePayload,
  fieldName: string,
): string | undefined => {
  if (!(fieldName in payload)) {
    return undefined;
  }
  return requiredText(payload, fieldName);
};

const optionalObject = (
  payload: RoutePayload,
  fieldName: string,
): Record<string, unknown> | undefined => {
  if (!(fieldName in payload)) {
    return undefined;
  }
  const value = payload[fieldName];
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new LocalPlatformApiRequestError(`field '${fieldName}' must be an object.`);
  }
  return value as Record<string, unknown>;
};

const optionalInteger = (
  payload: RoutePayload,
  fieldName: string,
): number | undefined => {
  if (!(fieldName in payload)) {
    return undefined;
  }
  const value = payload[fieldName];
  const text = typeof value === "number" ? String(value) : value;
  if (typeof text !== "string" || !/^\d+$/u.test(text)) {
    throw new LocalPlatformApiRequestError(`field '${fieldName}' must be a non-negative integer.`);
  }
  return Number.parseInt(text, 10);
};

const optionalObjectList = (
  payload: RoutePayload,
  fieldName: string,
): Record<string, unknown>[] | undefined => {
  if (!(fieldName in payload)) {
    return undefined;
  }
  const value = payload[fieldName];
  if (!Array.isArray(value) || value.some((item) => {
    return typeof item !== "object" || item === null || Array.isArray(item);
  })) {
    throw new LocalPlatformApiRequestError(`field '${fieldName}' must be a list of objects.`);
  }
  return value as Record<string, unknown>[];
};

const optionalStringList = (
  payload: RoutePayload,
  fieldName: string,
): string[] | undefined => {
  if (!(fieldName in payload)) {
    return undefined;
  }
  const value = payload[fieldName];
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || item.trim() === "")) {
    throw new LocalPlatformApiRequestError(`field '${fieldName}' must be a list of non-empty strings.`);
  }
  return value.map((item) => item.trim());
};

const setOptional = <TObject extends object, TKey extends keyof TObject>(
  target: TObject,
  key: TKey,
  value: TObject[TKey] | undefined,
): void => {
  if (value !== undefined) {
    target[key] = value;
  }
};
