import type { TransportProtocol } from "../../domain/contracts/transport-protocol.js";
import type { GatewayEnvelope } from "../../domain/entities/api-message.js";

export class JsonRpcClientProtocol implements TransportProtocol {
  public readonly kind = "http" as const;

  public encode<TPayload extends object>(envelope: GatewayEnvelope<TPayload>): string {
    return JSON.stringify(envelope);
  }

  public decode<TPayload extends object>(message: string): GatewayEnvelope<TPayload> {
    return JSON.parse(message) as GatewayEnvelope<TPayload>;
  }
}
