export interface ListModelsRequest {
  provider?: string;
  metadata?: Record<string, string>;
}

export interface ListModelsResponse {
  requestId: string;
  kind: string;
  payload: Record<string, unknown>;
  metadata?: Record<string, string>;
}
