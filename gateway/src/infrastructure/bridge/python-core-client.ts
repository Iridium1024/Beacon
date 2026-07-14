import type { CoreRuntimeClient } from "../../domain/contracts/core-runtime.js";
import type { TransportProtocol } from "../../domain/contracts/transport-protocol.js";
import type { GatewayEnvelope } from "../../domain/entities/api-message.js";
import type { ApiSession } from "../../domain/entities/api-session.js";

export class PythonCoreClient implements CoreRuntimeClient {
  public constructor(private readonly protocol: TransportProtocol, private readonly endpoint: string) {}

  public async send<TRequest extends object, TResponse extends object>(
    session: ApiSession,
    envelope: GatewayEnvelope<TRequest>,
  ): Promise<GatewayEnvelope<TResponse>> {
    const response = await fetch(this.endpoint, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-session-id": session.sessionId,
        "x-correlation-id": session.correlationId,
      },
      body: this.protocol.encode({
        ...envelope,
        metadata: {
          ...(envelope.metadata ?? {}),
          ...(session.metadata ?? {}),
        },
      }),
    });

    const rawPayload = await response.text();
    return this.protocol.decode<TResponse>(rawPayload);
  }
}
