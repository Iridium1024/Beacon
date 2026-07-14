import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer, type Server } from "node:http";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import type { GatewayLocalPlatformBridgeConfig } from "../src/infrastructure/config/env.js";
import type { LocalPlatformApiCallContext } from "../src/application/dto/local-platform-api-contract.js";
import { PythonLocalPlatformApiAdapter } from "../src/infrastructure/bridge/python-local-platform-api-adapter.js";
import { LocalPlatformApiBridgeError } from "../src/application/services/local-platform-api-service.js";
import { findPythonCommand } from "./support/python-command.js";

test("python local platform adapter runs workspace invocation and record flow", async () => {
  const tempRoot = mkdtempSync(join(tmpdir(), "agent-os-gateway-bridge-"));
  const adapter = new PythonLocalPlatformApiAdapter(testBridgeConfig(tempRoot));

  try {
    const created = await adapter.createWorkspace({
      workspaceId: "workspace-bridge-1",
      displayName: "Bridge Workspace",
    });
    const listed = await adapter.listWorkspaces();
    const opened = await adapter.openWorkspace("workspace-bridge-1");
    const agents = await adapter.listAgents("workspace-bridge-1");
    const runtimePermissions = await adapter.listAgentRuntimePermissions(
      "workspace-bridge-1",
    );
    const runtimePermission = await adapter.getAgentRuntimePermissions(
      "workspace-bridge-1",
      "agent-workspace-bridge-1",
    );
    const conversation = await adapter.createConversation(
      "workspace-bridge-1",
      {
        conversationId: "conversation-bridge-1",
        agentId: "agent-workspace-bridge-1",
        title: "Bridge conversation",
        metadata: {
          profileName: "bridge",
        },
      },
    );
    const invocation = await adapter.invokeAgent(
      "workspace-bridge-1",
      {
        workspaceId: "workspace-bridge-1",
        agentId: "agent-workspace-bridge-1",
        instruction: "Run bridge invocation.",
        invocationId: "invoke-bridge-1",
        conversationId: "conversation-bridge-1",
      },
      {
        ...localApiContext(),
      },
    );
    const conversationMessages = await adapter.listConversationMessages(
      "workspace-bridge-1",
      "conversation-bridge-1",
      { limit: 10, offset: 0 },
    );
    const context = await adapter.getContext("workspace-bridge-1");
    const invocations = await adapter.listInvocationRecords("workspace-bridge-1");
    const fileOperations = await adapter.listFileOperationRecords("workspace-bridge-1");
    const timeline = await adapter.getRunSessionTimeline(
      "workspace-bridge-1",
      "session-bridge-1",
    );
    const connections = await adapter.listProviderConnections();
    const connection = await adapter.createProviderConnection({
      providerKind: "remote_conversation",
      authMode: "external_connector",
      connectionId: "connection-bridge-1",
    });
    const binding = await adapter.createAgentRuntimeBinding({
      bindingId: "binding-bridge-1",
      agentId: "agent-workspace-bridge-1",
      connectionId: "connection-bridge-1",
      runtimeKind: "remote_conversation_instance",
    });

    assert.equal(created.created, true);
    assert.equal(listed.workspaces[0].workspaceId, "workspace-bridge-1");
    assert.equal(opened.workspace.workspaceId, "workspace-bridge-1");
    assert.equal(agents.agents[0].agentId, "agent-workspace-bridge-1");
    assert.equal(
      runtimePermissions.runtimePermissions[0].agentId,
      "agent-workspace-bridge-1",
    );
    assert.equal(
      runtimePermission.runtimePermission.runtimeKind,
      "provider_backed_model",
    );
    assert.equal(runtimePermission.runtimePermission.readModelOnly, true);
    assert.equal(
      runtimePermission.runtimePermission.boundary.model_provider_invoked,
      false,
    );
    assert.equal(conversation.created, true);
    assert.equal(conversation.conversation.conversationId, "conversation-bridge-1");
    assert.equal(conversation.conversation.metadata.profileName, "bridge");
    assert.equal(invocation.invocationResult.invocationId, "invoke-bridge-1");
    assert.equal(invocation.conversation?.conversationId, "conversation-bridge-1");
    assert.deepEqual(
      invocation.conversationMessages.map((message) => message.role),
      ["user", "assistant"],
    );
    assert.deepEqual(
      conversationMessages.messages.map((message) => message.invocationId),
      ["invoke-bridge-1", "invoke-bridge-1"],
    );
    assert.equal(
      conversationMessages.messages[0].contextUpdateId,
      invocation.userContextUpdate.updateId,
    );
    assert.equal(context.context?.workspaceId, "workspace-bridge-1");
    assert.equal(invocations.invocations[0].invocationId, "invoke-bridge-1");
    assert.equal(invocations.invocations[0].correlationId, "correlation-bridge-1");
    assert.equal(fileOperations.fileOperations.length, 0);
    assert.equal(timeline.session.sessionId, "session-bridge-1");
    assert.equal(timeline.session.status, "completed");
    assert.equal(timeline.session.lifecycle.hasExplicitLifecycleEvents, true);
    assert.equal(timeline.session.lifecycle.recoveryState, "closed");
    assert.equal(timeline.session.lifecycle.invocationEventCount, 2);
    assert.equal(connections.connections.length, 0);
    assert.equal(connection.connection.status, "not_connected");
    assert.equal(connection.created, false);
    assert.equal(binding.binding.status, "not_connected");
    assert.equal(binding.created, false);
  } finally {
    rmSync(tempRoot, { recursive: true, force: true });
  }
});

test("python local platform adapter can invoke through OpenAI-compatible fake provider", async () => {
  const tempRoot = mkdtempSync(join(tmpdir(), "agent-os-gateway-bridge-provider-"));
  const fakeProvider = await startFakeOpenAICompatibleProvider(
    "Gateway fake provider response.",
  );
  const credentialEnvVar = "AGENT_OS_OPENAI_COMPAT_GATEWAY_TEST_CREDENTIAL";
  const previousCredential = process.env[credentialEnvVar];
  process.env[credentialEnvVar] = randomUUID();
  const adapter = new PythonLocalPlatformApiAdapter({
    ...testBridgeConfig(tempRoot),
    agentAdapterMode: "openai-compatible-provider",
    openaiCompatibleBaseUrl: fakeProvider.url,
    openaiCompatibleModel: "fake-chat-model",
    openaiCompatibleApiKeyEnvVar: credentialEnvVar,
    openaiCompatibleTemperature: 0,
    openaiCompatibleMaxTokens: 24,
  });

  try {
    await adapter.createWorkspace({
      workspaceId: "workspace-bridge-provider-1",
      displayName: "Bridge Provider Workspace",
    });
    const agent = await adapter.createAgent(
      "workspace-bridge-provider-1",
      {
        agentId: "agent-bridge-reviewer-provider-1",
        name: "Reviewer",
        description: "Reviews provider-backed work.",
        defaultModel: "fake-chat-model",
        capabilities: [
          {
            name: "single-turn-status",
            description: "Runs one provider-backed turn.",
          },
        ],
        toolPermissions: ["workspace.read"],
        runtimeConfig: {
          profile: {
            profileName: "bridge-reviewer",
            roleName: "reviewer",
            systemPrompt: "Review provider-backed work.",
            providerName: "openai-compatible",
            modelName: "fake-chat-model",
            generationOptions: {
              temperature: 0.6,
              maxTokens: 35,
            },
            bindingId: "binding-bridge-reviewer-provider-1",
          },
        },
      },
    );
    const invocation = await adapter.invokeAgent(
      "workspace-bridge-provider-1",
      {
        workspaceId: "workspace-bridge-provider-1",
        agentId: "agent-bridge-reviewer-provider-1",
        instruction: "Run bridge provider invocation.",
        invocationId: "invoke-bridge-provider-1",
      },
      {
        ...localApiContext(),
        sessionId: "session-bridge-provider-1",
      },
    );

    assert.equal(agent.created, true);
    assert.equal(agent.agent.agentId, "agent-bridge-reviewer-provider-1");
    const agentProfile = agent.agent.runtimeConfig.profile as Record<string, unknown>;
    assert.equal(agentProfile.profileName, "bridge-reviewer");
    assert.equal(invocation.modelInvoked, true);
    assert.equal(invocation.deterministicPlaceholder, false);
    assert.equal(
      invocation.invocationResult.outputText,
      "Gateway fake provider response.",
    );
    assert.ok(invocation.invocationResult.outputPayload !== undefined);
    assert.equal(
      invocation.invocationResult.outputPayload.provider_name,
      "openai-compatible",
    );
    assert.equal(fakeProvider.requests[0].body.temperature, 0.6);
    assert.equal(fakeProvider.requests[0].body.max_tokens, 35);
    assert.equal(
      (fakeProvider.requests[0].body.messages as Array<Record<string, unknown>>)[0]
        .content,
      "Review provider-backed work.",
    );
    const runtimeProfile = invocation.invocationResult.outputPayload.runtime_profile as Record<
      string,
      unknown
    >;
    assert.equal(runtimeProfile.profile_name, "bridge-reviewer");
    assert.equal(
      fakeProvider.requests[0].authorization,
      `Bearer ${process.env[credentialEnvVar]}`,
    );
  } finally {
    if (previousCredential === undefined) {
      delete process.env[credentialEnvVar];
    } else {
      process.env[credentialEnvVar] = previousCredential;
    }
    await fakeProvider.close();
    rmSync(tempRoot, { recursive: true, force: true });
  }
});

test("python local platform adapter can invoke through provider API shape OpenAI Responses", async () => {
  const tempRoot = mkdtempSync(join(tmpdir(), "agent-os-gateway-bridge-responses-"));
  const fakeProvider = await startFakeOpenAIResponsesProvider(
    "Gateway fake Responses response.",
  );
  const credentialEnvVar = "AGENT_OS_RESPONSES_GATEWAY_TEST_CREDENTIAL";
  const previousCredential = process.env[credentialEnvVar];
  process.env[credentialEnvVar] = randomUUID();
  const adapter = new PythonLocalPlatformApiAdapter({
    ...testBridgeConfig(tempRoot),
    agentAdapterMode: "provider-api-shape",
    providerApiShape: "openai-responses",
    providerBaseUrl: fakeProvider.url,
    providerModel: "fake-responses-model",
    providerName: "openai-responses",
    providerApiKeyEnvVar: credentialEnvVar,
    providerTemperature: 0,
    providerMaxTokens: 23,
    providerInputMode: "plain_text",
    providerUserAgent: "AgentChatGatewayBridge/14.2",
  });

  try {
    await adapter.createWorkspace({
      workspaceId: "workspace-bridge-responses-1",
      displayName: "Bridge Responses Workspace",
    });
    const invocation = await adapter.invokeAgent(
      "workspace-bridge-responses-1",
      {
        workspaceId: "workspace-bridge-responses-1",
        agentId: "agent-workspace-bridge-responses-1",
        instruction: "Run bridge Responses invocation.",
        invocationId: "invoke-bridge-responses-1",
      },
      {
        ...localApiContext(),
        sessionId: "session-bridge-responses-1",
      },
    );

    assert.equal(invocation.modelInvoked, true);
    assert.equal(invocation.deterministicPlaceholder, false);
    assert.equal(
      invocation.invocationResult.outputText,
      "Gateway fake Responses response.",
    );
    assert.ok(invocation.invocationResult.outputPayload !== undefined);
    assert.equal(
      invocation.invocationResult.outputPayload.provider_name,
      "openai-responses",
    );
    assert.equal(fakeProvider.requests[0].path, "/v1/responses");
    assert.equal(
      fakeProvider.requests[0].authorization,
      `Bearer ${process.env[credentialEnvVar]}`,
    );
    assert.equal(
      fakeProvider.requests[0].userAgent,
      "AgentChatGatewayBridge/14.2",
    );
    assert.equal(fakeProvider.requests[0].body.model, "fake-responses-model");
    assert.equal(fakeProvider.requests[0].body.max_output_tokens, 23);
    assert.equal(fakeProvider.requests[0].body.temperature, 0);
    assert.equal(
      fakeProvider.requests[0].body.input,
      "Run bridge Responses invocation.",
    );
    assert.equal("max_tokens" in fakeProvider.requests[0].body, false);
    assert.equal("input_mode" in fakeProvider.requests[0].body, false);
  } finally {
    if (previousCredential === undefined) {
      delete process.env[credentialEnvVar];
    } else {
      process.env[credentialEnvVar] = previousCredential;
    }
    await fakeProvider.close();
    rmSync(tempRoot, { recursive: true, force: true });
  }
});

test("python local platform adapter can invoke through provider API shape Ollama without credential", async () => {
  const tempRoot = mkdtempSync(join(tmpdir(), "agent-os-gateway-bridge-ollama-"));
  const fakeProvider = await startFakeOllamaProvider(
    "Gateway fake Ollama response.",
  );
  const adapter = new PythonLocalPlatformApiAdapter({
    ...testBridgeConfig(tempRoot),
    agentAdapterMode: "provider-api-shape",
    providerApiShape: "ollama-chat",
    providerBaseUrl: fakeProvider.url,
    providerModel: "fake-ollama-model",
    providerName: "ollama",
    providerTemperature: 0.1,
    providerMaxTokens: 19,
  });

  try {
    await adapter.createWorkspace({
      workspaceId: "workspace-bridge-ollama-1",
      displayName: "Bridge Ollama Workspace",
    });
    const invocation = await adapter.invokeAgent(
      "workspace-bridge-ollama-1",
      {
        workspaceId: "workspace-bridge-ollama-1",
        agentId: "agent-workspace-bridge-ollama-1",
        instruction: "Run bridge Ollama invocation.",
        invocationId: "invoke-bridge-ollama-1",
      },
      {
        ...localApiContext(),
        sessionId: "session-bridge-ollama-1",
      },
    );

    assert.equal(invocation.modelInvoked, true);
    assert.equal(invocation.deterministicPlaceholder, false);
    assert.equal(
      invocation.invocationResult.outputText,
      "Gateway fake Ollama response.",
    );
    assert.equal(fakeProvider.requests[0].authorization, undefined);
    assert.equal(fakeProvider.requests[0].path, "/api/chat");
    assert.equal(fakeProvider.requests[0].body.model, "fake-ollama-model");
    const options = fakeProvider.requests[0].body.options as Record<string, unknown>;
    assert.equal(options.temperature, 0.1);
    assert.equal(options.num_predict, 19);
  } finally {
    await fakeProvider.close();
    rmSync(tempRoot, { recursive: true, force: true });
  }
});

test("python local platform adapter encapsulates provider API shape upstream errors", async () => {
  const tempRoot = mkdtempSync(join(tmpdir(), "agent-os-gateway-bridge-provider-error-"));
  const fakeProvider = await startFakeOpenAIResponsesProvider(
    "unused",
    503,
  );
  const credentialEnvVar = "AGENT_OS_RESPONSES_GATEWAY_ERROR_CREDENTIAL";
  const previousCredential = process.env[credentialEnvVar];
  process.env[credentialEnvVar] = randomUUID();
  const adapter = new PythonLocalPlatformApiAdapter({
    ...testBridgeConfig(tempRoot),
    agentAdapterMode: "provider-api-shape",
    providerApiShape: "openai-responses",
    providerBaseUrl: fakeProvider.url,
    providerModel: "fake-responses-model",
    providerName: "openai-responses",
    providerApiKeyEnvVar: credentialEnvVar,
    providerMaxTokens: 8,
  });

  try {
    await adapter.createWorkspace({
      workspaceId: "workspace-bridge-provider-error-1",
      displayName: "Bridge Provider Error Workspace",
    });
    const invocation = await adapter.invokeAgent(
      "workspace-bridge-provider-error-1",
      {
        workspaceId: "workspace-bridge-provider-error-1",
        agentId: "agent-workspace-bridge-provider-error-1",
        instruction: "Run bridge provider error invocation.",
        invocationId: "invoke-bridge-provider-error-1",
      },
      {
        ...localApiContext(),
        sessionId: "session-bridge-provider-error-1",
      },
    );

    assert.equal(invocation.modelInvoked, false);
    assert.equal(invocation.deterministicPlaceholder, false);
    assert.equal(invocation.invocationResult.status, "failed");
    assert.match(
      invocation.invocationResult.errorMessage ?? "",
      /OpenAI Responses provider request failed with status 503/,
    );
  } finally {
    if (previousCredential === undefined) {
      delete process.env[credentialEnvVar];
    } else {
      process.env[credentialEnvVar] = previousCredential;
    }
    await fakeProvider.close();
    rmSync(tempRoot, { recursive: true, force: true });
  }
});

test("python local platform adapter maps runtime errors to stable bridge errors", async () => {
  const tempRoot = mkdtempSync(join(tmpdir(), "agent-os-gateway-bridge-error-"));
  const adapter = new PythonLocalPlatformApiAdapter(testBridgeConfig(tempRoot));

  try {
    await assert.rejects(
      async () => adapter.openWorkspace("workspace-missing"),
      (error: unknown) => {
        assert.ok(error instanceof LocalPlatformApiBridgeError);
        assert.equal(error.errorType, "python_runtime_error");
        assert.doesNotMatch(error.message, /Traceback|stack/i);
        return true;
      },
    );
  } finally {
    rmSync(tempRoot, { recursive: true, force: true });
  }
});

test("python local platform adapter rejects missing or unsupported Python", async () => {
  const tempRoot = mkdtempSync(join(tmpdir(), "agent-os-gateway-python-preflight-"));
  const adapter = new PythonLocalPlatformApiAdapter({
    ...testBridgeConfig(tempRoot),
    pythonCommand: join(tempRoot, "missing-python"),
    pythonArgs: [],
    pythonFallbacks: [],
    timeoutMs: 500,
  });

  try {
    await assert.rejects(
      async () => adapter.listWorkspaces(),
      (error: unknown) => {
        assert.ok(error instanceof LocalPlatformApiBridgeError);
        assert.equal(error.errorType, "python_runtime_unavailable");
        assert.match(error.message, /Python 3\.11 or newer/);
        return true;
      },
    );
  } finally {
    rmSync(tempRoot, { recursive: true, force: true });
  }
});

test("python local platform adapter sanitizes internal runtime details", async () => {
  const tempRoot = mkdtempSync(join(tmpdir(), "agent-os-gateway-bridge-detail-"));
  const config = testBridgeConfig(tempRoot);
  const adapter = new PythonLocalPlatformApiAdapter({
    ...config,
    pythonArgs: [...config.pythonArgs, "-c", internalDetailScript()],
    skipPythonPreflight: true,
  });

  try {
    await assert.rejects(
      async () => adapter.listWorkspaces(),
      (error: unknown) => {
        assert.ok(error instanceof LocalPlatformApiBridgeError);
        assert.equal(error.errorType, "python_runtime_error");
        assert.equal(error.message, "Python local runtime reported an internal error.");
        assert.doesNotMatch(error.message, /Traceback|UserProfile|runtime\.py/i);
        return true;
      },
    );
  } finally {
    rmSync(tempRoot, { recursive: true, force: true });
  }
});

export const testBridgeConfig = (tempRoot: string): GatewayLocalPlatformBridgeConfig => {
  const python = findPythonCommand();
  const beaconRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
  return {
    mode: "python_cli",
    pythonCommand: python.command,
    pythonArgs: python.args,
    pythonCoreCwd: resolve(beaconRoot, "python-core"),
    pythonPath: "src",
    database: join(tempRoot, "platform.sqlite3"),
    workspaceRoot: join(tempRoot, "workspace"),
    pluginsDirectory: join(tempRoot, "plugins"),
    timeoutMs: 20000,
    agentAdapterMode: "deterministic-placeholder",
    openaiCompatibleApiKeyEnvVar: "AGENT_OS_OPENAI_COMPAT_API_KEY",
  };
};

const internalDetailScript = (): string => [
  "import json, sys",
  "sys.stderr.write(json.dumps({'ok': False, 'error': {'type': 'ValueError', 'message': 'Traceback File \"C:\\\\FixtureUser\\\\beacon-runtime.py\"'}}))",
  "sys.exit(1)",
].join("; ");

const localApiContext = (): LocalPlatformApiCallContext => ({
  sessionId: "session-bridge-1",
  correlationId: "correlation-bridge-1",
  actor: {
    actorKind: "local_process",
    actorId: "local-process",
  },
  accessPolicy: {
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
      "agent.invoke",
      "records.read",
      "provider_connection.reserve",
      "agent_binding.reserve",
    ],
  },
});

type FakeProviderRequest = {
  path: string;
  authorization: string | undefined;
  userAgent: string | string[] | undefined;
  body: Record<string, unknown>;
};

const startFakeOpenAICompatibleProvider = async (
  responseContent: string,
): Promise<{
  url: string;
  requests: FakeProviderRequest[];
  close: () => Promise<void>;
}> => {
  const requests: FakeProviderRequest[] = [];
  const server: Server = createServer((request, response) => {
    const chunks: Buffer[] = [];
    request.on("data", (chunk: Buffer) => chunks.push(chunk));
    request.on("end", () => {
      const body = JSON.parse(Buffer.concat(chunks).toString("utf8")) as Record<
        string,
        unknown
      >;
      requests.push({
        path: request.url ?? "",
        authorization: request.headers.authorization,
        userAgent: request.headers["user-agent"],
        body,
      });
      const payload = JSON.stringify({
        model: body.model,
        choices: [
          {
            message: {
              role: "assistant",
              content: responseContent,
            },
            finish_reason: "stop",
          },
        ],
        usage: {
          prompt_tokens: 1,
          completion_tokens: 1,
          total_tokens: 2,
        },
      });
      response.writeHead(200, {
        "content-type": "application/json",
        "content-length": Buffer.byteLength(payload),
      });
      response.end(payload);
    });
  });

  await new Promise<void>((resolveListen) => {
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address();
  assert.ok(address !== null && typeof address === "object");
  return {
    url: `http://127.0.0.1:${address.port}/v1`,
    requests,
    close: () => new Promise<void>((resolveClose) => server.close(() => resolveClose())),
  };
};

const startFakeOpenAIResponsesProvider = async (
  responseContent: string,
  statusCode = 200,
): Promise<{
  url: string;
  requests: FakeProviderRequest[];
  close: () => Promise<void>;
}> => {
  const requests: FakeProviderRequest[] = [];
  const server: Server = createServer((request, response) => {
    const chunks: Buffer[] = [];
    request.on("data", (chunk: Buffer) => chunks.push(chunk));
    request.on("end", () => {
      const body = JSON.parse(Buffer.concat(chunks).toString("utf8")) as Record<
        string,
        unknown
      >;
      requests.push({
        path: request.url ?? "",
        authorization: request.headers.authorization,
        userAgent: request.headers["user-agent"],
        body,
      });
      if (statusCode !== 200) {
        const payload = JSON.stringify({
          error: {
            message: "fake upstream unavailable",
            type: "upstream_error",
          },
        });
        response.writeHead(statusCode, {
          "content-type": "application/json",
          "content-length": Buffer.byteLength(payload),
        });
        response.end(payload);
        return;
      }
      const payload = JSON.stringify({
        id: "resp_gateway_fake_1",
        model: body.model,
        status: "completed",
        output_text: responseContent,
        usage: {
          input_tokens: 1,
          output_tokens: 1,
          total_tokens: 2,
        },
      });
      response.writeHead(200, {
        "content-type": "application/json",
        "content-length": Buffer.byteLength(payload),
      });
      response.end(payload);
    });
  });

  await new Promise<void>((resolveListen) => {
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address();
  assert.ok(address !== null && typeof address === "object");
  return {
    url: `http://127.0.0.1:${address.port}/v1`,
    requests,
    close: () => new Promise<void>((resolveClose) => server.close(() => resolveClose())),
  };
};

const startFakeOllamaProvider = async (
  responseContent: string,
): Promise<{
  url: string;
  requests: FakeProviderRequest[];
  close: () => Promise<void>;
}> => {
  const requests: FakeProviderRequest[] = [];
  const server: Server = createServer((request, response) => {
    const chunks: Buffer[] = [];
    request.on("data", (chunk: Buffer) => chunks.push(chunk));
    request.on("end", () => {
      const body = JSON.parse(Buffer.concat(chunks).toString("utf8")) as Record<
        string,
        unknown
      >;
      requests.push({
        path: request.url ?? "",
        authorization: request.headers.authorization,
        userAgent: request.headers["user-agent"],
        body,
      });
      const payload = JSON.stringify({
        model: body.model,
        message: {
          role: "assistant",
          content: responseContent,
        },
        done_reason: "stop",
      });
      response.writeHead(200, {
        "content-type": "application/json",
        "content-length": Buffer.byteLength(payload),
      });
      response.end(payload);
    });
  });

  await new Promise<void>((resolveListen) => {
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address();
  assert.ok(address !== null && typeof address === "object");
  return {
    url: `http://127.0.0.1:${address.port}`,
    requests,
    close: () => new Promise<void>((resolveClose) => server.close(() => resolveClose())),
  };
};
