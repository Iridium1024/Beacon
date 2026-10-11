import type {
  ConsoleProjectionAdapter,
  ConsoleProviderBackendListResponse,
  ConsoleWorkspaceListResponse,
  ConsoleWorkspaceProjectionRequest,
  ConsoleWorkspaceProjectionResponse,
} from "../dto/console-api-contract.js";
import { LocalPlatformApiNotConnectedError } from "./local-platform-api-service.js";

export class ConsoleProjectionService implements ConsoleProjectionAdapter {
  public constructor(private readonly adapter: ConsoleProjectionAdapter) {}

  public listWorkspaces(): Promise<ConsoleWorkspaceListResponse> {
    return this.adapter.listWorkspaces();
  }

  public listProviderBackends(): Promise<ConsoleProviderBackendListResponse> {
    return this.adapter.listProviderBackends();
  }

  public getWorkspaceView(
    request: ConsoleWorkspaceProjectionRequest,
  ): Promise<ConsoleWorkspaceProjectionResponse> {
    return this.adapter.getWorkspaceView(request);
  }
}

export class DisconnectedConsoleProjectionAdapter implements ConsoleProjectionAdapter {
  public listWorkspaces(): Promise<ConsoleWorkspaceListResponse> {
    return Promise.reject(new LocalPlatformApiNotConnectedError());
  }

  public listProviderBackends(): Promise<ConsoleProviderBackendListResponse> {
    return Promise.reject(new LocalPlatformApiNotConnectedError());
  }

  public getWorkspaceView(
    _request: ConsoleWorkspaceProjectionRequest,
  ): Promise<ConsoleWorkspaceProjectionResponse> {
    return Promise.reject(new LocalPlatformApiNotConnectedError());
  }
}

