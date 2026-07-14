import type { RouteHandlerMethod } from "fastify";

import type { SingleTurnPlatformInvocationRequest } from "../../../application/dto/platform-invocation-request.js";
import type { GatewayService } from "../../../application/services/gateway-service.js";
import { buildApiSession } from "../context.js";
import type { HttpRouteDefinition } from "../server.js";

const createSingleTurnPlatformInvocationHandler = (
  gatewayService: GatewayService,
): RouteHandlerMethod => {
  return async (request, reply) => {
    const session = buildApiSession(request);
    const envelope = gatewayService.createSingleTurnPlatformInvocationEnvelope(
      (request.body ?? {}) as SingleTurnPlatformInvocationRequest,
    );

    return reply.code(501).send({
      ...envelope,
      metadata: {
        ...(envelope.metadata ?? {}),
        routeStatus: "not_wired",
        platformRuntimeWired: "false",
        sessionId: session.sessionId,
        correlationId: session.correlationId,
      },
    });
  };
};

export const createSingleTurnPlatformInvocationRoute = (
  gatewayService: GatewayService,
): HttpRouteDefinition => ({
  method: "POST",
  path: "/platform/invocations/single-turn",
  handler: createSingleTurnPlatformInvocationHandler(gatewayService),
});
