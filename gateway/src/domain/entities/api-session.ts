export interface ApiSession {
  sessionId: string;
  workflowId?: string;
  correlationId: string;
  metadata?: Record<string, string>;
}
