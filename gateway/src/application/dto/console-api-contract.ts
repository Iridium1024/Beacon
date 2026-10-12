export const CONSOLE_SCHEMA = "beacon.console.v1" as const;
export const CONSOLE_SCHEMA_MAJOR = 1 as const;
export const CONSOLE_HEALTH_SCHEMA = "beacon.console.health.v1" as const;
export const CONSOLE_API_VERSION = "1.0" as const;
export const CONSOLE_TIMELINE_MAX_LIMIT = 200 as const;

export interface ConsoleGatewayHealthResponse {
  schema: typeof CONSOLE_HEALTH_SCHEMA;
  schemaMajor: typeof CONSOLE_SCHEMA_MAJOR;
  consoleSchema: typeof CONSOLE_SCHEMA;
  apiVersion: typeof CONSOLE_API_VERSION;
  status: "ready";
  authority: "beacon";
  source: "gateway";
  readOnly: true;
}

export interface ExtensibleEnum<TKnown extends string> {
  value: TKnown | "unknown";
  rawValue: string;
  known: boolean;
}

export interface ConsoleWorkspaceView {
  schema: "console_workspace_view.v1";
  workspaceId: string;
  displayName: string;
  rootSummary: string | null;
  status: ExtensibleEnum<"active" | "archived">;
  updatedAt: string | null;
  sourceEventSequence: number | null;
}

export interface ConsoleAgentView {
  schema: "console_agent_view.v1";
  workspaceId: string;
  agentId: string;
  displayName: string;
  status: ExtensibleEnum<"active" | "inactive" | "archived">;
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
  state: ExtensibleEnum<
    "active" | "inactive" | "continuity_lost" | "completed" | "failed"
  >;
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
  canSend: boolean;
  canResume: boolean;
  canReadStatus: boolean;
  canReadOwnedLiveStatus: boolean;
  canSupplementActiveTurn: boolean;
  canCancel: boolean;
  canHandleApprovalRequests: boolean;
  canReadHistory: boolean;
  canCaptureFinalMessage: boolean;
  canResumeAcrossProcess: boolean;
  canOwnRuntime: boolean;
  canManageMultipleThreads: boolean;
}

export interface ProviderBackendView {
  schema: "provider_backend_view.v1";
  provider: string;
  backendId: string;
  officialInterface: string;
  beaconImplementation: string;
  lifecycle: ExtensibleEnum<"short_lived_operation" | "managed_runtime">;
  runtimeOwnership: ExtensibleEnum<"none" | "operation_owned" | "persistent_owned">;
  statusAuthority: ExtensibleEnum<"unsupported" | "snapshot" | "point_read" | "owned_live">;
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
  status: ExtensibleEnum<
    | "queued"
    | "leased"
    | "running"
    | "waiting_response"
    | "completed"
    | "failed"
    | "cancelled"
    | "expired"
    | "dry_run"
  >;
  apiLayer: "delivery-oriented";
  updatedAt: string | null;
}

export interface ConsoleTimelineEvent {
  schema: "console_timeline_event.v1";
  eventId: string;
  workspaceOrdinal: number;
  sourceEventSequence: number;
  occurredAt: string;
  category: ExtensibleEnum<
    "identity" | "session" | "dispatch" | "runtime" | "lifecycle" | "workspace"
  >;
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

export interface ConsoleWorkspaceListResponse {
  schema: typeof CONSOLE_SCHEMA;
  schemaMajor: typeof CONSOLE_SCHEMA_MAJOR;
  authority: "beacon";
  displayShell: "beacon_read_only_projection";
  readOnly: true;
  items: ConsoleWorkspaceView[];
  count: number;
  sort: "displayName_asc_workspaceId_asc";
}

export interface ConsoleProviderBackendListResponse {
  schema: typeof CONSOLE_SCHEMA;
  schemaMajor: typeof CONSOLE_SCHEMA_MAJOR;
  authority: "beacon";
  readOnly: true;
  items: ProviderBackendView[];
  count: number;
  sort: "backendId_asc";
}

export interface ConsoleWorkspaceProjectionResponse {
  schema: typeof CONSOLE_SCHEMA;
  schemaMajor: typeof CONSOLE_SCHEMA_MAJOR;
  authority: "beacon";
  displayShell: "beacon_read_only_projection";
  readOnly: true;
  workspace: ConsoleWorkspaceView;
  agents: ConsoleAgentView[];
  sessions: ForeignSessionRef[];
  providerBackends: ProviderBackendView[];
  dispatches: DispatchProjection[];
  timeline: ConsoleTimelinePage;
  communicationLedger?: {
    schema: "console_communication_page.v1";
    cursor: string | null;
    events: Array<{
      communicationLedgerSequence: number;
      kind: string;
      occurredAt: string;
      messageCount: number;
      receiptKinds: string[];
    }>;
    nextCursor: string;
    hasMore: boolean;
    upper: number;
  };
  limitations: string[];
}

export interface ConsoleWorkspaceProjectionRequest {
  workspaceId: string;
  cursor?: string;
  communicationCursor?: string;
  limit?: number;
}

/** Structurally read-only: no mutation method is part of this port. */
export interface ConsoleProjectionAdapter {
  listWorkspaces(): Promise<ConsoleWorkspaceListResponse>;
  listProviderBackends(): Promise<ConsoleProviderBackendListResponse>;
  getWorkspaceView(
    request: ConsoleWorkspaceProjectionRequest,
  ): Promise<ConsoleWorkspaceProjectionResponse>;
}
