export interface ListAgentsRequest {
  capability?: string;
  metadata?: Record<string, string>;
}

export interface AgentRouteResponse {
  requestId: string;
  kind: string;
  payload: Record<string, unknown>;
  metadata?: Record<string, string>;
}
