import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import type { AddressInfo } from "node:net";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer, type Server } from "node:http";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { buildGateway } from "../src/index.js";
import { findPythonCommand } from "./support/python-command.js";

test("gateway HTTP API calls Python local runtime through bridge", async () => {
  const tempRoot = mkdtempSync(join(tmpdir(), "agent-os-gateway-http-smoke-"));
  const python = findPythonCommand();
  const envPatch = bridgeEnv(tempRoot, python.command, python.args);
  const previousEnv = patchEnv(envPatch);
  const runtime = await buildGateway();

  try {
    await runtime.server.start();
    const address = runtime.server.raw().server.address() as AddressInfo;
    const baseUrl = `http://127.0.0.1:${address.port}`;

    const created = await requestJson(baseUrl, "POST", "/api/v1/workspaces", {
      workspaceId: "workspace-http-bridge-1",
      displayName: "HTTP Bridge Workspace",
    });
    const listed = await requestJson(baseUrl, "GET", "/api/v1/workspaces");
    const opened = await requestJson(baseUrl, "GET", "/api/v1/workspaces/workspace-http-bridge-1");
    const invocation = await requestJson(
      baseUrl,
      "POST",
      "/api/v1/workspaces/workspace-http-bridge-1/invocations",
      {
        agentId: "agent-workspace-http-bridge-1",
        instruction: "Run HTTP bridge invocation.",
        invocationId: "invoke-http-bridge-1",
      },
    );
    const context = await requestJson(baseUrl, "GET", "/api/v1/workspaces/workspace-http-bridge-1/context");
    const records = await requestJson(baseUrl, "GET", "/api/v1/workspaces/workspace-http-bridge-1/invocations");
    const timeline = await requestJson(
      baseUrl,
      "GET",
      "/api/v1/workspaces/workspace-http-bridge-1/sessions/session-http-bridge-1/timeline",
    );

    assert.equal(created.status, 201);
    assert.equal(created.body.ok, true);
    assert.equal(created.body.metadata.platformRuntimeWired, "true");
    assert.equal(created.body.payload.workspace.workspace.workspaceId, "workspace-http-bridge-1");
    assert.equal(listed.body.payload.workspaces[0].workspaceId, "workspace-http-bridge-1");
    assert.equal(opened.body.payload.workspace.workspaceId, "workspace-http-bridge-1");
    assert.equal(invocation.body.payload.invocationResult.invocationId, "invoke-http-bridge-1");
    assert.equal(context.body.payload.context.workspaceId, "workspace-http-bridge-1");
    assert.equal(records.body.payload.invocations[0].correlationId, "correlation-http-bridge-1");
    assert.equal(timeline.body.payload.session.sessionId, "session-http-bridge-1");
    assert.equal(timeline.body.payload.session.status, "completed");
    assert.equal(timeline.body.payload.session.lifecycle.hasExplicitLifecycleEvents, true);
    assert.equal(timeline.body.payload.session.lifecycle.recoveryState, "closed");
  } finally {
    await runtime.server.raw().close();
    restoreEnv(previousEnv);
    rmSync(tempRoot, { recursive: true, force: true });
  }
});

test("gateway HTTP API can invoke provider API shape through Python bridge", async () => {
  const tempRoot = mkdtempSync(join(tmpdir(), "agent-os-gateway-http-provider-"));
  const python = findPythonCommand();
  const fakeProvider = await startFakeOpenAIResponsesProvider(
    "HTTP fake Responses response.",
  );
  const credentialEnvVar = "AGENT_OS_RESPONSES_HTTP_TEST_CREDENTIAL";
  const envPatch = {
    ...bridgeEnv(tempRoot, python.command, python.args),
    LOCAL_PLATFORM_AGENT_ADAPTER_MODE: "provider-api-shape",
    AGENT_OS_PROVIDER_API_SHAPE: "openai-responses",
    AGENT_OS_PROVIDER_BASE_URL: fakeProvider.url,
    AGENT_OS_PROVIDER_MODEL: "fake-http-responses-model",
    AGENT_OS_PROVIDER_NAME: "openai-responses",
    AGENT_OS_PROVIDER_API_KEY_ENV_VAR: credentialEnvVar,
    AGENT_OS_PROVIDER_MAX_TOKENS: "21",
    AGENT_OS_PROVIDER_INPUT_MODE: "plain_text",
    AGENT_OS_PROVIDER_USER_AGENT: "AgentChatGatewayHttp/14.2",
    [credentialEnvVar]: randomUUID(),
  };
  const previousEnv = patchEnv(envPatch);
  const runtime = await buildGateway();

  try {
    await runtime.server.start();
    const address = runtime.server.raw().server.address() as AddressInfo;
    const baseUrl = `http://127.0.0.1:${address.port}`;

    await requestJson(baseUrl, "POST", "/api/v1/workspaces", {
      workspaceId: "workspace-http-provider-1",
      displayName: "HTTP Provider Workspace",
    });
    const invocation = await requestJson(
      baseUrl,
      "POST",
      "/api/v1/workspaces/workspace-http-provider-1/invocations",
      {
        agentId: "agent-workspace-http-provider-1",
        instruction: "Run HTTP provider shape invocation.",
        invocationId: "invoke-http-provider-1",
      },
    );

    assert.equal(invocation.status, 200);
    assert.equal(invocation.body.ok, true);
    assert.equal(invocation.body.payload.modelInvoked, true);
    assert.equal(invocation.body.payload.deterministicPlaceholder, false);
    assert.equal(
      invocation.body.payload.invocationResult.outputText,
      "HTTP fake Responses response.",
    );
    assert.equal(fakeProvider.requests[0].path, "/v1/responses");
    assert.equal(
      fakeProvider.requests[0].authorization,
      `Bearer ${process.env[credentialEnvVar]}`,
    );
    assert.equal(
      fakeProvider.requests[0].userAgent,
      "AgentChatGatewayHttp/14.2",
    );
    assert.equal(fakeProvider.requests[0].body.model, "fake-http-responses-model");
    assert.equal(fakeProvider.requests[0].body.max_output_tokens, 21);
    assert.equal(
      fakeProvider.requests[0].body.input,
      "Run HTTP provider shape invocation.",
    );
    assert.equal("max_tokens" in fakeProvider.requests[0].body, false);
    assert.equal("input_mode" in fakeProvider.requests[0].body, false);
  } finally {
    await runtime.server.raw().close();
    restoreEnv(previousEnv);
    await fakeProvider.close();
    rmSync(tempRoot, { recursive: true, force: true });
  }
});

const requestJson = async (
  baseUrl: string,
  method: "GET" | "POST",
  path: string,
  payload?: object,
): Promise<{ status: number; body: any }> => {
  const response = await fetch(`${baseUrl}${path}`, {
    method,
    headers: {
      "content-type": "application/json",
      "x-session-id": "session-http-bridge-1",
      "x-correlation-id": "correlation-http-bridge-1",
    },
    ...(payload ? { body: JSON.stringify(payload) } : {}),
  });
  return {
    status: response.status,
    body: await response.json(),
  };
};

const bridgeEnv = (
  tempRoot: string,
  pythonCommand: string,
  pythonArgs: string[],
): Record<string, string> => {
  const beaconRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
  return {
    GATEWAY_HOST: "127.0.0.1",
    GATEWAY_PORT: "0",
    LOCAL_PLATFORM_BRIDGE_MODE: "python_cli",
    LOCAL_PLATFORM_PYTHON_COMMAND: pythonCommand,
    LOCAL_PLATFORM_PYTHON_ARGS: pythonArgs.join(" "),
    LOCAL_PLATFORM_PYTHON_CORE_CWD: resolve(beaconRoot, "python-core"),
    LOCAL_PLATFORM_PYTHONPATH: "src",
    LOCAL_PLATFORM_DATABASE: join(tempRoot, "platform.sqlite3"),
    LOCAL_PLATFORM_WORKSPACE_ROOT: join(tempRoot, "workspace"),
    LOCAL_PLATFORM_PLUGINS_DIRECTORY: join(tempRoot, "plugins"),
    LOCAL_PLATFORM_BRIDGE_TIMEOUT_MS: "20000",
  };
};

const patchEnv = (patch: Record<string, string>): Record<string, string | undefined> => {
  const previous: Record<string, string | undefined> = {};
  for (const [key, value] of Object.entries(patch)) {
    previous[key] = process.env[key];
    process.env[key] = value;
  }
  return previous;
};

const restoreEnv = (previous: Record<string, string | undefined>): void => {
  for (const [key, value] of Object.entries(previous)) {
    if (value === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = value;
    }
  }
};

type FakeProviderRequest = {
  path: string;
  authorization: string | undefined;
  userAgent: string | string[] | undefined;
  body: Record<string, unknown>;
};

const startFakeOpenAIResponsesProvider = async (
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
        id: "resp_gateway_http_fake_1",
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
