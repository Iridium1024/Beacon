export type LocalPlatformOperationMetadata = Record<string, unknown>;

export type LocalAgentInvocationRecordStatus =
  | "requested"
  | "succeeded"
  | "failed"
  | "cancelled";

export type LocalFileOperationRecordKind =
  | "read_file"
  | "write_file"
  | "list_directory";

export type LocalFileOperationRecordStatus =
  | "requested"
  | "succeeded"
  | "failed"
  | "denied";

export type LocalContextUpdateKind =
  | "user_message"
  | "agent_message"
  | "file_reference"
  | "tool_result"
  | "decision"
  | "note"
  | "artifact";

export type LocalConversationStatus = "active" | "archived";

export type LocalConversationMessageRole =
  | "user"
  | "assistant"
  | "system"
  | "tool"
  | "note";

export interface LocalWorkspaceStateDto {
  workspaceId: string;
  sourceEventSequence: number;
  displayName: string;
  rootPath: string;
  status: string;
  createdAt: string;
  updatedAt: string;
  workspaceState: LocalPlatformOperationMetadata;
  bindingState: LocalPlatformOperationMetadata;
  metadata: LocalPlatformOperationMetadata;
}

export interface LocalContextStateDto {
  workspaceId: string;
  contextId: string;
  sourceEventSequence: number;
  updateCount: number;
  materializedState: LocalPlatformOperationMetadata;
  createdAt: string;
  updatedAt: string;
  metadata: LocalPlatformOperationMetadata;
}

export interface LocalContextUpdateDto {
  updateId: string;
  workspaceId: string;
  updateKind: LocalContextUpdateKind;
  summary: string;
  createdAt: string;
  sourceAgentId: string | null;
  payload: LocalPlatformOperationMetadata;
  materializedStatePatch: LocalPlatformOperationMetadata;
  metadata: LocalPlatformOperationMetadata;
}

export interface LocalAgentCapabilityDto {
  name: string;
  description: string;
  metadata: LocalPlatformOperationMetadata;
}

export interface LocalAgentRegistrationStateDto {
  agentId: string;
  workspaceId: string;
  sourceEventSequence: number;
  name: string;
  description: string;
  status: string;
  defaultModel: string | null;
  capabilities: LocalAgentCapabilityDto[];
  toolPermissions: string[];
  runtimeConfig: LocalPlatformOperationMetadata;
  createdAt: string;
  updatedAt: string;
  registrationState: LocalPlatformOperationMetadata;
  metadata: LocalPlatformOperationMetadata;
}

export interface LocalAgentRuntimePermissionDto {
  workspaceId: string;
  agentId: string;
  profileName: string;
  roleName: string;
  runtimeKind: string;
  providerBackedModel: boolean;
  runtimeConnected: false;
  readModelOnly: true;
  configuredProfile: LocalPlatformOperationMetadata;
  capabilities: LocalPlatformOperationMetadata;
  grant: LocalPlatformOperationMetadata;
  deliveryPlan: LocalPlatformOperationMetadata;
  boundary: LocalPlatformOperationMetadata;
}

export interface LocalConversationSessionDto {
  conversationId: string;
  workspaceId: string;
  agentId: string | null;
  sourceEventSequence?: number;
  title: string;
  status: LocalConversationStatus;
  createdAt: string;
  updatedAt: string;
  archivedAt: string | null;
  metadata: LocalPlatformOperationMetadata;
}

export interface LocalConversationMessageDto {
  messageId: string;
  conversationId: string;
  workspaceId: string;
  sourceEventSequence: number;
  sequence: number;
  role: LocalConversationMessageRole;
  content: string;
  agentId: string | null;
  invocationId: string | null;
  contextUpdateId: string | null;
  runSessionId: string | null;
  createdAt: string;
  metadata: LocalPlatformOperationMetadata;
}

export interface LocalTaskStateDto {
  taskId: string;
  workspaceId: string;
  sourceEventSequence: number;
  title: string;
  status: string;
  description: string | null;
  assigneeAgentId: string | null;
  contextUpdateIds: string[];
  linkedFilePaths: string[];
  createdAt: string;
  updatedAt: string;
  taskState: LocalPlatformOperationMetadata;
  metadata: LocalPlatformOperationMetadata;
}

export interface LocalIssueStateDto {
  issueId: string;
  workspaceId: string;
  sourceEventSequence: number;
  title: string;
  status: string;
  severity: string;
  description: string | null;
  linkedTaskId: string | null;
  contextUpdateIds: string[];
  linkedFilePaths: string[];
  createdAt: string;
  updatedAt: string;
  issueState: LocalPlatformOperationMetadata;
  metadata: LocalPlatformOperationMetadata;
}

export interface LocalPlatformEventDto {
  sequence: number;
  eventId: string;
  workspaceId: string;
  sessionId: string | null;
  eventKind: string;
  aggregateType: string;
  aggregateId: string;
  occurredAt: string;
  correlationId: string | null;
  idempotencyKey: string | null;
  payload: LocalPlatformOperationMetadata;
  metadata: LocalPlatformOperationMetadata;
}

export interface LocalRunSessionTimelineDto {
  workspaceId: string;
  sessionId: string;
  status: string;
  eventCount: number;
  firstSequence: number | null;
  lastSequence: number | null;
  firstOccurredAt: string | null;
  lastOccurredAt: string | null;
  lifecycle: {
    hasExplicitLifecycleEvents: boolean;
    statusSource: "run_session_event" | "observed_events" | "none";
    recoveryState: "missing" | "open" | "closed" | "observed_without_lifecycle";
    startedSequence: number | null;
    terminalSequence: number | null;
    startedAt: string | null;
    endedAt: string | null;
    invocationEventCount: number;
    contextUpdateEventCount: number;
    fileOperationEventCount: number;
  };
}

export interface LocalRunSessionTimelineResponse {
  session: LocalRunSessionTimelineDto;
  events: LocalPlatformEventDto[];
}

export interface LocalAgentInvocationRecordDto {
  invocationId: string;
  workspaceId: string;
  agentId: string;
  taskId: string | null;
  sourceEventSequence: number;
  status: LocalAgentInvocationRecordStatus;
  instruction: string;
  requestedCapability: string | null;
  idempotencyKey: string | null;
  correlationId: string | null;
  requestState: LocalPlatformOperationMetadata;
  resultState: LocalPlatformOperationMetadata;
  contextUpdateIds: string[];
  fileReferences: string[];
  metadata: LocalPlatformOperationMetadata;
  requestedAt: string;
  completedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface LocalFileOperationRecordDto {
  operationId: string;
  workspaceId: string;
  sourceEventSequence: number;
  operationKind: LocalFileOperationRecordKind;
  relativePath: string;
  status: LocalFileOperationRecordStatus;
  requestedByAgentId: string | null;
  invocationId: string | null;
  taskId: string | null;
  contextUpdateId: string | null;
  requestState: LocalPlatformOperationMetadata;
  resultState: LocalPlatformOperationMetadata;
  outputPayload: LocalPlatformOperationMetadata;
  metadata: LocalPlatformOperationMetadata;
  requestedAt: string;
  completedAt: string | null;
  bytesRead: number | null;
  bytesWritten: number | null;
  errorMessage: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface LocalWorkspaceListResponse {
  workspaces: LocalWorkspaceStateDto[];
}

export interface LocalWorkspaceGetResponse {
  workspace: LocalWorkspaceStateDto | null;
}

export interface LocalContextGetResponse {
  context: LocalContextStateDto | null;
}

export interface LocalContextAppendResponse {
  contextUpdate: LocalContextUpdateDto;
  context: LocalContextStateDto;
  sourceEventSequence: number;
}

export interface LocalAgentRegistrationListResponse {
  agents: LocalAgentRegistrationStateDto[];
}

export interface LocalAgentRegistrationGetResponse {
  agent: LocalAgentRegistrationStateDto | null;
}

export interface LocalAgentRuntimePermissionListResponse {
  runtimePermissions: LocalAgentRuntimePermissionDto[];
}

export interface LocalAgentRuntimePermissionGetResponse {
  runtimePermission: LocalAgentRuntimePermissionDto;
}

export interface LocalConversationCreateResponse {
  conversation: LocalConversationSessionDto;
  created: boolean;
  conversationSourceEventSequence: number;
}

export interface LocalConversationListResponse {
  conversations: LocalConversationSessionDto[];
}

export interface LocalConversationGetResponse {
  conversation: LocalConversationSessionDto | null;
}

export interface LocalConversationArchiveResponse {
  conversation: LocalConversationSessionDto;
  archived: boolean;
  conversationSourceEventSequence: number;
}

export interface LocalConversationMessageAppendResponse {
  message: LocalConversationMessageDto;
  messageSourceEventSequence: number;
}

export interface LocalConversationMessageListResponse {
  conversation: LocalConversationSessionDto;
  messages: LocalConversationMessageDto[];
}

export interface LocalTaskListResponse {
  tasks: LocalTaskStateDto[];
}

export interface LocalTaskGetResponse {
  task: LocalTaskStateDto | null;
}

export interface LocalIssueListResponse {
  issues: LocalIssueStateDto[];
}

export interface LocalIssueGetResponse {
  issue: LocalIssueStateDto | null;
}

export interface LocalAgentInvocationRecordListResponse {
  invocations: LocalAgentInvocationRecordDto[];
}

export interface LocalAgentInvocationRecordGetResponse {
  invocation: LocalAgentInvocationRecordDto | null;
}

export interface LocalFileOperationRecordListResponse {
  fileOperations: LocalFileOperationRecordDto[];
}

export interface LocalFileOperationRecordGetResponse {
  fileOperation: LocalFileOperationRecordDto | null;
}
