import type { GatewayEnvelope } from "../entities/api-message.js";

export interface TransportProtocol {
  readonly kind: "json-rpc" | "http" | "stdio";
  encode<TPayload extends object>(envelope: GatewayEnvelope<TPayload>): string;
  decode<TPayload extends object>(message: string): GatewayEnvelope<TPayload>;
}
