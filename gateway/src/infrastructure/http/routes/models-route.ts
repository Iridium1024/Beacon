import type { RouteHandlerMethod } from "fastify";

import type { ListModelsRequest } from "../../../application/dto/model-request.js";
import type { GatewayService } from "../../../application/services/gateway-service.js";
import { buildApiSession, sendEnvelope } from "../context.js";
import type { HttpRouteDefinition } from "../server.js";

const createModelsHandler = (gatewayService: GatewayService): RouteHandlerMethod => {
  return async (request, reply) => {
    const session = buildApiSession(request);
    const query = (request.query as ListModelsRequest | undefined) ?? {};
    const response = await gatewayService.listModels(session, query);
    return sendEnvelope(reply, response);
  };
};

export const createModelsRoute = (gatewayService: GatewayService): HttpRouteDefinition => ({
  method: "GET",
  path: "/models",
  handler: createModelsHandler(gatewayService),
});
