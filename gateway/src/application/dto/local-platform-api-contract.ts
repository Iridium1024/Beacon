import type {
  SingleTurnPlatformInvocationRequest,
  SingleTurnPlatformInvocationResponse,
} from "./platform-invocation-request.js";
import type {
  LocalAgentRegistrationStateDto,
  LocalAgentRuntimePermissionGetResponse,
  LocalAgentRuntimePermissionListResponse,
  LocalAgentInvocationRecordListResponse,
  LocalConversationArchiveResponse,
  LocalConversationCreateResponse,
  LocalConversationGetResponse,
  LocalConversationListResponse,
  LocalConversationMessageAppendResponse,
  LocalConversationMessageListResponse,
  LocalConversationMessageRole,
  LocalContextAppendResponse,
  LocalContextGetResponse,
  LocalContextStateDto,
  LocalFileOperationRecordListResponse,
  LocalIssueStateDto,
  LocalPlatformOperationMetadata,
  LocalRunSessionTimelineResponse,
  LocalTaskStateDto,
  LocalWorkspaceListResponse,
  LocalWorkspaceStateDto,
} from "./local-platform-operation-response.js";

export type LocalPlatformApiMetadata = Record<string, unknown>;

export interface LocalPlatformRouteMetadata extends LocalPlatformApiMetadata {
  routeStatus: "ok" | "not_connected" | "invalid_request" | "failed";
  platformRuntimeWired: "false" | "contract_only" | "true";
  sessionId: string;
  correlationId: string;
  localApiPolicy: "local_only";
  actorKind: "local_process";
  permissionScopes: LocalPlatformApiPermissionScope[];
}

export interface LocalPlatformRouteResponse<TPayload extends object> {
  ok: boolean;
  payload: TPayload;
  metadata: LocalPlatformRouteMetadata;
}

export interface LocalPlatformApiCallContext {
  sessionId: string;
  correlationId: string;
  actor: LocalPlatformApiActorContext;
  accessPolicy: LocalPlatformApiAccessPolicy;
  metadata?: LocalPlatformApiMetadata;
}

export type LocalPlatformApiPermissionScope =
  | "workspace.read"
  | "workspace.write"
  | "context.read"
  | "context.append"
  | "agent.read"
  | "agent.write"
  | "agent.invoke"
  | "runtime_permission.read"
  | "conversation.read"
  | "conversation.write"
  | "records.read"
  | "provider_connection.reserve"
  | "agent_binding.reserve";

export interface LocalPlatformApiActorContext {
  actorKind: "local_process";
  actorId: string;
  displayName?: string;
}

export interface LocalPlatformApiAccessPolicy {
  policyMode: "local_only";
  localOnly: true;
  lanExposureEnabled: false;
  accountSystemEnabled: false;
  actor: LocalPlatformApiActorContext;
  permissionScopes: LocalPlatformApiPermissionScope[];
}

export interface LocalPlatformErrorPayload {
  error: {
    type: string;
    message: string;
  };
}

export interface LocalWorkspaceOverviewDto {
  workspace: LocalWorkspaceStateDto;
  context: LocalContextStateDto | null;
  agents: LocalAgentRegistrationStateDto[];
  tasks: LocalTaskStateDto[];
  issues: LocalIssueStateDto[];
}

export interface LocalWorkspaceBaselineDto {
  workspaceId: string;
  contextCreated: boolean;
  agentCreated: boolean;
  context: LocalContextStateDto | null;
  agents: LocalAgentRegistrationStateDto[];
}

export interface CreateLocalWorkspaceRequest {
  workspaceId?: string;
  contextId?: string;
  agentId?: string;
  displayName: string;
  rootPath?: string;
  metadata?: LocalPlatformOperationMetadata;
}

export interface LocalWorkspaceCreateResponse {
  workspace: LocalWorkspaceOverviewDto;
  created: boolean;
  workspaceSourceEventSequence: number;
  baseline: LocalWorkspaceBaselineDto;
}

export interface LocalWorkspaceOpenResponse extends LocalWorkspaceOverviewDto {}

export interface LocalWorkspaceArchiveResponse {
  workspace: LocalWorkspaceOverviewDto;
  archived: boolean;
  workspaceSourceEventSequence: number;
}

export interface CreateLocalAgentRequest {
  agentId?: string;
  name: string;
  description: string;
  defaultModel?: string;
  capabilities?: LocalPlatformOperationMetadata[];
  toolPermissions?: string[];
  runtimeConfig?: LocalPlatformOperationMetadata;
  metadata?: LocalPlatformOperationMetadata;
}

export interface LocalAgentRegistrationCreateResponse {
  agent: LocalAgentRegistrationStateDto;
  created: boolean;
  agentSourceEventSequence: number;
}

export interface AppendLocalContextUpdateRequest {
  updateKind?: "user_message" | "agent_message" | "file_reference" | "tool_result" | "decision" | "note" | "artifact";
  summary: string;
  updateId?: string;
  sourceAgentId?: string;
  payload?: LocalPlatformOperationMetadata;
  materializedStatePatch?: LocalPlatformOperationMetadata;
  metadata?: LocalPlatformOperationMetadata;
  sessionId?: string;
}

export interface CreateLocalConversationRequest {
  conversationId?: string;
  agentId?: string;
  title: string;
  metadata?: LocalPlatformOperationMetadata;
}

export interface AppendLocalConversationMessageRequest {
  messageId?: string;
  role: LocalConversationMessageRole;
  content: string;
  agentId?: string;
  invocationId?: string;
  contextUpdateId?: string;
  runSessionId?: string;
  metadata?: LocalPlatformOperationMetadata;
}

export interface ListLocalConversationMessagesRequest {
  limit?: number;
  offset?: number;
}

export type InvokeLocalAgentRequest = SingleTurnPlatformInvocationRequest;
export type InvokeLocalAgentResponse = SingleTurnPlatformInvocationResponse;

export type ProviderConnectionKind =
  | "deterministic"
  | "openai_compatible"
  | "local_model"
  | "remote_http"
  | "remote_conversation"
  | "custom";

export type ProviderConnectionAuthMode =
  | "none"
  | "managed_credential"
  | "oauth"
  | "local_session"
  | "external_connector";

export type ProviderConnectionStatus =
  | "not_connected"
  | "connected"
  | "disabled"
  | "error";

export interface ProviderConnectionDto {
  connectionId: string;
  providerKind: ProviderConnectionKind;
  accountAlias?: string | null;
  displayName?: string | null;
  authMode: ProviderConnectionAuthMode;
  status: ProviderConnectionStatus;
  metadata: LocalPlatformOperationMetadata;
}

export interface CreateProviderConnectionRequest {
  connectionId?: string;
  providerKind: ProviderConnectionKind;
  accountAlias?: string;
  displayName?: string;
  authMode: ProviderConnectionAuthMode;
  metadata?: LocalPlatformOperationMetadata;
}

export interface ProviderConnectionListResponse {
  connections: ProviderConnectionDto[];
}

export interface ProviderConnectionCreateResponse {
  connection: ProviderConnectionDto;
  created: boolean;
}

export type AgentRuntimeKind =
  | "deterministic_placeholder"
  | "provider_connection"
  | "remote_conversation_instance"
  | "external_connector";

export type AgentRuntimeBindingStatus =
  | "not_connected"
  | "active"
  | "disabled"
  | "error";

export interface AgentRuntimeBindingDto {
  bindingId: string;
  agentId: string;
  connectionId?: string | null;
  runtimeKind: AgentRuntimeKind;
  remoteInstanceId?: string | null;
  capabilities: string[];
  status: AgentRuntimeBindingStatus;
  metadata: LocalPlatformOperationMetadata;
}

export interface CreateAgentRuntimeBindingRequest {
  bindingId?: string;
  agentId: string;
  connectionId?: string;
  runtimeKind: AgentRuntimeKind;
  remoteInstanceId?: string;
  capabilities?: string[];
  metadata?: LocalPlatformOperationMetadata;
}

export interface AgentRuntimeBindingListResponse {
  bindings: AgentRuntimeBindingDto[];
}

export interface AgentRuntimeBindingCreateResponse {
  binding: AgentRuntimeBindingDto;
  created: boolean;
}

export interface LocalPlatformApiAdapter {
  createWorkspace(
    request: CreateLocalWorkspaceRequest,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalWorkspaceCreateResponse>;
  listWorkspaces(context?: LocalPlatformApiCallContext): Promise<LocalWorkspaceListResponse>;
  openWorkspace(
    workspaceId: string,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalWorkspaceOpenResponse>;
  archiveWorkspace(
    workspaceId: string,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalWorkspaceArchiveResponse>;
  getContext(
    workspaceId: string,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalContextGetResponse>;
  appendContextUpdate(
    workspaceId: string,
    request: AppendLocalContextUpdateRequest,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalContextAppendResponse>;
  listAgents(
    workspaceId: string,
    context?: LocalPlatformApiCallContext,
  ): Promise<{ agents: LocalAgentRegistrationStateDto[] }>;
  listAgentRuntimePermissions(
    workspaceId: string,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalAgentRuntimePermissionListResponse>;
  getAgentRuntimePermissions(
    workspaceId: string,
    agentId: string,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalAgentRuntimePermissionGetResponse>;
  createAgent(
    workspaceId: string,
    request: CreateLocalAgentRequest,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalAgentRegistrationCreateResponse>;
  createConversation(
    workspaceId: string,
    request: CreateLocalConversationRequest,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalConversationCreateResponse>;
  listConversations(
    workspaceId: string,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalConversationListResponse>;
  getConversation(
    workspaceId: string,
    conversationId: string,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalConversationGetResponse>;
  archiveConversation(
    workspaceId: string,
    conversationId: string,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalConversationArchiveResponse>;
  appendConversationMessage(
    workspaceId: string,
    conversationId: string,
    request: AppendLocalConversationMessageRequest,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalConversationMessageAppendResponse>;
  listConversationMessages(
    workspaceId: string,
    conversationId: string,
    request?: ListLocalConversationMessagesRequest,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalConversationMessageListResponse>;
  invokeAgent(
    workspaceId: string,
    request: InvokeLocalAgentRequest,
    context?: LocalPlatformApiCallContext,
  ): Promise<InvokeLocalAgentResponse>;
  listInvocationRecords(
    workspaceId: string,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalAgentInvocationRecordListResponse>;
  listFileOperationRecords(
    workspaceId: string,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalFileOperationRecordListResponse>;
  getRunSessionTimeline(
    workspaceId: string,
    sessionId: string,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalRunSessionTimelineResponse>;
  listProviderConnections(
    context?: LocalPlatformApiCallContext,
  ): Promise<ProviderConnectionListResponse>;
  createProviderConnection(
    request: CreateProviderConnectionRequest,
    context?: LocalPlatformApiCallContext,
  ): Promise<ProviderConnectionCreateResponse>;
  listAgentRuntimeBindings(
    context?: LocalPlatformApiCallContext,
  ): Promise<AgentRuntimeBindingListResponse>;
  createAgentRuntimeBinding(
    request: CreateAgentRuntimeBindingRequest,
    context?: LocalPlatformApiCallContext,
  ): Promise<AgentRuntimeBindingCreateResponse>;
}
