import type { ExecutionMode } from "./workflow-request.js";

export interface TaskRequest {
  goal: string;
  executionMode?: ExecutionMode;
  entryAgentId?: string;
  metadata?: Record<string, string>;
}

export interface TaskResponse {
  requestId: string;
  kind: string;
  payload: Record<string, unknown>;
  metadata?: Record<string, string>;
}
