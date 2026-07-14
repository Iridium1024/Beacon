import { randomUUID } from "node:crypto";

import type { FastifyReply, FastifyRequest } from "fastify";

import type { ApiSession } from "../../domain/entities/api-session.js";

export const buildApiSession = (request: FastifyRequest): ApiSession => {
  const sessionIdHeader = request.headers["x-session-id"];
  const correlationIdHeader = request.headers["x-correlation-id"];

  const sessionId = typeof sessionIdHeader === "string" ? sessionIdHeader : randomUUID();
  const correlationId =
    typeof correlationIdHeader === "string" ? correlationIdHeader : randomUUID();

  return {
    sessionId,
    correlationId,
    metadata: {
      method: request.method,
      url: request.url,
    },
  };
};

export const sendEnvelope = (
  reply: FastifyReply,
  envelope: {
    requestId: string;
    kind: string;
    payload: Record<string, unknown>;
    metadata?: Record<string, string>;
  },
): FastifyReply => {
  return reply.code(200).send(envelope);
};
