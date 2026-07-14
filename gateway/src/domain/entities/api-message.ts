export interface GatewayEnvelope<TPayload = Record<string, unknown>> {
  protocolVersion: string;
  requestId: string;
  kind: string;
  payload: TPayload;
  metadata?: Record<string, string>;
}
