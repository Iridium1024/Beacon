import { posix, win32 } from "node:path";

export interface GatewayDeferredFeatureConfig {
  finiteRoundDiscussion: boolean;
  heartbeat: boolean;
  convergence: boolean;
  schedulerHeartbeatPath: boolean;
  heartbeatTerminalExportConsumer: boolean;
}

export type LocalPlatformBridgeMode = "contract_only" | "python_cli";

export type LocalPlatformAgentAdapterMode =
  | "deterministic-placeholder"
  | "deterministic-provider"
  | "openai-compatible-provider"
  | "provider-api-shape";

export type GatewayProviderApiShape =
  | "openai-chat-completions"
  | "openai-responses"
  | "anthropic-messages"
  | "gemini-generate-content"
  | "ollama-chat";

export type GatewayProviderInputMode =
  | "structured_messages"
  | "plain_text";

export interface GatewayLocalPlatformBridgeConfig {
  mode: LocalPlatformBridgeMode;
  pythonCommand: string;
  pythonArgs: string[];
  pythonFallbacks?: GatewayPythonInvocation[];
  skipPythonPreflight?: boolean;
  pythonCoreCwd: string;
  pythonPath: string;
  database: string;
  workspaceRoot: string;
  pluginsDirectory: string;
  timeoutMs: number;
  agentAdapterMode: LocalPlatformAgentAdapterMode;
  openaiCompatibleBaseUrl?: string;
  openaiCompatibleModel?: string;
  openaiCompatibleProviderName?: string;
  openaiCompatibleApiKeyEnvVar: string;
  openaiCompatibleTimeoutSeconds?: number;
  openaiCompatibleTemperature?: number;
  openaiCompatibleMaxTokens?: number;
  providerApiShape?: GatewayProviderApiShape;
  providerBaseUrl?: string;
  providerModel?: string;
  providerName?: string;
  providerApiKeyEnvVar?: string;
  providerTimeoutSeconds?: number;
  providerTemperature?: number;
  providerMaxTokens?: number;
  providerReasoningEffort?: string;
  providerThinkingType?: string;
  providerInputMode?: GatewayProviderInputMode;
  providerUserAgent?: string;
}

export interface GatewayPythonInvocation {
  command: string;
  args: string[];
}

export type GatewayLocalApiPermissionScope =
  | "workspace.read"
  | "workspace.write"
  | "context.read"
  | "context.append"
  | "agent.read"
  | "agent.invoke"
  | "records.read"
  | "provider_connection.reserve"
  | "agent_binding.reserve";

export interface GatewayLocalApiAccessPolicyConfig {
  policyMode: "local_only";
  localOnly: true;
  lanExposureEnabled: false;
  accountSystemEnabled: false;
  actor: {
    actorKind: "local_process";
    actorId: string;
    displayName?: string;
  };
  permissionScopes: GatewayLocalApiPermissionScope[];
}

export interface GatewayConfig {
  port: number;
  host: string;
  runtimeEndpoint: string;
  protocol: "json-rpc" | "http" | "stdio";
  pluginDirectory: string;
  deferredFeatures: GatewayDeferredFeatureConfig;
  localPlatformBridge: GatewayLocalPlatformBridgeConfig;
  localApiAccessPolicy: GatewayLocalApiAccessPolicyConfig;
}

const parseBooleanEnv = (value: string | undefined): boolean => {
  if (value === undefined) {
    return false;
  }

  return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
};

export const loadGatewayDeferredFeatureConfig = (
  env: NodeJS.ProcessEnv = process.env,
): GatewayDeferredFeatureConfig => {
  return {
    finiteRoundDiscussion: parseBooleanEnv(env.GATEWAY_ENABLE_FINITE_ROUND_DISCUSSION),
    heartbeat: parseBooleanEnv(env.GATEWAY_ENABLE_HEARTBEAT),
    convergence: parseBooleanEnv(env.GATEWAY_ENABLE_CONVERGENCE),
    schedulerHeartbeatPath: parseBooleanEnv(env.GATEWAY_ENABLE_SCHEDULER_HEARTBEAT_PATH),
    heartbeatTerminalExportConsumer: parseBooleanEnv(
      env.GATEWAY_ENABLE_HEARTBEAT_TERMINAL_EXPORT_CONSUMER,
    ),
  };
};

const parseLocalPlatformBridgeMode = (
  value: string | undefined,
): LocalPlatformBridgeMode => {
  const normalized = value?.trim() || "contract_only";
  if (normalized === "contract_only" || normalized === "python_cli") {
    return normalized;
  }
  throw new Error(
    "LOCAL_PLATFORM_BRIDGE_MODE must be either 'contract_only' or 'python_cli'.",
  );
};

const parseLocalPlatformAgentAdapterMode = (
  value: string | undefined,
): LocalPlatformAgentAdapterMode => {
  const normalized = value?.trim() || "deterministic-placeholder";
  if (
    normalized === "deterministic-placeholder"
    || normalized === "deterministic-provider"
    || normalized === "openai-compatible-provider"
    || normalized === "provider-api-shape"
  ) {
    return normalized;
  }
  throw new Error(
    "LOCAL_PLATFORM_AGENT_ADAPTER_MODE must be one of: deterministic-placeholder, deterministic-provider, openai-compatible-provider, provider-api-shape.",
  );
};

const parseCommandArgs = (value: string | undefined): string[] => {
  if (value === undefined || value.trim() === "") {
    return [];
  }
  return value.trim().split(/\s+/u);
};

const parsePositiveInteger = (
  value: string | undefined,
  defaultValue: number,
): number => {
  if (value === undefined || value.trim() === "") {
    return defaultValue;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : defaultValue;
};

const optionalPositiveNumber = (
  value: string | undefined,
  name: string,
): number | undefined => {
  if (value === undefined || value.trim() === "") {
    return undefined;
  }
  const parsed = Number(value);
  if (Number.isFinite(parsed) && parsed > 0) {
    return parsed;
  }
  throw new Error(`${name} must be a positive number.`);
};

const optionalNonNegativeNumber = (
  value: string | undefined,
  name: string,
): number | undefined => {
  if (value === undefined || value.trim() === "") {
    return undefined;
  }
  const parsed = Number(value);
  if (Number.isFinite(parsed) && parsed >= 0) {
    return parsed;
  }
  throw new Error(`${name} must be a non-negative number.`);
};

const optionalInteger = (
  value: string | undefined,
  name: string,
): number | undefined => {
  if (value === undefined || value.trim() === "") {
    return undefined;
  }
  if (!/^\d+$/u.test(value.trim())) {
    throw new Error(`${name} must be an integer.`);
  }
  const parsed = Number.parseInt(value, 10);
  if (parsed > 0) {
    return parsed;
  }
  throw new Error(`${name} must be a positive integer.`);
};

const optionalText = (value: string | undefined): string | undefined => {
  const normalized = value?.trim();
  return normalized ? normalized : undefined;
};

const envVarName = (
  value: string | undefined,
  defaultValue: string,
  name: string,
): string => {
  const normalized = optionalText(value) ?? defaultValue;
  if (/^[A-Z_][A-Z0-9_]*$/u.test(normalized)) {
    return normalized;
  }
  throw new Error(
    `${name} must be an uppercase environment variable name.`,
  );
};

const providerApiShapes = new Set<GatewayProviderApiShape>([
  "openai-chat-completions",
  "openai-responses",
  "anthropic-messages",
  "gemini-generate-content",
  "ollama-chat",
]);

const parseProviderApiShape = (
  value: string | undefined,
): GatewayProviderApiShape | undefined => {
  const normalized = optionalText(value);
  if (normalized === undefined) {
    return undefined;
  }
  if (providerApiShapes.has(normalized as GatewayProviderApiShape)) {
    return normalized as GatewayProviderApiShape;
  }
  throw new Error(
    "AGENT_OS_PROVIDER_API_SHAPE must be one of: openai-chat-completions, openai-responses, anthropic-messages, gemini-generate-content, ollama-chat.",
  );
};

const parseProviderInputMode = (
  value: string | undefined,
): GatewayProviderInputMode | undefined => {
  const normalized = optionalText(value)?.replace(/-/gu, "_");
  if (normalized === undefined) {
    return undefined;
  }
  if (normalized === "structured_messages" || normalized === "plain_text") {
    return normalized;
  }
  throw new Error(
    "AGENT_OS_PROVIDER_INPUT_MODE must be one of: structured_messages, plain_text.",
  );
};

const parseProviderUserAgent = (
  value: string | undefined,
): string | undefined => {
  const normalized = optionalText(value);
  if (normalized === undefined) {
    return undefined;
  }
  if (/[\r\n]/u.test(normalized)) {
    throw new Error("AGENT_OS_PROVIDER_USER_AGENT must not contain CR or LF.");
  }
  if (normalized.length > 256) {
    throw new Error(
      "AGENT_OS_PROVIDER_USER_AGENT must be 256 characters or fewer.",
    );
  }
  return normalized;
};

const defaultProviderApiKeyEnvVar = (
  shape: GatewayProviderApiShape | undefined,
): string | undefined => {
  if (shape === undefined || shape === "ollama-chat") {
    return undefined;
  }
  if (shape === "openai-chat-completions") {
    return "AGENT_OS_OPENAI_COMPAT_API_KEY";
  }
  if (shape === "openai-responses") {
    return "AGENT_OS_OPENAI_RESPONSES_API_KEY";
  }
  if (shape === "anthropic-messages") {
    return "AGENT_OS_ANTHROPIC_API_KEY";
  }
  if (shape === "gemini-generate-content") {
    return "AGENT_OS_GEMINI_API_KEY";
  }
  return "AGENT_OS_PROVIDER_API_KEY";
};

const providerApiKeyEnvVar = (
  value: string | undefined,
  shape: GatewayProviderApiShape | undefined,
): string | undefined => {
  const defaultValue = defaultProviderApiKeyEnvVar(shape);
  if (defaultValue === undefined && optionalText(value) === undefined) {
    return undefined;
  }
  return envVarName(
    value,
    defaultValue ?? "AGENT_OS_PROVIDER_API_KEY",
    "AGENT_OS_PROVIDER_API_KEY_ENV_VAR",
  );
};

const localOnlyHosts = new Set(["127.0.0.1", "localhost", "::1"]);

const parseGatewayHost = (value: string | undefined): string => {
  const normalized = value?.trim() || "127.0.0.1";
  if (localOnlyHosts.has(normalized)) {
    return normalized;
  }
  throw new Error(
    "GATEWAY_HOST must remain local-only. Allowed values: 127.0.0.1, localhost, ::1.",
  );
};

const parseGatewayPort = (value: string | undefined): number => {
  const normalized = value?.trim() || "3000";
  if (!/^\d+$/u.test(normalized)) {
    throw new Error("GATEWAY_PORT must be an integer between 0 and 65535.");
  }
  const parsed = Number.parseInt(normalized, 10);
  if (Number.isFinite(parsed) && parsed >= 0 && parsed <= 65535) {
    return parsed;
  }
  throw new Error("GATEWAY_PORT must be an integer between 0 and 65535.");
};

const defaultLocalApiPermissionScopes: GatewayLocalApiPermissionScope[] = [
  "workspace.read",
  "workspace.write",
  "context.read",
  "context.append",
  "agent.read",
  "agent.invoke",
  "records.read",
  "provider_connection.reserve",
  "agent_binding.reserve",
];

export const loadGatewayLocalApiAccessPolicyConfig = (
  env: NodeJS.ProcessEnv = process.env,
): GatewayLocalApiAccessPolicyConfig => {
  const actorId = env.LOCAL_API_ACTOR_ID?.trim() || "local-process";
  const displayName = env.LOCAL_API_ACTOR_DISPLAY_NAME?.trim();
  return {
    policyMode: "local_only",
    localOnly: true,
    lanExposureEnabled: false,
    accountSystemEnabled: false,
    actor: {
      actorKind: "local_process",
      actorId,
      ...(displayName ? { displayName } : {}),
    },
    permissionScopes: [...defaultLocalApiPermissionScopes],
  };
};

export const loadGatewayLocalPlatformBridgeConfig = (
  env: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
): GatewayLocalPlatformBridgeConfig => {
  const hasExplicitPythonCommand = env.LOCAL_PLATFORM_PYTHON_COMMAND !== undefined;
  const pythonInvocations = resolveGatewayPythonInvocations(env, platform);
  const providerApiShape = parseProviderApiShape(env.AGENT_OS_PROVIDER_API_SHAPE);
  return {
    mode: parseLocalPlatformBridgeMode(env.LOCAL_PLATFORM_BRIDGE_MODE),
    pythonCommand: pythonInvocations[0].command,
    pythonArgs: parseCommandArgs(
      env.LOCAL_PLATFORM_PYTHON_ARGS
        ?? (hasExplicitPythonCommand ? "" : pythonInvocations[0].args.join(" ")),
    ),
    pythonFallbacks: hasExplicitPythonCommand ? [] : pythonInvocations.slice(1),
    pythonCoreCwd: env.LOCAL_PLATFORM_PYTHON_CORE_CWD ?? "../python-core",
    pythonPath: env.LOCAL_PLATFORM_PYTHONPATH ?? "src",
    database: env.LOCAL_PLATFORM_DATABASE ?? "../runtime/state/local-platform.sqlite3",
    workspaceRoot: env.LOCAL_PLATFORM_WORKSPACE_ROOT ?? "../workspace/sandboxes/local-platform",
    pluginsDirectory: env.LOCAL_PLATFORM_PLUGINS_DIRECTORY ?? "../plugins",
    timeoutMs: parsePositiveInteger(env.LOCAL_PLATFORM_BRIDGE_TIMEOUT_MS, 10000),
    agentAdapterMode: parseLocalPlatformAgentAdapterMode(
      env.LOCAL_PLATFORM_AGENT_ADAPTER_MODE,
    ),
    openaiCompatibleBaseUrl: optionalText(env.AGENT_OS_OPENAI_COMPAT_BASE_URL),
    openaiCompatibleModel: optionalText(env.AGENT_OS_OPENAI_COMPAT_MODEL),
    openaiCompatibleProviderName: optionalText(
      env.AGENT_OS_OPENAI_COMPAT_PROVIDER_NAME,
    ),
    openaiCompatibleApiKeyEnvVar: envVarName(
      env.AGENT_OS_OPENAI_COMPAT_API_KEY_ENV_VAR,
      "AGENT_OS_OPENAI_COMPAT_API_KEY",
      "AGENT_OS_OPENAI_COMPAT_API_KEY_ENV_VAR",
    ),
    openaiCompatibleTimeoutSeconds: optionalPositiveNumber(
      env.AGENT_OS_OPENAI_COMPAT_TIMEOUT_SECONDS,
      "AGENT_OS_OPENAI_COMPAT_TIMEOUT_SECONDS",
    ),
    openaiCompatibleTemperature: optionalNonNegativeNumber(
      env.AGENT_OS_OPENAI_COMPAT_TEMPERATURE,
      "AGENT_OS_OPENAI_COMPAT_TEMPERATURE",
    ),
    openaiCompatibleMaxTokens: optionalInteger(
      env.AGENT_OS_OPENAI_COMPAT_MAX_TOKENS,
      "AGENT_OS_OPENAI_COMPAT_MAX_TOKENS",
    ),
    providerApiShape,
    providerBaseUrl: optionalText(env.AGENT_OS_PROVIDER_BASE_URL),
    providerModel: optionalText(env.AGENT_OS_PROVIDER_MODEL),
    providerName: optionalText(env.AGENT_OS_PROVIDER_NAME),
    providerApiKeyEnvVar: providerApiKeyEnvVar(
      env.AGENT_OS_PROVIDER_API_KEY_ENV_VAR,
      providerApiShape,
    ),
    providerTimeoutSeconds: optionalPositiveNumber(
      env.AGENT_OS_PROVIDER_TIMEOUT_SECONDS,
      "AGENT_OS_PROVIDER_TIMEOUT_SECONDS",
    ),
    providerTemperature: optionalNonNegativeNumber(
      env.AGENT_OS_PROVIDER_TEMPERATURE,
      "AGENT_OS_PROVIDER_TEMPERATURE",
    ),
    providerMaxTokens: optionalInteger(
      env.AGENT_OS_PROVIDER_MAX_TOKENS,
      "AGENT_OS_PROVIDER_MAX_TOKENS",
    ),
    providerReasoningEffort: optionalText(env.AGENT_OS_PROVIDER_REASONING_EFFORT),
    providerThinkingType: optionalText(env.AGENT_OS_PROVIDER_THINKING_TYPE),
    providerInputMode: parseProviderInputMode(env.AGENT_OS_PROVIDER_INPUT_MODE),
    providerUserAgent: parseProviderUserAgent(env.AGENT_OS_PROVIDER_USER_AGENT),
  };
};

export const resolveGatewayPythonInvocations = (
  env: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
): GatewayPythonInvocation[] => {
  const explicit = optionalText(env.LOCAL_PLATFORM_PYTHON_COMMAND);
  if (explicit !== undefined) {
    return [{ command: explicit, args: parseCommandArgs(env.LOCAL_PLATFORM_PYTHON_ARGS) }];
  }

  const fallbacks: GatewayPythonInvocation[] = platform === "win32"
    ? [{ command: "py", args: ["-3.11"] }]
    : [
      { command: "python3.11", args: [] },
      { command: "python3", args: [] },
    ];
  const virtualEnvironment = optionalText(env.VIRTUAL_ENV);
  if (virtualEnvironment === undefined) {
    return fallbacks;
  }
  const virtualEnvironmentPython = platform === "win32"
    ? win32.join(virtualEnvironment, "Scripts", "python.exe")
    : posix.join(virtualEnvironment, "bin", "python");
  return [
    { command: virtualEnvironmentPython, args: [] },
    ...fallbacks,
  ];
};

export const loadGatewayConfig = (
  env: NodeJS.ProcessEnv = process.env,
): GatewayConfig => {
  return {
    port: parseGatewayPort(env.GATEWAY_PORT),
    host: parseGatewayHost(env.GATEWAY_HOST),
    runtimeEndpoint: env.PYTHON_ORCHESTRATOR_ENDPOINT ?? "http://127.0.0.1:8000/runtime",
    protocol: (env.PYTHON_ORCHESTRATOR_PROTOCOL as GatewayConfig["protocol"] | undefined) ?? "http",
    pluginDirectory: env.GATEWAY_PLUGIN_DIRECTORY ?? "./plugins",
    deferredFeatures: loadGatewayDeferredFeatureConfig(env),
    localPlatformBridge: loadGatewayLocalPlatformBridgeConfig(env),
    localApiAccessPolicy: loadGatewayLocalApiAccessPolicyConfig(env),
  };
};
