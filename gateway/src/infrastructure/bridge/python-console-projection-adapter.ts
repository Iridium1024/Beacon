import type {
  ConsoleProjectionAdapter,
  ConsoleProviderBackendListResponse,
  ConsoleWorkspaceListResponse,
  ConsoleWorkspaceProjectionRequest,
  ConsoleWorkspaceProjectionResponse,
} from "../../application/dto/console-api-contract.js";
import type { GatewayLocalPlatformBridgeConfig } from "../config/env.js";
import { PythonLocalRuntimeCommandRunner } from "./python-local-platform-api-adapter.js";

/** Python bridge with an intentionally read-only public method set. */
export class PythonConsoleProjectionAdapter implements ConsoleProjectionAdapter {
  private readonly runner: PythonLocalRuntimeCommandRunner;

  public constructor(config: GatewayLocalPlatformBridgeConfig) {
    this.runner = new PythonLocalRuntimeCommandRunner(config);
  }

  public listWorkspaces(): Promise<ConsoleWorkspaceListResponse> {
    return this.runner.run<ConsoleWorkspaceListResponse>([
      "console-workspace-list",
    ]);
  }

  public listProviderBackends(): Promise<ConsoleProviderBackendListResponse> {
    return this.runner.run<ConsoleProviderBackendListResponse>([
      "console-provider-backends",
    ]);
  }

  public getWorkspaceView(
    request: ConsoleWorkspaceProjectionRequest,
  ): Promise<ConsoleWorkspaceProjectionResponse> {
    return this.runner.run<ConsoleWorkspaceProjectionResponse>([
      "console-workspace-view",
      "--workspace-id",
      request.workspaceId,
      ...(request.cursor === undefined ? [] : ["--cursor", request.cursor]),
      ...(request.communicationCursor === undefined ? [] : ["--communication-cursor", request.communicationCursor]),
      ...(request.limit === undefined ? [] : ["--limit", String(request.limit)]),
    ]);
  }
}
