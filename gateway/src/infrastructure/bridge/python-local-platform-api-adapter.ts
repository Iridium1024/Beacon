import { execFile } from "node:child_process";
import { promisify } from "node:util";

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
  LocalPlatformApiCallContext,
  LocalWorkspaceArchiveResponse,
  LocalWorkspaceCreateResponse,
  LocalWorkspaceOpenResponse,
  ProviderConnectionCreateResponse,
  ProviderConnectionListResponse,
} from "../../application/dto/local-platform-api-contract.js";
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
} from "../../application/dto/local-platform-operation-response.js";
import { LocalPlatformApiBridgeError } from "../../application/services/local-platform-api-service.js";
import type {
  GatewayLocalPlatformBridgeConfig,
  GatewayPythonInvocation,
} from "../config/env.js";

const execFileAsync = promisify(execFile);

type CliFailure = Error & {
  code?: number | string;
  killed?: boolean;
  signal?: NodeJS.Signals;
  stdout?: string | Buffer;
  stderr?: string | Buffer;
};

export class PythonLocalPlatformApiAdapter implements LocalPlatformApiAdapter {
  private selectedPython?: Promise<GatewayPythonInvocation>;

  public constructor(private readonly config: GatewayLocalPlatformBridgeConfig) {}

  public async createWorkspace(
    request: CreateLocalWorkspaceRequest,
    _context?: LocalPlatformApiCallContext,
  ): Promise<LocalWorkspaceCreateResponse> {
    rejectUnsupported(request.metadata, "workspace metadata");
    return this.run<LocalWorkspaceCreateResponse>([
      "workspace-create",
      "--display-name",
      request.displayName,
      ...optionalArg("--workspace-id", request.workspaceId),
      ...optionalArg("--context-id", request.contextId),
      ...optionalArg("--agent-id", request.agentId),
      ...optionalArg("--root-path", request.rootPath),
    ]);
  }

  public async listWorkspaces(
    _context?: LocalPlatformApiCallContext,
  ): Promise<LocalWorkspaceListResponse> {
    return this.run<LocalWorkspaceListResponse>(["workspace-list"]);
  }

  public async openWorkspace(
    workspaceId: string,
    _context?: LocalPlatformApiCallContext,
  ): Promise<LocalWorkspaceOpenResponse> {
    return this.run<LocalWorkspaceOpenResponse>([
      "workspace-open",
      "--workspace-id",
      workspaceId,
    ]);
  }

  public async archiveWorkspace(
    workspaceId: string,
    _context?: LocalPlatformApiCallContext,
  ): Promise<LocalWorkspaceArchiveResponse> {
    return this.run<LocalWorkspaceArchiveResponse>([
      "workspace-archive",
      "--workspace-id",
      workspaceId,
    ]);
  }

  public async getContext(
    workspaceId: string,
    _context?: LocalPlatformApiCallContext,
  ): Promise<LocalContextGetResponse> {
    return this.run<LocalContextGetResponse>([
      "context-get",
      "--workspace-id",
      workspaceId,
    ]);
  }

  public async appendContextUpdate(
    workspaceId: string,
    request: AppendLocalContextUpdateRequest,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalContextAppendResponse> {
    rejectUnsupported(request.sourceAgentId, "context update sourceAgentId");
    rejectUnsupported(request.metadata, "context update metadata");
    return this.run<LocalContextAppendResponse>([
      "context-append",
      "--workspace-id",
      workspaceId,
      "--summary",
      request.summary,
      "--update-kind",
      request.updateKind ?? "note",
      ...optionalArg("--update-id", request.updateId),
      ...optionalJsonArg("--payload-json", request.payload),
      ...optionalJsonArg("--patch-json", request.materializedStatePatch),
      ...optionalArg("--session-id", request.sessionId ?? context?.sessionId),
    ]);
  }

  public async listAgents(
    workspaceId: string,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalAgentRegistrationListResponse> {
    const opened = await this.openWorkspace(workspaceId, context);
    return { agents: opened.agents };
  }

  public async listAgentRuntimePermissions(
    workspaceId: string,
    _context?: LocalPlatformApiCallContext,
  ): Promise<LocalAgentRuntimePermissionListResponse> {
    return this.run<LocalAgentRuntimePermissionListResponse>([
      "agent-runtime-permissions",
      "--workspace-id",
      workspaceId,
    ]);
  }

  public async getAgentRuntimePermissions(
    workspaceId: string,
    agentId: string,
    _context?: LocalPlatformApiCallContext,
  ): Promise<LocalAgentRuntimePermissionGetResponse> {
    return this.run<LocalAgentRuntimePermissionGetResponse>([
      "agent-runtime-permission-get",
      "--workspace-id",
      workspaceId,
      "--agent-id",
      agentId,
    ]);
  }

  public async createAgent(
    workspaceId: string,
    request: CreateLocalAgentRequest,
    _context?: LocalPlatformApiCallContext,
  ): Promise<LocalAgentRegistrationCreateResponse> {
    return this.run<LocalAgentRegistrationCreateResponse>([
      "agent-create",
      "--workspace-id",
      workspaceId,
      "--name",
      request.name,
      "--description",
      request.description,
      ...optionalArg("--agent-id", request.agentId),
      ...optionalArg("--default-model", request.defaultModel),
      ...optionalJsonArg("--capabilities-json", request.capabilities),
      ...optionalJsonArg("--tool-permissions-json", request.toolPermissions),
      ...optionalJsonArg("--runtime-config-json", request.runtimeConfig),
      ...optionalJsonArg("--metadata-json", request.metadata),
    ]);
  }

  public async createConversation(
    workspaceId: string,
    request: CreateLocalConversationRequest,
    _context?: LocalPlatformApiCallContext,
  ): Promise<LocalConversationCreateResponse> {
    return this.run<LocalConversationCreateResponse>([
      "conversation-create",
      "--workspace-id",
      workspaceId,
      "--title",
      request.title,
      ...optionalArg("--conversation-id", request.conversationId),
      ...optionalArg("--agent-id", request.agentId),
      ...optionalJsonArg("--metadata-json", request.metadata),
    ]);
  }

  public async listConversations(
    workspaceId: string,
    _context?: LocalPlatformApiCallContext,
  ): Promise<LocalConversationListResponse> {
    return this.run<LocalConversationListResponse>([
      "conversation-list",
      "--workspace-id",
      workspaceId,
    ]);
  }

  public async getConversation(
    workspaceId: string,
    conversationId: string,
    _context?: LocalPlatformApiCallContext,
  ): Promise<LocalConversationGetResponse> {
    return this.run<LocalConversationGetResponse>([
      "conversation-get",
      "--workspace-id",
      workspaceId,
      "--conversation-id",
      conversationId,
    ]);
  }

  public async archiveConversation(
    workspaceId: string,
    conversationId: string,
    _context?: LocalPlatformApiCallContext,
  ): Promise<LocalConversationArchiveResponse> {
    return this.run<LocalConversationArchiveResponse>([
      "conversation-archive",
      "--workspace-id",
      workspaceId,
      "--conversation-id",
      conversationId,
    ]);
  }

  public async appendConversationMessage(
    workspaceId: string,
    conversationId: string,
    request: AppendLocalConversationMessageRequest,
    context?: LocalPlatformApiCallContext,
  ): Promise<LocalConversationMessageAppendResponse> {
    return this.run<LocalConversationMessageAppendResponse>([
      "conversation-message-append",
      "--workspace-id",
      workspaceId,
      "--conversation-id",
      conversationId,
      "--role",
      request.role,
      "--content",
      request.content,
      ...optionalArg("--message-id", request.messageId),
      ...optionalArg("--agent-id", request.agentId),
      ...optionalArg("--invocation-id", request.invocationId),
      ...optionalArg("--context-update-id", request.contextUpdateId),
      ...optionalArg("--run-session-id", request.runSessionId ?? context?.sessionId),
      ...optionalJsonArg("--metadata-json", request.metadata),
    ]);
  }

  public async listConversationMessages(
    workspaceId: string,
    conversationId: string,
    request: ListLocalConversationMessagesRequest = {},
    _context?: LocalPlatformApiCallContext,
  ): Promise<LocalConversationMessageListResponse> {
    return this.run<LocalConversationMessageListResponse>([
      "conversation-messages",
      "--workspace-id",
      workspaceId,
      "--conversation-id",
      conversationId,
      ...optionalNumberArg("--limit", request.limit),
      ...optionalNumberArg("--offset", request.offset),
    ]);
  }

  public async invokeAgent(
    workspaceId: string,
    request: InvokeLocalAgentRequest,
    context?: LocalPlatformApiCallContext,
  ): Promise<InvokeLocalAgentResponse> {
    const payload: InvokeLocalAgentRequest = {
      ...request,
      workspaceId,
      sessionId: request.sessionId ?? context?.sessionId,
      correlationId: request.correlationId ?? context?.correlationId,
    };
    return this.run<InvokeLocalAgentResponse>([
      "invoke-json",
      "--payload-json",
      JSON.stringify(payload),
    ]);
  }

  public async listInvocationRecords(
    workspaceId: string,
    _context?: LocalPlatformApiCallContext,
  ): Promise<LocalAgentInvocationRecordListResponse> {
    return this.run<LocalAgentInvocationRecordListResponse>([
      "records-invocations",
      "--workspace-id",
      workspaceId,
    ]);
  }

  public async listFileOperationRecords(
    workspaceId: string,
    _context?: LocalPlatformApiCallContext,
  ): Promise<LocalFileOperationRecordListResponse> {
    return this.run<LocalFileOperationRecordListResponse>([
      "records-file-operations",
      "--workspace-id",
      workspaceId,
    ]);
  }

  public async getRunSessionTimeline(
    workspaceId: string,
    sessionId: string,
    _context?: LocalPlatformApiCallContext,
  ): Promise<LocalRunSessionTimelineResponse> {
    return this.run<LocalRunSessionTimelineResponse>([
      "session-timeline",
      "--workspace-id",
      workspaceId,
      "--session-id",
      sessionId,
    ]);
  }

  public async listProviderConnections(
    _context?: LocalPlatformApiCallContext,
  ): Promise<ProviderConnectionListResponse> {
    return { connections: [] };
  }

  public async createProviderConnection(
    request: CreateProviderConnectionRequest,
    _context?: LocalPlatformApiCallContext,
  ): Promise<ProviderConnectionCreateResponse> {
    return {
      created: false,
      connection: {
        connectionId: request.connectionId ?? "connection-not-connected",
        providerKind: request.providerKind,
        accountAlias: request.accountAlias ?? null,
        displayName: request.displayName ?? null,
        authMode: request.authMode,
        status: "not_connected",
        metadata: request.metadata ?? {},
      },
    };
  }

  public async listAgentRuntimeBindings(
    _context?: LocalPlatformApiCallContext,
  ): Promise<AgentRuntimeBindingListResponse> {
    return { bindings: [] };
  }

  public async createAgentRuntimeBinding(
    request: CreateAgentRuntimeBindingRequest,
    _context?: LocalPlatformApiCallContext,
  ): Promise<AgentRuntimeBindingCreateResponse> {
    return {
      created: false,
      binding: {
        bindingId: request.bindingId ?? "binding-not-connected",
        agentId: request.agentId,
        connectionId: request.connectionId ?? null,
        runtimeKind: request.runtimeKind,
        remoteInstanceId: request.remoteInstanceId ?? null,
        capabilities: request.capabilities ?? [],
        status: "not_connected",
        metadata: request.metadata ?? {},
      },
    };
  }

  private async run<TResponse extends object>(commandArgs: string[]): Promise<TResponse> {
    const python = await this.pythonInvocation();
    const args = [
      ...python.args,
      "-m",
      "agent_os.local_runtime",
      "--database",
      this.config.database,
      "--workspace-root",
      this.config.workspaceRoot,
      "--plugins-directory",
      this.config.pluginsDirectory,
      ...providerBridgeArgs(this.config),
      ...commandArgs,
    ];

    try {
      const { stdout } = await execFileAsync(python.command, args, {
        cwd: this.config.pythonCoreCwd,
        env: childEnvironment(this.config),
        encoding: "utf8",
        maxBuffer: 10 * 1024 * 1024,
        timeout: this.config.timeoutMs,
        windowsHide: true,
      });
      return parseJsonResponse<TResponse>(String(stdout));
    } catch (error) {
      throw bridgeError(error);
    }
  }

  private async pythonInvocation(): Promise<GatewayPythonInvocation> {
    if (this.config.skipPythonPreflight === true) {
      return {
        command: this.config.pythonCommand,
        args: [...this.config.pythonArgs],
      };
    }
    this.selectedPython ??= selectSupportedPython(this.config);
    return this.selectedPython;
  }
}

const selectSupportedPython = async (
  config: GatewayLocalPlatformBridgeConfig,
): Promise<GatewayPythonInvocation> => {
  const candidates = [
    { command: config.pythonCommand, args: [...config.pythonArgs] },
    ...(config.pythonFallbacks ?? []).map((candidate) => ({
      command: candidate.command,
      args: [...candidate.args],
    })),
  ];
  for (const candidate of candidates) {
    try {
      const { stdout } = await execFileAsync(
        candidate.command,
        [
          ...candidate.args,
          "-c",
          "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')",
        ],
        {
          cwd: config.pythonCoreCwd,
          env: childEnvironment(config),
          encoding: "utf8",
          timeout: Math.min(config.timeoutMs, 5000),
          windowsHide: true,
        },
      );
      const match = /^(\d+)\.(\d+)\.(\d+)/u.exec(String(stdout).trim());
      if (
        match !== null
        && (Number(match[1]) > 3 || (Number(match[1]) === 3 && Number(match[2]) >= 11))
      ) {
        return candidate;
      }
    } catch (_error) {
      continue;
    }
  }
  throw new LocalPlatformApiBridgeError(
    "python_runtime_unavailable",
    "Gateway requires Python 3.11 or newer. Set LOCAL_PLATFORM_PYTHON_COMMAND to a supported interpreter.",
    503,
  );
};

const optionalArg = (name: string, value: string | undefined): string[] => {
  return value === undefined ? [] : [name, value];
};

const optionalJsonArg = (
  name: string,
  value: unknown | undefined,
): string[] => {
  return value === undefined ? [] : [name, JSON.stringify(value)];
};

const optionalNumberArg = (
  name: string,
  value: number | undefined,
): string[] => {
  return value === undefined ? [] : [name, String(value)];
};

const providerBridgeArgs = (
  config: GatewayLocalPlatformBridgeConfig,
): string[] => {
  const baseArgs = [
    "--agent-adapter-mode",
    config.agentAdapterMode,
  ];
  if (config.agentAdapterMode === "openai-compatible-provider") {
    return [
      ...baseArgs,
      ...optionalArg("--openai-compatible-base-url", config.openaiCompatibleBaseUrl),
      ...optionalArg("--openai-compatible-model", config.openaiCompatibleModel),
      ...optionalArg(
        "--openai-compatible-provider-name",
        config.openaiCompatibleProviderName,
      ),
      "--openai-compatible-api-key-env-var",
      config.openaiCompatibleApiKeyEnvVar,
      ...optionalNumberArg(
        "--openai-compatible-timeout-seconds",
        config.openaiCompatibleTimeoutSeconds,
      ),
      ...optionalNumberArg(
        "--openai-compatible-temperature",
        config.openaiCompatibleTemperature,
      ),
      ...optionalNumberArg(
        "--openai-compatible-max-tokens",
        config.openaiCompatibleMaxTokens,
      ),
    ];
  }
  if (config.agentAdapterMode === "provider-api-shape") {
    return [
      ...baseArgs,
      ...optionalArg("--provider-api-shape", config.providerApiShape),
      ...optionalArg("--provider-base-url", config.providerBaseUrl),
      ...optionalArg("--provider-model", config.providerModel),
      ...optionalArg("--provider-name", config.providerName),
      ...optionalArg("--provider-api-key-env-var", config.providerApiKeyEnvVar),
      ...optionalNumberArg(
        "--provider-timeout-seconds",
        config.providerTimeoutSeconds,
      ),
      ...optionalNumberArg("--provider-temperature", config.providerTemperature),
      ...optionalNumberArg("--provider-max-tokens", config.providerMaxTokens),
      ...optionalArg("--provider-reasoning-effort", config.providerReasoningEffort),
      ...optionalArg("--provider-thinking-type", config.providerThinkingType),
      ...optionalArg("--provider-input-mode", config.providerInputMode),
      ...optionalArg("--provider-user-agent", config.providerUserAgent),
    ];
  }
  return baseArgs;
};

const rejectUnsupported = (value: unknown, fieldName: string): void => {
  if (value !== undefined) {
    throw new LocalPlatformApiBridgeError(
      "unsupported_bridge_request",
      `${fieldName} is not supported by the Python CLI bridge yet.`,
      400,
    );
  }
};

const parseJsonResponse = <TResponse extends object>(stdout: string): TResponse => {
  const payload = stdout.trim();
  if (!payload) {
    throw new LocalPlatformApiBridgeError(
      "invalid_bridge_response",
      "Python local runtime returned an empty response.",
    );
  }
  try {
    return JSON.parse(payload) as TResponse;
  } catch (_error) {
    throw new LocalPlatformApiBridgeError(
      "invalid_bridge_response",
      "Python local runtime returned invalid JSON.",
    );
  }
};

const bridgeError = (error: unknown): LocalPlatformApiBridgeError => {
  if (error instanceof LocalPlatformApiBridgeError) {
    return error;
  }
  const failure = error as CliFailure;
  if (failure.killed || failure.signal === "SIGTERM") {
    return new LocalPlatformApiBridgeError(
      "bridge_timeout",
      "Python local runtime bridge timed out.",
      504,
    );
  }
  const stderr = bufferText(failure.stderr).trim();
  const parsed = parsePythonError(stderr);
  if (parsed !== undefined) {
    return parsed;
  }
  return new LocalPlatformApiBridgeError(
    "bridge_process_error",
    "Python local runtime bridge process failed.",
  );
};

const parsePythonError = (stderr: string): LocalPlatformApiBridgeError | undefined => {
  if (!stderr) {
    return undefined;
  }
  try {
    const payload = JSON.parse(stderr) as {
      ok?: boolean;
      error?: {
        type?: unknown;
        message?: unknown;
      };
    };
    if (payload.ok === false && typeof payload.error?.message === "string") {
      return new LocalPlatformApiBridgeError(
        "python_runtime_error",
        payload.error.message,
        502,
      );
    }
  } catch (_error) {
    return undefined;
  }
  return undefined;
};

const bufferText = (value: string | Buffer | undefined): string => {
  if (value === undefined) {
    return "";
  }
  return typeof value === "string" ? value : value.toString("utf8");
};

const childEnvironment = (
  config: GatewayLocalPlatformBridgeConfig,
): NodeJS.ProcessEnv => {
  const env: NodeJS.ProcessEnv = {
    PYTHONPATH: config.pythonPath,
  };
  copyEnv(env, "PATH");
  copyEnv(env, "Path");
  copyEnv(env, "PATHEXT");
  copyEnv(env, "SYSTEMROOT");
  copyEnv(env, "SystemRoot");
  copyEnv(env, "TEMP");
  copyEnv(env, "TMP");
  if (config.agentAdapterMode === "openai-compatible-provider") {
    copyEnv(env, config.openaiCompatibleApiKeyEnvVar);
  }
  if (
    config.agentAdapterMode === "provider-api-shape"
    && config.providerApiKeyEnvVar !== undefined
  ) {
    copyEnv(env, config.providerApiKeyEnvVar);
  }
  return env;
};

const copyEnv = (target: NodeJS.ProcessEnv, key: string): void => {
  const value = process.env[key];
  if (value !== undefined) {
    target[key] = value;
  }
};
