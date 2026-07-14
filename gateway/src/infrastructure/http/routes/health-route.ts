import type { RouteHandlerMethod } from "fastify";

import type { HealthService } from "../../../application/services/health-service.js";
import type { HttpRouteDefinition } from "../server.js";

const createHealthHandler = (healthService: HealthService): RouteHandlerMethod => {
  return async (_request, reply) => {
    const status = await healthService.getStatus();
    return reply.code(200).send(status);
  };
};

export const createHealthRoute = (healthService: HealthService): HttpRouteDefinition => ({
  method: "GET",
  path: "/health",
  handler: createHealthHandler(healthService),
});
