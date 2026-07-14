import { DefaultGatewayService } from "./application/services/gateway-service.js";
import { ContractOnlyLocalPlatformApiAdapter } from "./application/services/local-platform-api-service.js";
import { PlaceholderHealthService } from "./application/services/health-service.js";
import type { GatewayConfig } from "./infrastructure/config/env.js";
import type { LocalPlatformApiAdapter } from "./application/dto/local-platform-api-contract.js";
import { PythonCoreClient } from "./infrastructure/bridge/python-core-client.js";
import { PythonLocalPlatformApiAdapter } from "./infrastructure/bridge/python-local-platform-api-adapter.js";
import { loadGatewayConfig } from "./infrastructure/config/env.js";
import { createAgentsRoute } from "./infrastructure/http/routes/agent-route.js";
import { createHealthRoute } from "./infrastructure/http/routes/health-route.js";
import { createModelsRoute } from "./infrastructure/http/routes/models-route.js";
import { createLocalPlatformApiRoutes } from "./infrastructure/http/routes/local-platform-route.js";
import { createSingleTurnPlatformInvocationRoute } from "./infrastructure/http/routes/platform-invocation-route.js";
import { createTaskRoute } from "./infrastructure/http/routes/task-route.js";
import { createHttpServer, type HttpServer } from "./infrastructure/http/server.js";
import { HttpEnvelopeProtocol } from "./infrastructure/protocols/http-envelope-protocol.js";

export interface GatewayRuntime {
  readonly config: GatewayConfig;
  readonly server: HttpServer;
}

export const buildGateway = async (): Promise<GatewayRuntime> => {
  const config = loadGatewayConfig();
  const protocol = new HttpEnvelopeProtocol();
  const runtimeClient = new PythonCoreClient(protocol, config.runtimeEndpoint);
  const gatewayService = new DefaultGatewayService(runtimeClient);
  const localPlatformApiAdapter = createLocalPlatformApiAdapter(config);
  const healthService = new PlaceholderHealthService();
  const server = createHttpServer(config.host, config.port);

  await server.registerRoute(createHealthRoute(healthService));
  await server.registerRoute(createTaskRoute(gatewayService));
  await server.registerRoute(createAgentsRoute(gatewayService));
  await server.registerRoute(createModelsRoute(gatewayService));
  await server.registerRoute(createSingleTurnPlatformInvocationRoute(gatewayService));
  for (const route of createLocalPlatformApiRoutes(localPlatformApiAdapter, {
    platformRuntimeWired: config.localPlatformBridge.mode === "python_cli" ? "true" : "contract_only",
    accessPolicy: config.localApiAccessPolicy,
  })) {
    await server.registerRoute(route);
  }

  return {
    config,
    server,
  };
};

const createLocalPlatformApiAdapter = (config: GatewayConfig): LocalPlatformApiAdapter => {
  if (config.localPlatformBridge.mode === "python_cli") {
    return new PythonLocalPlatformApiAdapter(config.localPlatformBridge);
  }
  return new ContractOnlyLocalPlatformApiAdapter();
};
