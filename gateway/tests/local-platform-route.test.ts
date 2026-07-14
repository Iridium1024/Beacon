import assert from "node:assert/strict";
import test from "node:test";

import type {
  LocalPlatformApiAdapter,
  LocalPlatformApiCallContext,
} from "../src/application/dto/local-platform-api-contract.js";
import type {
  LocalConversationMessageDto,
  LocalConversationSessionDto,
} from "../src/application/dto/local-platform-operation-response.js";
import { ContractOnlyLocalPlatformApiAdapter } from "../src/application/services/local-platform-api-service.js";
import { createLocalPlatformApiRoutes } from "../src/infrastructure/http/routes/local-platform-route.js";
import { createHttpServer } from "../src/infrastructure/http/server.js";

test("local platform routes expose resource API through injected adapter", async () => {
  const received: Record<string, unknown> = {};
  const server = createHttpServer("127.0.0.1", 0);
  for (const route of createLocalPlatformApiRoutes(fakeAdapter(received))) {
    await server.registerRoute(route);
  }

  try {
    const createWorkspace = await injectJson(server, {
      method: "POST",
      url: "/api/v1/workspaces",
      payload: {
        workspaceId: "workspace-1",
        displayName: "Workspace",
        rootPath: "X:/fixture/workspace",
      },
    });
    const listWorkspaces = await injectJson(server, {
      method: "GET",
      url: "/api/v1/workspaces",
    });
    const openWorkspace = await injectJson(server, {
      method: "GET",
      url: "/api/v1/workspaces/workspace-1",
    });
    const context = await injectJson(server, {
      method: "GET",
      url: "/api/v1/workspaces/workspace-1/context",
    });
    const createdAgent = await injectJson(server, {
      method: "POST",
      url: "/api/v1/workspaces/workspace-1/agents",
      payload: {
        agentId: "agent-reviewer-1",
        name: "Reviewer",
        description: "Reviews local plans.",
        defaultModel: "fake-chat-model",
        capabilities: [
          {
            name: "single-turn-status",
            description: "Handles local requests.",
          },
        ],
        toolPermissions: ["workspace.read"],
        runtimeConfig: {
          profile: {
            profileName: "reviewer",
            roleName: "reviewer",
          },
        },
      },
    });
    const runtimePermissions = await injectJson(server, {
      method: "GET",
      url: "/api/v1/workspaces/workspace-1/runtime-permissions",
    });
    const runtimePermission = await injectJson(server, {
      method: "GET",
      url: "/api/v1/workspaces/workspace-1/agents/agent-1/runtime-permissions",
    });
    const createdConversation = await injectJson(server, {
      method: "POST",
      url: "/api/v1/workspaces/workspace-1/conversations",
      payload: {
        conversationId: "conversation-1",
        agentId: "agent-1",
        title: "Reviewer thread",
        metadata: {
          profileName: "reviewer",
        },
      },
    });
    const conversations = await injectJson(server, {
      method: "GET",
      url: "/api/v1/workspaces/workspace-1/conversations",
    });
    const openedConversation = await injectJson(server, {
      method: "GET",
      url: "/api/v1/workspaces/workspace-1/conversations/conversation-1",
    });
    const appendedMessage = await injectJson(server, {
      method: "POST",
      url: "/api/v1/workspaces/workspace-1/conversations/conversation-1/messages",
      payload: {
        messageId: "message-1",
        role: "user",
        content: "Keep this in history.",
        runSessionId: "session-1",
      },
    });
    const conversationMessages = await injectJson(server, {
      method: "GET",
      url: "/api/v1/workspaces/workspace-1/conversations/conversation-1/messages?limit=10&offset=0",
    });
    const invocation = await injectJson(server, {
      method: "POST",
      url: "/api/v1/workspaces/workspace-1/invocations",
      payload: {
        agentId: "agent-1",
        instruction: "Capture current context.",
        sessionId: "session-1",
        conversationId: "conversation-1",
      },
    });
    const records = await injectJson(server, {
      method: "GET",
      url: "/api/v1/workspaces/workspace-1/invocations",
    });
    const files = await injectJson(server, {
      method: "GET",
      url: "/api/v1/workspaces/workspace-1/file-operations",
    });
    const timeline = await injectJson(server, {
      method: "GET",
      url: "/api/v1/workspaces/workspace-1/sessions/session-1/timeline",
    });

    assert.equal(createWorkspace.statusCode, 201);
    assert.equal(createWorkspace.body.ok, true);
    assert.equal(createWorkspace.body.payload.workspace.workspace.workspaceId, "workspace-1");
    assert.equal(createWorkspace.body.metadata.platformRuntimeWired, "contract_only");
    assert.equal(createWorkspace.body.metadata.localApiPolicy, "local_only");
    assert.equal(createWorkspace.body.metadata.actorKind, "local_process");
    assert.ok(createWorkspace.body.metadata.permissionScopes.includes("agent.invoke"));
    assert.equal(listWorkspaces.body.payload.workspaces[0].workspaceId, "workspace-1");
    assert.equal(openWorkspace.body.payload.workspace.workspaceId, "workspace-1");
    assert.equal(context.body.payload.context.workspaceId, "workspace-1");
    assert.equal(createdAgent.statusCode, 201);
    assert.equal(createdAgent.body.payload.agent.agentId, "agent-reviewer-1");
    assert.equal(runtimePermissions.body.payload.runtimePermissions[0].agentId, "agent-1");
    assert.equal(runtimePermission.body.payload.runtimePermission.runtimeKind, "provider_backed_model");
    assert.equal(
      runtimePermission.body.payload.runtimePermission.boundary.real_runtime_connected,
      false,
    );
    assert.equal(createdConversation.statusCode, 201);
    assert.equal(createdConversation.body.payload.conversation.conversationId, "conversation-1");
    assert.equal(conversations.body.payload.conversations[0].conversationId, "conversation-1");
    assert.equal(openedConversation.body.payload.conversation.conversationId, "conversation-1");
    assert.equal(appendedMessage.statusCode, 201);
    assert.equal(appendedMessage.body.payload.message.messageId, "message-1");
    assert.equal(conversationMessages.body.payload.messages[0].messageId, "message-1");
    assert.equal(invocation.body.payload.workspaceId, "workspace-1");
    assert.equal(invocation.body.payload.conversation.conversationId, "conversation-1");
    assert.equal(records.body.payload.invocations[0].invocationId, "invoke-1");
    assert.equal(files.body.payload.fileOperations.length, 0);
    assert.equal(timeline.body.payload.session.sessionId, "session-1");
    assert.deepEqual(received.invocation, {
      workspaceId: "workspace-1",
      agentId: "agent-1",
      instruction: "Capture current context.",
      sessionId: "session-1",
      conversationId: "conversation-1",
    });
    assert.deepEqual(received.conversation, {
      conversationId: "conversation-1",
      agentId: "agent-1",
      title: "Reviewer thread",
      metadata: {
        profileName: "reviewer",
      },
    });
    assert.deepEqual(received.conversationMessage, {
      messageId: "message-1",
      role: "user",
      content: "Keep this in history.",
      runSessionId: "session-1",
    });
    assert.deepEqual(received.conversationMessagesRequest, {
      limit: 10,
      offset: 0,
    });
    assert.deepEqual(received.agent, {
      agentId: "agent-reviewer-1",
      name: "Reviewer",
      description: "Reviews local plans.",
      defaultModel: "fake-chat-model",
      capabilities: [
        {
          name: "single-turn-status",
          description: "Handles local requests.",
        },
      ],
      toolPermissions: ["workspace.read"],
      runtimeConfig: {
        profile: {
          profileName: "reviewer",
          roleName: "reviewer",
        },
      },
    });
    const invocationContext = received.invocationContext as LocalPlatformApiCallContext;
    assert.equal(invocationContext.actor.actorKind, "local_process");
    assert.equal(invocationContext.actor.actorId, "local-process");
    assert.equal(invocationContext.accessPolicy.policyMode, "local_only");
    assert.equal(invocationContext.accessPolicy.accountSystemEnabled, false);
    assert.ok(invocationContext.accessPolicy.permissionScopes.includes("agent.invoke"));
    assert.ok(
      invocationContext.accessPolicy.permissionScopes.includes(
        "runtime_permission.read",
      ),
    );
  } finally {
    await server.raw().close();
  }
});

test("connection and binding routes are contract boundaries", async () => {
  const received: Record<string, unknown> = {};
  const server = createHttpServer("127.0.0.1", 0);
  for (const route of createLocalPlatformApiRoutes(fakeAdapter(received))) {
    await server.registerRoute(route);
  }

  try {
    const connections = await injectJson(server, {
      method: "GET",
      url: "/api/v1/connections",
    });
    const createdConnection = await injectJson(server, {
      method: "POST",
      url: "/api/v1/connections",
      payload: {
        connectionId: "connection-1",
        providerKind: "remote_conversation",
        accountAlias: "account-a",
        authMode: "external_connector",
      },
    });
    const bindings = await injectJson(server, {
      method: "GET",
      url: "/api/v1/agent-bindings",
    });
    const createdBinding = await injectJson(server, {
      method: "POST",
      url: "/api/v1/agent-bindings",
      payload: {
        bindingId: "binding-1",
        agentId: "agent-1",
        connectionId: "connection-1",
        runtimeKind: "remote_conversation_instance",
        remoteInstanceId: "instance-1",
        capabilities: ["single-turn-status"],
      },
    });

    assert.equal(connections.body.payload.connections.length, 0);
    assert.equal(createdConnection.statusCode, 201);
    assert.equal(createdConnection.body.payload.connection.status, "not_connected");
    assert.equal(bindings.body.payload.bindings.length, 0);
    assert.equal(createdBinding.statusCode, 201);
    assert.equal(createdBinding.body.payload.binding.agentId, "agent-1");
    assert.equal(createdBinding.body.payload.binding.connectionId, "connection-1");
    assert.deepEqual(received.connection, {
      connectionId: "connection-1",
      providerKind: "remote_conversation",
      accountAlias: "account-a",
      authMode: "external_connector",
    });
  } finally {
    await server.raw().close();
  }
});

test("local platform routes return stable request and not-connected errors", async () => {
  const invalidServer = createHttpServer("127.0.0.1", 0);
  for (const route of createLocalPlatformApiRoutes(fakeAdapter({}))) {
    await invalidServer.registerRoute(route);
  }
  const contractOnlyServer = createHttpServer("127.0.0.1", 0);
  for (const route of createLocalPlatformApiRoutes(new ContractOnlyLocalPlatformApiAdapter())) {
    await contractOnlyServer.registerRoute(route);
  }

  try {
    const invalid = await injectJson(invalidServer, {
      method: "POST",
      url: "/api/v1/workspaces",
      payload: {},
    });
    const notConnected = await injectJson(contractOnlyServer, {
      method: "POST",
      url: "/api/v1/workspaces",
      payload: {
        workspaceId: "workspace-1",
        displayName: "Workspace",
      },
    });

    assert.equal(invalid.statusCode, 400);
    assert.equal(invalid.body.ok, false);
    assert.equal(invalid.body.payload.error.type, "invalid_request");
    assert.equal(notConnected.statusCode, 501);
    assert.equal(notConnected.body.ok, false);
    assert.equal(notConnected.body.metadata.routeStatus, "not_connected");
    assert.equal(notConnected.body.payload.error.type, "not_connected");
    assert.doesNotMatch(JSON.stringify(notConnected.body), /Traceback|stack/i);
  } finally {
    await invalidServer.raw().close();
    await contractOnlyServer.raw().close();
  }
});

const injectJson = async (
  server: ReturnType<typeof createHttpServer>,
  options: {
    method: "GET" | "POST";
    url: string;
    payload?: object;
  },
): Promise<{ statusCode: number; body: any }> => {
  const response = await server.raw().inject({
    method: options.method,
    url: options.url,
    headers: {
      "content-type": "application/json",
      "x-session-id": "session-1",
      "x-correlation-id": "correlation-1",
    },
    ...(options.payload ? { payload: JSON.stringify(options.payload) } : {}),
  });
  return {
    statusCode: response.statusCode,
    body: JSON.parse(response.payload),
  };
};

const fakeAdapter = (received: Record<string, unknown>): LocalPlatformApiAdapter => {
  return {
    async createWorkspace(request, context) {
      received.workspace = request;
      received.workspaceContext = context;
      return {
        created: true,
        workspaceSourceEventSequence: 1,
        workspace: workspaceOverview(),
        baseline: {
          workspaceId: "workspace-1",
          contextCreated: true,
          agentCreated: true,
          context: contextState(),
          agents: [agentState()],
        },
      };
    },
    async listWorkspaces() {
      return { workspaces: [workspaceState()] };
    },
    async openWorkspace(_workspaceId) {
      return workspaceOverview();
    },
    async archiveWorkspace(_workspaceId) {
      return {
        workspace: workspaceOverview(),
        archived: true,
        workspaceSourceEventSequence: 2,
      };
    },
    async getContext(_workspaceId) {
      return { context: contextState() };
    },
    async appendContextUpdate(_workspaceId, request) {
      received.contextUpdate = request;
      return {
        contextUpdate: {
          updateId: "update-1",
          workspaceId: "workspace-1",
          updateKind: "note",
          summary: request.summary,
          createdAt: "2026-06-05T00:00:00+00:00",
          sourceAgentId: null,
          payload: {},
          materializedStatePatch: {},
          metadata: {},
        },
        context: contextState(),
        sourceEventSequence: 3,
      };
    },
    async listAgents(_workspaceId) {
      return { agents: [agentState()] };
    },
    async listAgentRuntimePermissions(_workspaceId) {
      return { runtimePermissions: [runtimePermissionState()] };
    },
    async getAgentRuntimePermissions(_workspaceId, agentId) {
      return {
        runtimePermission: runtimePermissionState({
          agentId,
        }),
      };
    },
    async createAgent(_workspaceId, request) {
      received.agent = request;
      return {
        agent: agentState({
          agentId: request.agentId ?? "agent-1",
          name: request.name,
          description: request.description,
          defaultModel: request.defaultModel ?? "deterministic-placeholder",
          runtimeConfig: request.runtimeConfig ?? {},
        }),
        created: true,
        agentSourceEventSequence: 7,
      };
    },
    async createConversation(_workspaceId, request) {
      received.conversation = request;
      return {
        conversation: conversationState({
          conversationId: request.conversationId ?? "conversation-1",
          agentId: request.agentId ?? null,
          title: request.title,
          metadata: request.metadata ?? {},
        }),
        created: true,
        conversationSourceEventSequence: 8,
      };
    },
    async listConversations(_workspaceId) {
      return { conversations: [conversationState()] };
    },
    async getConversation(_workspaceId, conversationId) {
      return {
        conversation: conversationState({ conversationId }),
      };
    },
    async archiveConversation(_workspaceId, conversationId) {
      return {
        conversation: conversationState({
          conversationId,
          status: "archived",
          archivedAt: "2026-06-05T00:05:00+00:00",
        }),
        archived: true,
        conversationSourceEventSequence: 9,
      };
    },
    async appendConversationMessage(_workspaceId, _conversationId, request) {
      received.conversationMessage = request;
      return {
        message: conversationMessage({
          messageId: request.messageId ?? "message-1",
          role: request.role,
          content: request.content,
          runSessionId: request.runSessionId ?? null,
        }),
        messageSourceEventSequence: 10,
      };
    },
    async listConversationMessages(_workspaceId, _conversationId, request) {
      received.conversationMessagesRequest = request;
      return {
        conversation: conversationState(),
        messages: [conversationMessage()],
      };
    },
    async invokeAgent(_workspaceId, request, context) {
      received.invocation = request;
      received.invocationContext = context;
      return {
        workspaceId: "workspace-1",
        agentId: "agent-1",
        contextId: "context-1",
        runtimeLoaded: true,
        modelInvoked: false,
        toolInvoked: false,
        deterministicPlaceholder: true,
        sourceEventSequence: 4,
        agentInvocationEventSequence: 6,
        materializedState: {},
        userContextUpdate: {
          updateId: "update-user-1",
          workspaceId: "workspace-1",
          updateKind: "user_message",
          summary: "Captured user instruction",
          createdAt: "2026-06-05T00:00:00+00:00",
          sourceAgentId: null,
          payload: {},
          materializedStatePatch: {},
          metadata: {},
        },
        invocationResult: {
          invocationId: "invoke-1",
          workspaceId: "workspace-1",
          agentId: "agent-1",
          status: "succeeded",
          summary: "Succeeded",
          completedAt: "2026-06-05T00:00:00+00:00",
          outputText: "ok",
          errorMessage: null,
          outputPayload: {},
          contextUpdateIds: ["update-user-1"],
          metadata: {},
        },
        fileOperations: [],
        conversation: conversationState(),
        conversationMessages: [],
      };
    },
    async listInvocationRecords(_workspaceId) {
      return {
        invocations: [
          {
            invocationId: "invoke-1",
            workspaceId: "workspace-1",
            agentId: "agent-1",
            taskId: null,
            sourceEventSequence: 6,
            status: "succeeded",
            instruction: "Capture current context.",
            requestedCapability: null,
            idempotencyKey: null,
            correlationId: null,
            requestState: {},
            resultState: {},
            contextUpdateIds: ["update-user-1"],
            fileReferences: [],
            metadata: {},
            requestedAt: "2026-06-05T00:00:00+00:00",
            completedAt: "2026-06-05T00:00:00+00:00",
            createdAt: "2026-06-05T00:00:00+00:00",
            updatedAt: "2026-06-05T00:00:00+00:00",
          },
        ],
      };
    },
    async listFileOperationRecords(_workspaceId) {
      return { fileOperations: [] };
    },
    async getRunSessionTimeline(_workspaceId, sessionId) {
      return {
        session: {
          workspaceId: "workspace-1",
          sessionId,
          status: "observed",
          eventCount: 1,
          firstSequence: 4,
          lastSequence: 4,
          firstOccurredAt: "2026-06-05T00:00:00+00:00",
          lastOccurredAt: "2026-06-05T00:00:00+00:00",
          lifecycle: {
            hasExplicitLifecycleEvents: false,
            statusSource: "observed_events",
            recoveryState: "observed_without_lifecycle",
            startedSequence: null,
            terminalSequence: null,
            startedAt: null,
            endedAt: null,
            invocationEventCount: 1,
            contextUpdateEventCount: 0,
            fileOperationEventCount: 0,
          },
        },
        events: [],
      };
    },
    async listProviderConnections() {
      return { connections: [] };
    },
    async createProviderConnection(request) {
      received.connection = request;
      return {
        created: true,
        connection: {
          connectionId: request.connectionId ?? "connection-1",
          providerKind: request.providerKind,
          accountAlias: request.accountAlias ?? null,
          displayName: request.displayName ?? null,
          authMode: request.authMode,
          status: "not_connected",
          metadata: request.metadata ?? {},
        },
      };
    },
    async listAgentRuntimeBindings() {
      return { bindings: [] };
    },
    async createAgentRuntimeBinding(request) {
      received.binding = request;
      return {
        created: true,
        binding: {
          bindingId: request.bindingId ?? "binding-1",
          agentId: request.agentId,
          connectionId: request.connectionId ?? null,
          runtimeKind: request.runtimeKind,
          remoteInstanceId: request.remoteInstanceId ?? null,
          capabilities: request.capabilities ?? [],
          status: "not_connected",
          metadata: request.metadata ?? {},
        },
      };
    },
  };
};

const workspaceOverview = () => ({
  workspace: workspaceState(),
  context: contextState(),
  agents: [agentState()],
  tasks: [],
  issues: [],
});

const workspaceState = () => ({
  workspaceId: "workspace-1",
  sourceEventSequence: 1,
  displayName: "Workspace",
  rootPath: "X:/fixture/workspace",
  status: "active",
  createdAt: "2026-06-05T00:00:00+00:00",
  updatedAt: "2026-06-05T00:00:00+00:00",
  workspaceState: {},
  bindingState: {},
  metadata: {},
});

const contextState = () => ({
  workspaceId: "workspace-1",
  contextId: "context-1",
  sourceEventSequence: 1,
  updateCount: 0,
  materializedState: {},
  createdAt: "2026-06-05T00:00:00+00:00",
  updatedAt: "2026-06-05T00:00:00+00:00",
  metadata: {},
});

const agentState = (
  overrides: Partial<ReturnType<typeof agentStateBase>> = {},
) => ({
  ...agentStateBase(),
  ...overrides,
});

const agentStateBase = () => ({
  agentId: "agent-1",
  workspaceId: "workspace-1",
  sourceEventSequence: 2,
  name: "Agent",
  description: "Handles local requests.",
  status: "active",
  defaultModel: "deterministic-placeholder",
  capabilities: [
    {
      name: "single-turn-status",
      description: "Captures local requests.",
      metadata: {},
    },
  ],
  toolPermissions: ["workspace.read"],
  runtimeConfig: {},
  createdAt: "2026-06-05T00:00:00+00:00",
  updatedAt: "2026-06-05T00:00:00+00:00",
  registrationState: {},
  metadata: {},
});

const runtimePermissionState = (
  overrides: Partial<ReturnType<typeof runtimePermissionStateBase>> = {},
) => ({
  ...runtimePermissionStateBase(),
  ...overrides,
});

const runtimePermissionStateBase = () => ({
  workspaceId: "workspace-1",
  agentId: "agent-1",
  profileName: "Agent",
  roleName: "Agent",
  runtimeKind: "provider_backed_model",
  providerBackedModel: true,
  runtimeConnected: false as const,
  readModelOnly: true as const,
  configuredProfile: {
    delegated_context_delivery: "none",
  },
  capabilities: {
    denied: ["real_runtime_connection", "websocket_transport"],
    flags: {
      websocket_transport_allowed: false,
    },
  },
  grant: {
    revoked: false,
    real_runtime_connected: false,
  },
  deliveryPlan: {
    materialized_text_included: false,
    file_bodies_included: false,
    real_runtime_connected: false,
  },
  boundary: {
    real_runtime_connected: false,
    invocation_created: false,
  },
});

const conversationState = (
  overrides: Partial<LocalConversationSessionDto> = {},
): LocalConversationSessionDto => ({
  ...conversationStateBase(),
  ...overrides,
});

const conversationStateBase = (): LocalConversationSessionDto => ({
  conversationId: "conversation-1",
  workspaceId: "workspace-1",
  agentId: "agent-1",
  sourceEventSequence: 8,
  title: "Reviewer thread",
  status: "active" as const,
  createdAt: "2026-06-05T00:00:00+00:00",
  updatedAt: "2026-06-05T00:00:00+00:00",
  archivedAt: null,
  metadata: {},
});

const conversationMessage = (
  overrides: Partial<LocalConversationMessageDto> = {},
): LocalConversationMessageDto => ({
  ...conversationMessageBase(),
  ...overrides,
});

const conversationMessageBase = (): LocalConversationMessageDto => ({
  messageId: "message-1",
  conversationId: "conversation-1",
  workspaceId: "workspace-1",
  sourceEventSequence: 10,
  sequence: 1,
  role: "user" as const,
  content: "Keep this in history.",
  agentId: "agent-1",
  invocationId: null,
  contextUpdateId: null,
  runSessionId: "session-1",
  createdAt: "2026-06-05T00:00:00+00:00",
  metadata: {},
});
