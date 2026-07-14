import { randomUUID } from "node:crypto";

import type { ListAgentsRequest } from "../dto/agent-request.js";
import type { ListModelsRequest } from "../dto/model-request.js";
import type { SingleTurnPlatformInvocationRequest } from "../dto/platform-invocation-request.js";
import type { TaskRequest } from "../dto/task-request.js";
import type { ExchangeContextRequest, RegisterAgentRequest, SubmitWorkflowRequest } from "../dto/workflow-request.js";
import type { CoreRuntimeClient } from "../../domain/contracts/core-runtime.js";
import type { GatewayEnvelope } from "../../domain/entities/api-message.js";
import type { ApiSession } from "../../domain/entities/api-session.js";

export interface GatewayService {
  submitTask(
    session: ApiSession,
    request: TaskRequest,
  ): Promise<GatewayEnvelope<Record<string, unknown>>>;

  submitWorkflow(
    session: ApiSession,
    request: SubmitWorkflowRequest,
  ): Promise<GatewayEnvelope<Record<string, unknown>>>;

  listAgents(
    session: ApiSession,
    request: ListAgentsRequest,
  ): Promise<GatewayEnvelope<Record<string, unknown>>>;

  registerAgent(
    session: ApiSession,
    request: RegisterAgentRequest,
  ): Promise<GatewayEnvelope<Record<string, unknown>>>;

  listModels(
    session: ApiSession,
    request: ListModelsRequest,
  ): Promise<GatewayEnvelope<Record<string, unknown>>>;

  exchangeContext(
    session: ApiSession,
    request: ExchangeContextRequest,
  ): Promise<GatewayEnvelope<Record<string, unknown>>>;

  createSingleTurnPlatformInvocationEnvelope(
    request: SingleTurnPlatformInvocationRequest,
  ): GatewayEnvelope<SingleTurnPlatformInvocationRequest>;
}

export class DefaultGatewayService implements GatewayService {
  public constructor(private readonly coreRuntime: CoreRuntimeClient) {}

  public async submitTask(
    session: ApiSession,
    request: TaskRequest,
  ): Promise<GatewayEnvelope<Record<string, unknown>>> {
    return this.coreRuntime.send(session, this.createEnvelope("task.submit", request));
  }

  public async submitWorkflow(
    session: ApiSession,
    request: SubmitWorkflowRequest,
  ): Promise<GatewayEnvelope<Record<string, unknown>>> {
    return this.coreRuntime.send(session, this.createEnvelope("workflow.submit", request));
  }

  public async listAgents(
    session: ApiSession,
    request: ListAgentsRequest,
  ): Promise<GatewayEnvelope<Record<string, unknown>>> {
    return this.coreRuntime.send(session, this.createEnvelope("agents.list", request));
  }

  public async registerAgent(
    session: ApiSession,
    request: RegisterAgentRequest,
  ): Promise<GatewayEnvelope<Record<string, unknown>>> {
    return this.coreRuntime.send(session, this.createEnvelope("agent.register", request));
  }

  public async listModels(
    session: ApiSession,
    request: ListModelsRequest,
  ): Promise<GatewayEnvelope<Record<string, unknown>>> {
    return this.coreRuntime.send(session, this.createEnvelope("models.list", request));
  }

  public async exchangeContext(
    session: ApiSession,
    request: ExchangeContextRequest,
  ): Promise<GatewayEnvelope<Record<string, unknown>>> {
    return this.coreRuntime.send(session, this.createEnvelope("context.exchange", request));
  }

  public createSingleTurnPlatformInvocationEnvelope(
    request: SingleTurnPlatformInvocationRequest,
  ): GatewayEnvelope<SingleTurnPlatformInvocationRequest> {
    return this.createEnvelope("platform.invocation.single_turn", request);
  }

  private createEnvelope<TPayload extends object>(
    kind: string,
    payload: TPayload,
  ): GatewayEnvelope<TPayload> {
    return {
      protocolVersion: "1.0",
      requestId: randomUUID(),
      kind,
      payload,
    };
  }
}
