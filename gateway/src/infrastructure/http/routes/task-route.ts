import type { RouteHandlerMethod } from "fastify";

import type { GatewayService } from "../../../application/services/gateway-service.js";
import type { TaskRequest } from "../../../application/dto/task-request.js";
import { buildApiSession, sendEnvelope } from "../context.js";
import type { HttpRouteDefinition } from "../server.js";

const createTaskHandler = (gatewayService: GatewayService): RouteHandlerMethod => {
  return async (request, reply) => {
    const session = buildApiSession(request);
    const response = await gatewayService.submitTask(session, request.body as TaskRequest);
    return sendEnvelope(reply, response);
  };
};

export const createTaskRoute = (gatewayService: GatewayService): HttpRouteDefinition => ({
  method: "POST",
  path: "/task",
  handler: createTaskHandler(gatewayService),
});
