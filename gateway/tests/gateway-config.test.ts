import assert from "node:assert/strict";
import test from "node:test";

import {
  loadGatewayConfig,
  loadGatewayDeferredFeatureConfig,
  loadGatewayLocalApiAccessPolicyConfig,
  loadGatewayLocalPlatformBridgeConfig,
} from "../src/infrastructure/config/env.js";

test("gateway deferred features stay disabled by default", () => {
  const deferredFeatures = loadGatewayDeferredFeatureConfig({});

  assert.equal(deferredFeatures.finiteRoundDiscussion, false);
  assert.equal(deferredFeatures.heartbeat, false);
  assert.equal(deferredFeatures.convergence, false);
  assert.equal(deferredFeatures.schedulerHeartbeatPath, false);
  assert.equal(deferredFeatures.heartbeatTerminalExportConsumer, false);
});

test("gateway deferred features require explicit environment opt-in", () => {
  const deferredFeatures = loadGatewayDeferredFeatureConfig({
    GATEWAY_ENABLE_FINITE_ROUND_DISCUSSION: "true",
    GATEWAY_ENABLE_HEARTBEAT: "1",
    GATEWAY_ENABLE_CONVERGENCE: "yes",
    GATEWAY_ENABLE_SCHEDULER_HEARTBEAT_PATH: "on",
    GATEWAY_ENABLE_HEARTBEAT_TERMINAL_EXPORT_CONSUMER: "false",
  });

  assert.equal(deferredFeatures.finiteRoundDiscussion, true);
  assert.equal(deferredFeatures.heartbeat, true);
  assert.equal(deferredFeatures.convergence, true);
  assert.equal(deferredFeatures.schedulerHeartbeatPath, true);
  assert.equal(deferredFeatures.heartbeatTerminalExportConsumer, false);
});

test("gateway config includes deferred feature boundary", () => {
  const config = loadGatewayConfig({
    GATEWAY_PORT: "3030",
    GATEWAY_ENABLE_HEARTBEAT: "true",
  });

  assert.equal(config.port, 3030);
  assert.equal(config.host, "127.0.0.1");
  assert.equal(config.protocol, "http");
  assert.equal(config.deferredFeatures.heartbeat, true);
  assert.equal(config.deferredFeatures.convergence, false);
});

test("gateway config stays localhost-first and keeps port configurable", () => {
  const defaults = loadGatewayConfig({});
  const configured = loadGatewayConfig({
    GATEWAY_HOST: "127.0.0.1",
    GATEWAY_PORT: "8765",
  });

  assert.equal(defaults.host, "127.0.0.1");
  assert.equal(defaults.port, 3000);
  assert.equal(configured.host, "127.0.0.1");
  assert.equal(configured.port, 8765);
});

test("gateway config rejects non-local API hosts", () => {
  assert.throws(
    () => loadGatewayConfig({ GATEWAY_HOST: "0.0.0.0" }),
    /local-only/,
  );
  assert.throws(
    () => loadGatewayConfig({ GATEWAY_HOST: "192.168.1.20" }),
    /local-only/,
  );
  assert.equal(loadGatewayConfig({ GATEWAY_HOST: "localhost" }).host, "localhost");
  assert.equal(loadGatewayConfig({ GATEWAY_HOST: "::1" }).host, "::1");
});

test("gateway config rejects invalid API ports", () => {
  assert.throws(
    () => loadGatewayConfig({ GATEWAY_PORT: "not-a-port" }),
    /GATEWAY_PORT/,
  );
  assert.throws(
    () => loadGatewayConfig({ GATEWAY_PORT: "3000abc" }),
    /GATEWAY_PORT/,
  );
  assert.throws(
    () => loadGatewayConfig({ GATEWAY_PORT: "70000" }),
    /GATEWAY_PORT/,
  );
  assert.equal(loadGatewayConfig({ GATEWAY_PORT: "0" }).port, 0);
});

test("local API access policy reserves permissions without enabling accounts", () => {
  const policy = loadGatewayLocalApiAccessPolicyConfig({
    LOCAL_API_ACTOR_ID: "local-operator",
    LOCAL_API_ACTOR_DISPLAY_NAME: "Local Operator",
  });

  assert.equal(policy.policyMode, "local_only");
  assert.equal(policy.localOnly, true);
  assert.equal(policy.lanExposureEnabled, false);
  assert.equal(policy.accountSystemEnabled, false);
  assert.equal(policy.actor.actorKind, "local_process");
  assert.equal(policy.actor.actorId, "local-operator");
  assert.equal(policy.actor.displayName, "Local Operator");
  assert.ok(policy.permissionScopes.includes("agent.invoke"));
  assert.ok(policy.permissionScopes.includes("provider_connection.reserve"));
});

test("local platform bridge config defaults to contract-only mode", () => {
  const bridge = loadGatewayLocalPlatformBridgeConfig({}, "win32");

  assert.equal(bridge.mode, "contract_only");
  assert.equal(bridge.pythonCommand, "py");
  assert.deepEqual(bridge.pythonArgs, ["-3.11"]);
  assert.deepEqual(bridge.pythonFallbacks, []);
  assert.equal(bridge.pythonCoreCwd, "../python-core");
  assert.equal(bridge.pythonPath, "src");
  assert.equal(bridge.database, "../runtime/state/local-platform.sqlite3");
  assert.equal(bridge.workspaceRoot, "../workspace/sandboxes/local-platform");
  assert.equal(bridge.pluginsDirectory, "../plugins");
  assert.equal(bridge.timeoutMs, 10000);
  assert.equal(bridge.agentAdapterMode, "deterministic-placeholder");
  assert.equal(bridge.openaiCompatibleApiKeyEnvVar, "AGENT_OS_OPENAI_COMPAT_API_KEY");
  assert.equal(bridge.openaiCompatibleBaseUrl, undefined);
  assert.equal(bridge.openaiCompatibleModel, undefined);
});

test("local platform bridge config resolves POSIX and virtualenv Python candidates", () => {
  const posix = loadGatewayLocalPlatformBridgeConfig({}, "linux");
  const venv = loadGatewayLocalPlatformBridgeConfig(
    { VIRTUAL_ENV: "/tmp/beacon-venv" },
    "linux",
  );

  assert.equal(posix.pythonCommand, "python3.11");
  assert.deepEqual(posix.pythonArgs, []);
  assert.deepEqual(posix.pythonFallbacks, [{ command: "python3", args: [] }]);
  assert.equal(venv.pythonCommand, "/tmp/beacon-venv/bin/python");
  assert.deepEqual(venv.pythonFallbacks, [
    { command: "python3.11", args: [] },
    { command: "python3", args: [] },
  ]);
});

test("local platform bridge config accepts explicit python CLI settings", () => {
  const bridge = loadGatewayLocalPlatformBridgeConfig({
    LOCAL_PLATFORM_BRIDGE_MODE: "python_cli",
    LOCAL_PLATFORM_PYTHON_COMMAND: "C:/Python/python.exe",
    LOCAL_PLATFORM_PYTHON_ARGS: "-X utf8",
    LOCAL_PLATFORM_PYTHON_CORE_CWD: "X:/fixture/project/python-core",
    LOCAL_PLATFORM_PYTHONPATH: "src;extras",
    LOCAL_PLATFORM_DATABASE: "X:/fixture/state/platform.sqlite3",
    LOCAL_PLATFORM_WORKSPACE_ROOT: "X:/fixture/workspace",
    LOCAL_PLATFORM_PLUGINS_DIRECTORY: "X:/fixture/plugins",
    LOCAL_PLATFORM_BRIDGE_TIMEOUT_MS: "15000",
  });

  assert.equal(bridge.mode, "python_cli");
  assert.equal(bridge.pythonCommand, "C:/Python/python.exe");
  assert.deepEqual(bridge.pythonArgs, ["-X", "utf8"]);
  assert.equal(bridge.pythonCoreCwd, "X:/fixture/project/python-core");
  assert.equal(bridge.pythonPath, "src;extras");
  assert.equal(bridge.database, "X:/fixture/state/platform.sqlite3");
  assert.equal(bridge.workspaceRoot, "X:/fixture/workspace");
  assert.equal(bridge.pluginsDirectory, "X:/fixture/plugins");
  assert.equal(bridge.timeoutMs, 15000);
});

test("local platform bridge config accepts OpenAI-compatible provider settings without credential value", () => {
  const bridge = loadGatewayLocalPlatformBridgeConfig({
    LOCAL_PLATFORM_AGENT_ADAPTER_MODE: "openai-compatible-provider",
    AGENT_OS_OPENAI_COMPAT_BASE_URL: "http://127.0.0.1:9999/v1",
    AGENT_OS_OPENAI_COMPAT_MODEL: "fake-chat-model",
    AGENT_OS_OPENAI_COMPAT_PROVIDER_NAME: "test-compatible",
    AGENT_OS_OPENAI_COMPAT_API_KEY_ENV_VAR: "AGENT_OS_OPENAI_COMPAT_TEST_CREDENTIAL",
    AGENT_OS_OPENAI_COMPAT_API_KEY: "must-not-enter-config",
    AGENT_OS_OPENAI_COMPAT_TIMEOUT_SECONDS: "2.5",
    AGENT_OS_OPENAI_COMPAT_TEMPERATURE: "0",
    AGENT_OS_OPENAI_COMPAT_MAX_TOKENS: "32",
  });

  assert.equal(bridge.agentAdapterMode, "openai-compatible-provider");
  assert.equal(bridge.openaiCompatibleBaseUrl, "http://127.0.0.1:9999/v1");
  assert.equal(bridge.openaiCompatibleModel, "fake-chat-model");
  assert.equal(bridge.openaiCompatibleProviderName, "test-compatible");
  assert.equal(
    bridge.openaiCompatibleApiKeyEnvVar,
    "AGENT_OS_OPENAI_COMPAT_TEST_CREDENTIAL",
  );
  assert.equal(bridge.openaiCompatibleTimeoutSeconds, 2.5);
  assert.equal(bridge.openaiCompatibleTemperature, 0);
  assert.equal(bridge.openaiCompatibleMaxTokens, 32);
  assert.equal(
    Object.values(bridge).includes("must-not-enter-config"),
    false,
  );
});

test("local platform bridge config accepts provider API shape settings without credential value", () => {
  const bridge = loadGatewayLocalPlatformBridgeConfig({
    LOCAL_PLATFORM_AGENT_ADAPTER_MODE: "provider-api-shape",
    AGENT_OS_PROVIDER_API_SHAPE: "openai-responses",
    AGENT_OS_PROVIDER_BASE_URL: "http://127.0.0.1:9999/v1",
    AGENT_OS_PROVIDER_MODEL: "fake-responses-model",
    AGENT_OS_PROVIDER_NAME: "fake-openai-responses",
    AGENT_OS_PROVIDER_API_KEY_ENV_VAR: "AGENT_OS_PROVIDER_TEST_CREDENTIAL",
    AGENT_OS_PROVIDER_API_KEY: "must-not-enter-config",
    AGENT_OS_PROVIDER_TIMEOUT_SECONDS: "3.5",
    AGENT_OS_PROVIDER_TEMPERATURE: "0",
    AGENT_OS_PROVIDER_MAX_TOKENS: "48",
    AGENT_OS_PROVIDER_REASONING_EFFORT: "low",
    AGENT_OS_PROVIDER_THINKING_TYPE: "disabled",
    AGENT_OS_PROVIDER_INPUT_MODE: "plain-text",
    AGENT_OS_PROVIDER_USER_AGENT: "AgentChatGateway/14.2",
  });

  assert.equal(bridge.agentAdapterMode, "provider-api-shape");
  assert.equal(bridge.providerApiShape, "openai-responses");
  assert.equal(bridge.providerBaseUrl, "http://127.0.0.1:9999/v1");
  assert.equal(bridge.providerModel, "fake-responses-model");
  assert.equal(bridge.providerName, "fake-openai-responses");
  assert.equal(bridge.providerApiKeyEnvVar, "AGENT_OS_PROVIDER_TEST_CREDENTIAL");
  assert.equal(bridge.providerTimeoutSeconds, 3.5);
  assert.equal(bridge.providerTemperature, 0);
  assert.equal(bridge.providerMaxTokens, 48);
  assert.equal(bridge.providerReasoningEffort, "low");
  assert.equal(bridge.providerThinkingType, "disabled");
  assert.equal(bridge.providerInputMode, "plain_text");
  assert.equal(bridge.providerUserAgent, "AgentChatGateway/14.2");
  assert.equal(
    Object.values(bridge).includes("must-not-enter-config"),
    false,
  );
});

test("local platform bridge config allowlists executable provider API shapes", () => {
  const shapes = [
    "openai-chat-completions",
    "openai-responses",
    "anthropic-messages",
    "gemini-generate-content",
    "ollama-chat",
  ] as const;

  for (const shape of shapes) {
    const bridge = loadGatewayLocalPlatformBridgeConfig({
      LOCAL_PLATFORM_AGENT_ADAPTER_MODE: "provider-api-shape",
      AGENT_OS_PROVIDER_API_SHAPE: shape,
    });

    assert.equal(bridge.providerApiShape, shape);
  }
});

test("local platform bridge config rejects unknown provider API shapes", () => {
  assert.throws(
    () => loadGatewayLocalPlatformBridgeConfig({
      LOCAL_PLATFORM_AGENT_ADAPTER_MODE: "provider-api-shape",
      AGENT_OS_PROVIDER_API_SHAPE: "azure-openai",
    }),
    /AGENT_OS_PROVIDER_API_SHAPE/,
  );
});

test("local platform bridge config rejects unknown bridge mode", () => {
  assert.throws(
    () => loadGatewayLocalPlatformBridgeConfig({ LOCAL_PLATFORM_BRIDGE_MODE: "remote" }),
    /LOCAL_PLATFORM_BRIDGE_MODE/,
  );
});

test("local platform bridge config rejects unsafe provider mode settings", () => {
  assert.throws(
    () => loadGatewayLocalPlatformBridgeConfig({
      LOCAL_PLATFORM_AGENT_ADAPTER_MODE: "remote-provider",
    }),
    /LOCAL_PLATFORM_AGENT_ADAPTER_MODE/,
  );
  assert.throws(
    () => loadGatewayLocalPlatformBridgeConfig({
      AGENT_OS_OPENAI_COMPAT_API_KEY_ENV_VAR: "not-loud-enough",
    }),
    /AGENT_OS_OPENAI_COMPAT_API_KEY_ENV_VAR/,
  );
  assert.throws(
    () => loadGatewayLocalPlatformBridgeConfig({
      AGENT_OS_PROVIDER_API_KEY_ENV_VAR: "not-loud-enough",
    }),
    /AGENT_OS_PROVIDER_API_KEY_ENV_VAR/,
  );
  assert.throws(
    () => loadGatewayLocalPlatformBridgeConfig({
      AGENT_OS_OPENAI_COMPAT_MAX_TOKENS: "0",
    }),
    /AGENT_OS_OPENAI_COMPAT_MAX_TOKENS/,
  );
  assert.throws(
    () => loadGatewayLocalPlatformBridgeConfig({
      AGENT_OS_PROVIDER_INPUT_MODE: "relay-auto",
    }),
    /AGENT_OS_PROVIDER_INPUT_MODE/,
  );
  assert.throws(
    () => loadGatewayLocalPlatformBridgeConfig({
      AGENT_OS_PROVIDER_USER_AGENT: "AgentChat\r\nCookie: leaked",
    }),
    /AGENT_OS_PROVIDER_USER_AGENT/,
  );
  assert.throws(
    () => loadGatewayLocalPlatformBridgeConfig({
      AGENT_OS_PROVIDER_USER_AGENT: "x".repeat(257),
    }),
    /AGENT_OS_PROVIDER_USER_AGENT/,
  );
});
