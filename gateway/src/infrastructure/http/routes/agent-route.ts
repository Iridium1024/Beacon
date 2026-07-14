import type { RouteHandlerMethod } from "fastify";

import type { ListAgentsRequest } from "../../../application/dto/agent-request.js";
import type { GatewayService } from "../../../application/services/gateway-service.js";
import { buildApiSession, sendEnvelope } from "../context.js";
import type { HttpRouteDefinition } from "../server.js";

const createAgentsHandler = (gatewayService: GatewayService): RouteHandlerMethod => {
  return async (request, reply) => {
    const session = buildApiSession(request);
    const query = (request.query as ListAgentsRequest | undefined) ?? {};
    const response = await gatewayService.listAgents(session, query);
    return sendEnvelope(reply, response);
  };
};

export const createAgentsRoute = (gatewayService: GatewayService): HttpRouteDefinition => ({
  method: "GET",
  path: "/agents",
  handler: createAgentsHandler(gatewayService),
});
