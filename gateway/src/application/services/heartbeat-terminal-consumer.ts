import {
  decodeHeartbeatTerminalExport,
  type HeartbeatTerminalExportPayload,
  type ProtocolEnvelope,
} from "../../domain/contracts/heartbeat-terminal-export.js";

export interface HeartbeatTerminalConsumer {
  consume(envelope: unknown): HeartbeatTerminalExportPayload;
}

export class DefaultHeartbeatTerminalConsumer implements HeartbeatTerminalConsumer {
  public consume(envelope: unknown): HeartbeatTerminalExportPayload {
    return decodeHeartbeatTerminalExport(envelope);
  }
}

export const consumeHeartbeatTerminalEnvelope = (
  envelope: ProtocolEnvelope<unknown> | unknown,
): HeartbeatTerminalExportPayload => decodeHeartbeatTerminalExport(envelope);
