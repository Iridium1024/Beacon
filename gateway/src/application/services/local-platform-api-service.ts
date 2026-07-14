import type {
  AgentRuntimeBindingCreateResponse,
  AgentRuntimeBindingListResponse,
  AppendLocalConversationMessageRequest,
  AppendLocalContextUpdateRequest,
  CreateAgentRuntimeBindingRequest,
  CreateLocalConversationRequest,
  CreateLocalAgentRequest,
  CreateLocalWorkspaceRequest,
  CreateProviderConnectionRequest,
  InvokeLocalAgentRequest,
  InvokeLocalAgentResponse,
  ListLocalConversationMessagesRequest,
  LocalAgentRegistrationCreateResponse,
  LocalPlatformApiAdapter,
  LocalWorkspaceArchiveResponse,
  LocalWorkspaceCreateResponse,
  LocalWorkspaceOpenResponse,
  ProviderConnectionCreateResponse,
  ProviderConnectionListResponse,
} from "../dto/local-platform-api-contract.js";
import type {
  LocalAgentInvocationRecordListResponse,
  LocalAgentRegistrationListResponse,
  LocalAgentRuntimePermissionGetResponse,
  LocalAgentRuntimePermissionListResponse,
  LocalConversationArchiveResponse,
  LocalConversationCreateResponse,
  LocalConversationGetResponse,
  LocalConversationListResponse,
  LocalConversationMessageAppendResponse,
  LocalConversationMessageListResponse,
  LocalContextAppendResponse,
  LocalContextGetResponse,
  LocalFileOperationRecordListResponse,
  LocalRunSessionTimelineResponse,
  LocalWorkspaceListResponse,
} from "../dto/local-platform-operation-response.js";

export class LocalPlatformApiNotConnectedError extends Error {
  public constructor(message = "Local platform runtime bridge is not connected.") {
    super(message);
    this.name = "LocalPlatformApiNotConnectedError";
  }
}

export class LocalPlatformApiBridgeError extends Error {
  public constructor(
    public readonly errorType: string,
    message: string,
    public readonly statusCode = 502,
  ) {
    super(sanitizeBridgeErrorMessage(message));
    this.name = "LocalPlatformApiBridgeError";
  }
}

const sanitizeBridgeErrorMessage = (message: string): string => {
  const normalized = message.replace(/\s+/gu, " ").trim();
  if (!normalized) {
    return "Python local runtime bridge failed.";
  }
  if (containsRuntimeInternalDetails(normalized)) {
    return "Python local runtime reported an internal error.";
  }
  return normalized;
};

const containsRuntimeInternalDetails = (message: string): boolean => {
  return [
    /Traceback/iu,
    /File\s+"/u,
    /[A-Za-z]:[\\/][^\s"]*/u,
    /(?:^|\s)\/(?:Users|home|tmp|var|etc|mnt)\//iu,
  ].some((pattern) => pattern.test(message));
};

export class ContractOnlyLocalPlatformApiAdapter implements LocalPlatformApiAdapter {
  public createWorkspace(_request: CreateLocalWorkspaceRequest): Promise<LocalWorkspaceCreateResponse> {
    return this.notConnected();
  }

  public listWorkspaces(): Promise<LocalWorkspaceListResponse> {
    return this.notConnected();
  }

  public openWorkspace(_workspaceId: string): Promise<LocalWorkspaceOpenResponse> {
    return this.notConnected();
  }

  public archiveWorkspace(_workspaceId: string): Promise<LocalWorkspaceArchiveResponse> {
    return this.notConnected();
  }

  public getContext(_workspaceId: string): Promise<LocalContextGetResponse> {
    return this.notConnected();
  }

  public appendContextUpdate(
    _workspaceId: string,
    _request: AppendLocalContextUpdateRequest,
  ): Promise<LocalContextAppendResponse> {
    return this.notConnected();
  }

  public listAgents(_workspaceId: string): Promise<LocalAgentRegistrationListResponse> {
    return this.notConnected();
  }

  public listAgentRuntimePermissions(
    _workspaceId: string,
  ): Promise<LocalAgentRuntimePermissionListResponse> {
    return this.notConnected();
  }

  public getAgentRuntimePermissions(
    _workspaceId: string,
    _agentId: string,
  ): Promise<LocalAgentRuntimePermissionGetResponse> {
    return this.notConnected();
  }

  public createAgent(
    _workspaceId: string,
    _request: CreateLocalAgentRequest,
  ): Promise<LocalAgentRegistrationCreateResponse> {
    return this.notConnected();
  }

  public createConversation(
    _workspaceId: string,
    _request: CreateLocalConversationRequest,
  ): Promise<LocalConversationCreateResponse> {
    return this.notConnected();
  }

  public listConversations(_workspaceId: string): Promise<LocalConversationListResponse> {
    return this.notConnected();
  }

  public getConversation(
    _workspaceId: string,
    _conversationId: string,
  ): Promise<LocalConversationGetResponse> {
    return this.notConnected();
  }

  public archiveConversation(
    _workspaceId: string,
    _conversationId: string,
  ): Promise<LocalConversationArchiveResponse> {
    return this.notConnected();
  }

  public appendConversationMessage(
    _workspaceId: string,
    _conversationId: string,
    _request: AppendLocalConversationMessageRequest,
  ): Promise<LocalConversationMessageAppendResponse> {
    return this.notConnected();
  }

  public listConversationMessages(
    _workspaceId: string,
    _conversationId: string,
    _request?: ListLocalConversationMessagesRequest,
  ): Promise<LocalConversationMessageListResponse> {
    return this.notConnected();
  }

  public invokeAgent(
    _workspaceId: string,
    _request: InvokeLocalAgentRequest,
  ): Promise<InvokeLocalAgentResponse> {
    return this.notConnected();
  }

  public listInvocationRecords(_workspaceId: string): Promise<LocalAgentInvocationRecordListResponse> {
    return this.notConnected();
  }

  public listFileOperationRecords(_workspaceId: string): Promise<LocalFileOperationRecordListResponse> {
    return this.notConnected();
  }

  public getRunSessionTimeline(
    _workspaceId: string,
    _sessionId: string,
  ): Promise<LocalRunSessionTimelineResponse> {
    return this.notConnected();
  }

  public listProviderConnections(): Promise<ProviderConnectionListResponse> {
    return this.notConnected();
  }

  public createProviderConnection(
    _request: CreateProviderConnectionRequest,
  ): Promise<ProviderConnectionCreateResponse> {
    return this.notConnected();
  }

  public listAgentRuntimeBindings(): Promise<AgentRuntimeBindingListResponse> {
    return this.notConnected();
  }

  public createAgentRuntimeBinding(
    _request: CreateAgentRuntimeBindingRequest,
  ): Promise<AgentRuntimeBindingCreateResponse> {
    return this.notConnected();
  }

  private notConnected<T>(): Promise<T> {
    return Promise.reject(new LocalPlatformApiNotConnectedError());
  }
}
