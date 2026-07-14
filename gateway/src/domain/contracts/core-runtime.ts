import type { GatewayEnvelope } from "../entities/api-message.js";
import type { ApiSession } from "../entities/api-session.js";

export interface CoreRuntimeClient {
  send<TRequest extends object, TResponse extends object>(
    session: ApiSession,
    envelope: GatewayEnvelope<TRequest>,
  ): Promise<GatewayEnvelope<TResponse>>;
}
