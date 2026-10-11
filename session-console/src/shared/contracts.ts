export interface ExtensibleEnum {
  value: string;
  rawValue: string;
  known: boolean;
}

export interface ConsoleWorkspaceView {
  schema: "console_workspace_view.v1";
  workspaceId: string;
  displayName: string;
  rootSummary: string | null;
  status: ExtensibleEnum;
  updatedAt: string | null;
  sourceEventSequence: number | null;
}

export interface ConsoleAgentView {
  schema: "console_agent_view.v1";
  workspaceId: string;
  agentId: string;
  displayName: string;
  status: ExtensibleEnum;
  capabilityNames: string[];
  sourceEventSequence: number | null;
}

export type ConsoleProvider =
  | "claude"
  | "codex"
  | "hermes"
  | "deepseek_harness";

export interface ForeignSessionRef {
  schema: "foreign_session_ref.v1";
  identity: {
    provider: ConsoleProvider;
    nativeSessionId: string;
  };
  workspaceId: string;
  agentId: string;
  handleId: string;
  state: ExtensibleEnum;
  cwdSummary: string | null;
  updatedAt: string | null;
  sourceEventSequence: number | null;
  nativeDshSession: boolean;
  foreignProjectionOnly: boolean;
  continuity: {
    scope: string;
    state: string;
    resumeAcrossRuntimeRestart: boolean | null;
  };
}

export interface ProviderCapabilities {
  canSend: boolean | null;
  canResume: boolean | null;
  canReadStatus: boolean | null;
  canReadOwnedLiveStatus: boolean | null;
  canSupplementActiveTurn: boolean | null;
  canCancel: boolean | null;
  canHandleApprovalRequests: boolean | null;
  canReadHistory: boolean | null;
  canCaptureFinalMessage: boolean | null;
  canResumeAcrossProcess: boolean | null;
  canOwnRuntime: boolean | null;
  canManageMultipleThreads: boolean | null;
}

export interface ProviderBackendView {
  schema: "provider_backend_view.v1";
  provider: string;
  backendId: string;
  officialInterface: string;
  beaconImplementation: string;
  lifecycle: ExtensibleEnum;
  runtimeOwnership: ExtensibleEnum;
  statusAuthority: ExtensibleEnum;
  capabilities: ProviderCapabilities;
  continuityScope: string | null;
  canResumeAcrossRuntimeRestart: boolean | null;
  maxConcurrentOperations: number | null;
  existingSessionImport: boolean | null;
}

export interface DispatchProjection {
  schema: "dispatch_projection.v1";
  workspaceId: string;
  dispatchId: string;
  exchangeRequestId: string;
  sourceAgentId: string;
  targetAgentId: string;
  targetProvider: string | null;
  targetHandleId: string | null;
  status: ExtensibleEnum;
  apiLayer: "delivery-oriented";
  updatedAt: string | null;
}

export interface ConsoleTimelineEvent {
  schema: "console_timeline_event.v1";
  eventId: string;
  workspaceOrdinal: number;
  sourceEventSequence: number;
  occurredAt: string;
  category: ExtensibleEnum;
  eventKind: string;
  aggregateType: string;
  aggregateId: string;
  summary: string;
  presentationNodeKey: string;
}

export interface ConsoleTimelinePage {
  schema: "console_timeline_page.v1";
  events: ConsoleTimelineEvent[];
  page: {
    cursor: string | null;
    nextCursor: string;
    limit: number;
    returned: number;
    total: number;
    hasMore: boolean;
    truncated: boolean;
    cursorOutOfRange: boolean;
    rebuildRequired: boolean;
  };
  replay: {
    order: "workspaceOrdinal_asc_eventId_asc";
    duplicateEventIdPolicy: "first_sequence_wins";
    reconnect: "resume_from_nextCursor_or_rebuild_on_token_change";
    rebuildToken: string;
    deterministicRebuild: true;
    polling: "bounded_get_polling_no_stream_claim";
  };
}

export interface ConsoleGatewayHealthResponse {
  schema: "beacon.console.health.v1";
  schemaMajor: 1;
  consoleSchema: "beacon.console.v1";
  apiVersion: "1.0";
  status: "ready";
  authority: "beacon";
  source: "gateway" | "synthetic";
  readOnly: true;
}

export interface ConsoleWorkspaceListResponse {
  schema: "beacon.console.v1";
  schemaMajor: 1;
  authority: "beacon";
  displayShell: "beacon_read_only_projection";
  readOnly: true;
  items: ConsoleWorkspaceView[];
  count: number;
  sort: "displayName_asc_workspaceId_asc";
}

export interface ConsoleProviderBackendListResponse {
  schema: "beacon.console.v1";
  schemaMajor: 1;
  authority: "beacon";
  readOnly: true;
  items: ProviderBackendView[];
  count: number;
  sort: "backendId_asc";
}

export interface ConsoleWorkspaceProjectionResponse {
  schema: "beacon.console.v1";
  schemaMajor: 1;
  authority: "beacon";
  displayShell: "beacon_read_only_projection";
  readOnly: true;
  workspace: ConsoleWorkspaceView;
  agents: ConsoleAgentView[];
  sessions: ForeignSessionRef[];
  providerBackends: ProviderBackendView[];
  dispatches: DispatchProjection[];
  timeline: ConsoleTimelinePage;
  limitations: string[];
}

export interface ConsoleErrorResponse {
  schema: "beacon.console.error.v1";
  readOnly: true;
  error: { code: string; message: string };
}
