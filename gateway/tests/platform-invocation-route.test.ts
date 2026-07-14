import assert from "node:assert/strict";
import test from "node:test";

import type { SingleTurnPlatformInvocationRequest } from "../src/application/dto/platform-invocation-request.js";
import type { GatewayService } from "../src/application/services/gateway-service.js";
import { createSingleTurnPlatformInvocationRoute } from "../src/infrastructure/http/routes/platform-invocation-route.js";
import { createHttpServer } from "../src/infrastructure/http/server.js";

test("single-turn platform invocation route stays disabled and local-only", async () => {
  let envelopeCreateCount = 0;
  let receivedRequest: SingleTurnPlatformInvocationRequest | undefined;

  const unexpected = (method: string): never => {
    throw new Error(`unexpected GatewayService method: ${method}`);
  };
  const gatewayService: GatewayService = {
    async submitTask() {
      return unexpected("submitTask");
    },
    async submitWorkflow() {
      return unexpected("submitWorkflow");
    },
    async listAgents() {
      return unexpected("listAgents");
    },
    async registerAgent() {
      return unexpected("registerAgent");
    },
    async listModels() {
      return unexpected("listModels");
    },
    async exchangeContext() {
      return unexpected("exchangeContext");
    },
    createSingleTurnPlatformInvocationEnvelope(
      request: SingleTurnPlatformInvocationRequest,
    ) {
      envelopeCreateCount += 1;
      receivedRequest = request;

      return {
        protocolVersion: "1.0",
        requestId: "request-1",
        kind: "platform.invocation.single_turn",
        payload: request,
        metadata: {
          serviceStatus: "local_envelope_only",
        },
      };
    },
  };

  const server = createHttpServer("127.0.0.1", 0);
  await server.registerRoute(createSingleTurnPlatformInvocationRoute(gatewayService));

  try {
    const response = await server.raw().inject({
      method: "POST",
      url: "/platform/invocations/single-turn",
      headers: {
        "content-type": "application/json",
        "x-session-id": "session-1",
        "x-correlation-id": "correlation-1",
      },
      payload: JSON.stringify({
        workspaceId: "workspace-1",
        agentId: "agent-1",
        instruction: "Summarize current context.",
        conversationId: "conversation-1",
        fileOperations: [
          {
            operationKind: "read_file",
            relativePath: "docs/status.md",
            operationId: "file-op-1",
            contextUpdateId: "update-file-ref-1",
          },
        ],
      }),
    });

    assert.equal(response.statusCode, 501);
    assert.equal(envelopeCreateCount, 1);
    assert.equal(receivedRequest?.workspaceId, "workspace-1");
    assert.equal(receivedRequest?.agentId, "agent-1");
    assert.equal(receivedRequest?.instruction, "Summarize current context.");
    assert.equal(receivedRequest?.conversationId, "conversation-1");
    assert.equal(receivedRequest?.fileOperations?.[0]?.operationId, "file-op-1");

    const body = JSON.parse(response.payload) as {
      protocolVersion: string;
      requestId: string;
      kind: string;
      payload: SingleTurnPlatformInvocationRequest;
      metadata: Record<string, string>;
    };

    assert.equal(body.protocolVersion, "1.0");
    assert.equal(body.requestId, "request-1");
    assert.equal(body.kind, "platform.invocation.single_turn");
    assert.equal(body.payload.workspaceId, "workspace-1");
    assert.equal(body.payload.conversationId, "conversation-1");
    assert.equal(body.payload.fileOperations?.[0]?.relativePath, "docs/status.md");
    assert.equal(body.metadata.serviceStatus, "local_envelope_only");
    assert.equal(body.metadata.routeStatus, "not_wired");
    assert.equal(body.metadata.platformRuntimeWired, "false");
    assert.equal(body.metadata.sessionId, "session-1");
    assert.equal(body.metadata.correlationId, "correlation-1");
  } finally {
    await server.raw().close();
  }
});
