import { useSyncExternalStore } from "react";

import type {
  ConsoleGatewayHealthResponse,
  ConsoleProvider,
  ConsoleProviderBackendListResponse,
  ConsoleWorkspaceListResponse,
  ConsoleWorkspaceProjectionResponse,
} from "../shared/contracts.js";
import {
  ConsoleProtocolError,
  MAX_RESPONSE_BYTES,
  mergeTimeline,
  parseGatewayHealth,
  parseProviderBackends,
  parseWorkspaceList,
  parseWorkspaceProjection,
  rebuildTimeline,
  type TimelineAccumulator,
} from "../shared/protocol.js";

const POLL_INTERVAL_MS = 15_000;
const DEFAULT_REQUEST_TIMEOUT_MS = 5_000;

export type ConsoleConnectionState =
  | "idle"
  | "loading"
  | "ready"
  | "disconnected"
  | "permission"
  | "protocol"
  | "version"
  | "timeout"
  | "error";

export type AppearanceMode = "system" | "light" | "dark";

export interface ConsoleState {
  connection: ConsoleConnectionState;
  connectionMessage: string | null;
  health: ConsoleGatewayHealthResponse | null;
  workspaces: ConsoleWorkspaceListResponse | null;
  backends: ConsoleProviderBackendListResponse | null;
  view: ConsoleWorkspaceProjectionResponse | null;
  timeline: TimelineAccumulator | null;
  selectedWorkspaceId: string | null;
  selectedProvider: ConsoleProvider | "all";
  selectedSessionKey: string | null;
  sessionSelectionExplicitlyCleared: boolean;
  appearance: AppearanceMode;
  resolvedTheme: "light" | "dark";
  highContrast: boolean;
  lastRefreshedAt: string | null;
  refreshing: boolean;
}

export interface ConsoleProjectionDataSource {
  checkHealth(): Promise<ConsoleGatewayHealthResponse>;
  listWorkspaces(): Promise<ConsoleWorkspaceListResponse>;
  listProviderBackends(): Promise<ConsoleProviderBackendListResponse>;
  getWorkspaceView(
    workspaceId: string,
    cursor?: string,
    limit?: number,
  ): Promise<ConsoleWorkspaceProjectionResponse>;
}

export interface HttpConsoleDataSourceOptions {
  baseUrl: string;
  timeoutMs?: number;
}

const initialState = (): ConsoleState => ({
  connection: "idle",
  connectionMessage: null,
  health: null,
  workspaces: null,
  backends: null,
  view: null,
  timeline: null,
  selectedWorkspaceId: null,
  selectedProvider: "all",
  selectedSessionKey: null,
  sessionSelectionExplicitlyCleared: false,
  appearance: "system",
  resolvedTheme: systemTheme(),
  highContrast: false,
  lastRefreshedAt: null,
  refreshing: false,
});

export class ConsoleStore {
  private state = initialState();
  private readonly listeners = new Set<() => void>();
  private started = false;
  private polling: ReturnType<typeof setInterval> | undefined;
  private requestGeneration = 0;
  private media: MediaQueryList | undefined;
  private mediaListener: ((event: MediaQueryListEvent) => void) | undefined;

  public constructor(private readonly dataSource: ConsoleProjectionDataSource) {}

  public getSnapshot = (): ConsoleState => this.state;

  public subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  public start(): void {
    if (this.started) {
      return;
    }
    this.started = true;
    this.observeSystemTheme();
    void this.loadInitial();
    this.polling = setInterval(() => {
      if (this.state.connection === "ready" && !this.state.refreshing) {
        void this.loadWorkspace(false);
      }
    }, POLL_INTERVAL_MS);
  }

  public stop(): void {
    this.started = false;
    this.requestGeneration += 1;
    if (this.polling !== undefined) {
      clearInterval(this.polling);
      this.polling = undefined;
    }
    if (this.media !== undefined && this.mediaListener !== undefined) {
      this.media.removeEventListener("change", this.mediaListener);
    }
    this.media = undefined;
    this.mediaListener = undefined;
  }

  public refresh = (): void => {
    void this.loadWorkspace(true);
  };

  public reconnect = (): void => {
    void this.loadInitial();
  };

  public selectWorkspace = (workspaceId: string): void => {
    if (workspaceId === this.state.selectedWorkspaceId) {
      return;
    }
    this.setState({
      selectedWorkspaceId: workspaceId,
      selectedSessionKey: null,
      sessionSelectionExplicitlyCleared: false,
      view: null,
      timeline: null,
      connection: "loading",
      connectionMessage: null,
    });
    void this.loadWorkspace(true);
  };

  public selectProvider = (provider: ConsoleProvider | "all"): void => {
    const sessions = this.state.view?.sessions ?? [];
    const visibleSessions = provider === "all"
      ? sessions
      : sessions.filter((session) => session.identity.provider === provider);
    const selectedStillVisible = visibleSessions.some(
      (session) => sessionIdentityKey(session.identity) === this.state.selectedSessionKey,
    );
    this.setState({
      selectedProvider: provider,
      selectedSessionKey: selectedStillVisible
        ? this.state.selectedSessionKey
        : visibleSessions[0] === undefined
          ? null
          : sessionIdentityKey(visibleSessions[0].identity),
      sessionSelectionExplicitlyCleared: false,
    });
  };

  public selectSession = (provider: ConsoleProvider, nativeSessionId: string): void => {
    const key = sessionIdentityKey({ provider, nativeSessionId });
    if (key === this.state.selectedSessionKey) {
      return;
    }
    this.setState({
      selectedSessionKey: key,
      sessionSelectionExplicitlyCleared: false,
    });
  };

  public clearSessionSelection = (): void => {
    if (this.state.selectedSessionKey === null) {
      return;
    }
    this.setState({
      selectedSessionKey: null,
      sessionSelectionExplicitlyCleared: true,
    });
  };

  public setAppearance = (appearance: AppearanceMode): void => {
    this.setState({
      appearance,
      resolvedTheme: appearance === "system" ? systemTheme() : appearance,
    });
  };

  public toggleContrast = (): void => {
    this.setState({ highContrast: !this.state.highContrast });
  };

  public setHighContrast = (highContrast: boolean): void => {
    if (highContrast === this.state.highContrast) {
      return;
    }
    this.setState({ highContrast });
  };

  private async loadInitial(): Promise<void> {
    const generation = ++this.requestGeneration;
    this.setState({ connection: "loading", refreshing: true, connectionMessage: null, health: null });
    try {
      const health = await this.dataSource.checkHealth();
      if (generation !== this.requestGeneration) {
        return;
      }
      this.setState({ health });
      const [workspaces, backends] = await Promise.all([
        this.dataSource.listWorkspaces(),
        this.dataSource.listProviderBackends(),
      ]);
      if (generation !== this.requestGeneration) {
        return;
      }
      const selectedWorkspaceId = this.state.selectedWorkspaceId
        ?? workspaces.items[0]?.workspaceId
        ?? null;
      this.setState({ workspaces, backends, selectedWorkspaceId });
      if (selectedWorkspaceId === null) {
        this.setState({
          connection: "ready",
          refreshing: false,
          lastRefreshedAt: new Date().toISOString(),
        });
        return;
      }
      await this.loadWorkspace(true, generation);
    } catch (error) {
      if (generation === this.requestGeneration) {
        this.fail(error);
      }
    }
  }

  private async loadWorkspace(
    replace: boolean,
    inheritedGeneration?: number,
  ): Promise<void> {
    const workspaceId = this.state.selectedWorkspaceId;
    if (workspaceId === null) {
      return;
    }
    const generation = inheritedGeneration ?? ++this.requestGeneration;
    if (replace) {
      this.setState({ refreshing: true, connectionMessage: null });
    }
    const cursor = replace ? undefined : this.state.timeline?.nextCursor;
    try {
      const view = await this.dataSource.getWorkspaceView(workspaceId, cursor, 50);
      if (generation !== this.requestGeneration) {
        return;
      }
      const timeline = replace || this.state.timeline === null
        ? rebuildTimeline(view.timeline)
        : mergeTimeline(this.state.timeline, view.timeline);
      if (timeline.gapDetected) {
        this.setState({
          connection: "protocol",
          connectionMessage: "A timeline gap was detected. Refresh to rebuild the bounded projection.",
          view,
          timeline,
          refreshing: false,
        });
        return;
      }
      this.setState({
        connection: "ready",
        connectionMessage: null,
        view,
        timeline,
        selectedSessionKey: selectSessionKey(
          view.sessions,
          this.state.selectedProvider,
          this.state.selectedSessionKey,
          this.state.sessionSelectionExplicitlyCleared,
        ),
        refreshing: false,
        lastRefreshedAt: new Date().toISOString(),
      });
    } catch (error) {
      if (generation === this.requestGeneration) {
        this.fail(error);
      }
    }
  }

  private fail(error: unknown): void {
    const mapped = mapFailure(error);
    this.setState({
      connection: mapped.state,
      connectionMessage: mapped.message,
      refreshing: false,
    });
  }

  private setState(patch: Partial<ConsoleState>): void {
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) {
      listener();
    }
  }

  private observeSystemTheme(): void {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    this.media = window.matchMedia("(prefers-color-scheme: dark)");
    this.mediaListener = (event) => {
      if (this.state.appearance === "system") {
        this.setState({ resolvedTheme: event.matches ? "dark" : "light" });
      }
    };
    this.media.addEventListener("change", this.mediaListener);
  }
}

export const sessionIdentityKey = (
  identity: { provider: ConsoleProvider; nativeSessionId: string },
): string => `${identity.provider}:${identity.nativeSessionId}`;

const selectSessionKey = (
  sessions: ConsoleWorkspaceProjectionResponse["sessions"],
  provider: ConsoleProvider | "all",
  current: string | null,
  explicitlyCleared: boolean,
): string | null => {
  const visible = provider === "all"
    ? sessions
    : sessions.filter((session) => session.identity.provider === provider);
  if (current !== null && visible.some((session) => sessionIdentityKey(session.identity) === current)) {
    return current;
  }
  if (explicitlyCleared) {
    return null;
  }
  return visible[0] === undefined ? null : sessionIdentityKey(visible[0].identity);
};

export const createHttpConsoleDataSource = ({
  baseUrl,
  timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
}: HttpConsoleDataSourceOptions): ConsoleProjectionDataSource => {
  const normalizedBase = baseUrl.replace(/\/+$/u, "");
  return {
    checkHealth: () => fetchProjection(
      `${normalizedBase}/health`,
      parseGatewayHealth,
      timeoutMs,
    ),
    listWorkspaces: () => fetchProjection(
      `${normalizedBase}/workspaces`,
      parseWorkspaceList,
      timeoutMs,
    ),
    listProviderBackends: () => fetchProjection(
      `${normalizedBase}/provider-backends`,
      parseProviderBackends,
      timeoutMs,
    ),
    getWorkspaceView: (workspaceId, cursor, limit = 50) => {
      const params = new URLSearchParams({ limit: String(limit) });
      if (cursor !== undefined) {
        params.set("cursor", cursor);
      }
      return fetchProjection(
        `${normalizedBase}/workspaces/${encodeURIComponent(workspaceId)}?${params}`,
        parseWorkspaceProjection,
        timeoutMs,
      );
    },
  };
};

const fetchProjection = async <T>(
  url: string,
  parse: (payload: unknown) => T,
  timeoutMs: number,
): Promise<T> => {
  const controller = new AbortController();
  const timeout = setTimeout(() => { controller.abort(); }, timeoutMs);
  let response: Response;
  try {
    response = await fetch(url, {
      method: "GET",
      headers: { accept: "application/json" },
      cache: "no-store",
      credentials: "omit",
      redirect: "manual",
      signal: controller.signal,
    });
  } catch {
    if (controller.signal.aborted) {
      throw new ConsoleProtocolError("timeout", "Beacon projection request timed out.");
    }
    throw new ConsoleProtocolError("disconnected", "Beacon projection is disconnected.");
  } finally {
    clearTimeout(timeout);
  }
  if (response.type === "opaqueredirect" || (response.status >= 300 && response.status < 400)) {
    throw new ConsoleProtocolError("redirect", "Projection redirects are not allowed.");
  }
  if (response.status === 401 || response.status === 403) {
    throw new ConsoleProtocolError("permission", "Projection permission was denied.");
  }
  const contentLength = Number(response.headers.get("content-length") ?? "0");
  if (contentLength > MAX_RESPONSE_BYTES) {
    throw new ConsoleProtocolError("oversized", "Projection response exceeded 1 MiB.");
  }
  const text = await response.text();
  if (new TextEncoder().encode(text).byteLength > MAX_RESPONSE_BYTES) {
    throw new ConsoleProtocolError("oversized", "Projection response exceeded 1 MiB.");
  }
  if (!response.ok) {
    throw new ConsoleProtocolError(
      response.status === 503 ? "disconnected" : "malformed",
      response.status === 503
        ? "Beacon projection is disconnected."
        : "Beacon projection request failed.",
    );
  }
  try {
    return parse(JSON.parse(text));
  } catch (error) {
    if (error instanceof ConsoleProtocolError) {
      throw error;
    }
    throw new ConsoleProtocolError("malformed", "Projection response was malformed JSON.");
  }
};

const mapFailure = (
  error: unknown,
): { state: ConsoleConnectionState; message: string } => {
  if (error instanceof ConsoleProtocolError) {
    if (error.kind === "version") {
      return { state: "version", message: error.message };
    }
    if (error.kind === "permission") {
      return { state: "permission", message: error.message };
    }
    if (error.kind === "disconnected") {
      return { state: "disconnected", message: error.message };
    }
    if (error.kind === "timeout") {
      return { state: "timeout", message: error.message };
    }
    return { state: "protocol", message: error.message };
  }
  return { state: "error", message: "Console projection failed." };
};

const systemTheme = (): "light" | "dark" => {
  return typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
};

export const consoleStore = new ConsoleStore(createHttpConsoleDataSource({
  baseUrl: "/beacon-console/api",
}));

export const useConsoleState = (store: ConsoleStore = consoleStore): ConsoleState => {
  return useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    store.getSnapshot,
  );
};
