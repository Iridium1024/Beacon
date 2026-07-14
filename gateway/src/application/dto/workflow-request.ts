export type ExecutionMode = "sequential" | "parallel" | "hybrid";

export interface SubmitWorkflowRequest {
  goal: string;
  executionMode?: ExecutionMode;
  entryAgentId?: string;
  metadata?: Record<string, string>;
}

export interface RegisterAgentRequest {
  agentId: string;
  name: string;
  description: string;
  capabilities: string[];
  metadata?: Record<string, string>;
}

export interface ExchangeContextRequest {
  workflowId: string;
  fromAgentId: string;
  toAgentId: string;
  objective: string;
}
