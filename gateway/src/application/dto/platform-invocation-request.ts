export type PlatformInvocationMetadata = Record<string, unknown>;

export type PlatformInvocationResultStatus = "succeeded" | "failed" | "cancelled";

export type PlatformFileOperationKind =
  | "read_file"
  | "list_directory"
  | "write_file"
  | "readFile"
  | "listDirectory"
  | "writeFile";

export type PlatformInvocationFileOperationRequestKind =
  | "read_file"
  | "list_directory"
  | "readFile"
  | "listDirectory";

export type PlatformFileOperationStatus =
  | "requested"
  | "succeeded"
  | "failed"
  | "denied";

export type PlatformContextUpdateKind =
  | "user_message"
  | "agent_message"
  | "file_reference"
  | "tool_result"
  | "decision"
  | "note"
  | "artifact";

export type PlatformConversationStatus = "active" | "archived";

export type PlatformConversationMessageRole =
  | "user"
  | "assistant"
  | "system"
  | "tool"
  | "note";

export interface PlatformInvocationFileOperationRequest {
  operationKind: PlatformInvocationFileOperationRequestKind;
  relativePath: string;
  operationId?: string;
  eventId?: string;
  contextUpdateId?: string;
  contextEventId?: string;
  recursive?: boolean;
  reason?: string;
  requestMetadata?: PlatformInvocationMetadata;
  auditMetadata?: PlatformInvocationMetadata;
}

export type SingleTurnPlatformInvocationRequest = PlatformInvocationMetadata & {
  workspaceId: string;
  agentId: string;
  instruction: string;
  invocationId?: string;
  requestedAt?: string;
  taskId?: string;
  requestedCapability?: string;
  contextUpdateIds?: string[];
  fileReferences?: string[];
  idempotencyKey?: string;
  correlationId?: string;
  requestMetadata?: PlatformInvocationMetadata;
  userContextUpdateId?: string;
  userContextCreatedAt?: string;
  contextEventId?: string;
  agentInvocationEventId?: string;
  sessionId?: string;
  contextMetadata?: PlatformInvocationMetadata;
  contextEventMetadata?: PlatformInvocationMetadata;
  agentInvocationEventMetadata?: PlatformInvocationMetadata;
  fileOperations?: PlatformInvocationFileOperationRequest[];
  conversationId?: string;
};

export interface PlatformInvocationFileOperationSummary {
  operationId: string;
  workspaceId: string;
  operationKind: PlatformFileOperationKind;
  relativePath: string;
  status: PlatformFileOperationStatus;
  sourceEventSequence: number;
  contextUpdateId?: string | null;
  contextEventSequence?: number | null;
  bytesRead?: number | null;
  bytesWritten?: number | null;
  errorMessage?: string | null;
  outputPayload?: PlatformInvocationMetadata;
}

export interface ContextUpdateInfoDto {
  updateId: string;
  workspaceId: string;
  updateKind: PlatformContextUpdateKind;
  summary: string;
  createdAt: string;
  sourceAgentId?: string | null;
  payload?: PlatformInvocationMetadata;
  materializedStatePatch?: PlatformInvocationMetadata;
  metadata?: PlatformInvocationMetadata;
}

export interface AgentInvocationResultDto {
  invocationId: string;
  workspaceId: string;
  agentId: string;
  status: PlatformInvocationResultStatus;
  summary: string;
  completedAt: string;
  outputText?: string | null;
  errorMessage?: string | null;
  outputPayload?: PlatformInvocationMetadata;
  contextUpdateIds: string[];
  metadata?: PlatformInvocationMetadata;
}

export interface PlatformConversationSessionSummary {
  conversationId: string;
  workspaceId: string;
  agentId?: string | null;
  sourceEventSequence?: number;
  title: string;
  status: PlatformConversationStatus;
  createdAt: string;
  updatedAt: string;
  archivedAt?: string | null;
  metadata?: PlatformInvocationMetadata;
}

export interface PlatformConversationMessageSummary {
  messageId: string;
  conversationId: string;
  workspaceId: string;
  sourceEventSequence: number;
  sequence: number;
  role: PlatformConversationMessageRole;
  content: string;
  agentId?: string | null;
  invocationId?: string | null;
  contextUpdateId?: string | null;
  runSessionId?: string | null;
  createdAt: string;
  metadata?: PlatformInvocationMetadata;
}

export interface SingleTurnPlatformInvocationResponse {
  workspaceId: string;
  agentId: string;
  contextId: string;
  runtimeLoaded: boolean;
  modelInvoked: boolean;
  toolInvoked: boolean;
  deterministicPlaceholder: boolean;
  invocationResult: AgentInvocationResultDto;
  userContextUpdate: ContextUpdateInfoDto;
  sourceEventSequence: number;
  agentInvocationEventSequence?: number | null;
  runSessionEventSequences?: {
    started?: number | null;
    terminal?: number | null;
  };
  materializedState?: PlatformInvocationMetadata;
  fileOperations: PlatformInvocationFileOperationSummary[];
  conversation: PlatformConversationSessionSummary | null;
  conversationMessages: PlatformConversationMessageSummary[];
}
