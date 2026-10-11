import { useEffect, type ReactNode } from "react";

import type { ConsoleProvider, ForeignSessionRef } from "../shared/contracts.js";
import {
  consoleStore,
  sessionIdentityKey,
  type ConsoleStore,
  useConsoleState,
} from "./console-store.js";
import { useConsoleI18n, type ConsoleCopyKey } from "./i18n.js";
import { Icon } from "./icons.js";

const providers: Array<{ id: ConsoleProvider | "all"; short: string }> = [
  { id: "all", short: "All" },
  { id: "claude", short: "Cl" },
  { id: "codex", short: "Cx" },
  { id: "hermes", short: "He" },
  { id: "deepseek_harness", short: "DSH" },
];

const providerLabels: Record<ConsoleProvider, string> = {
  claude: "Claude",
  codex: "Codex",
  hermes: "Hermes",
  deepseek_harness: "DeepSeek Harness",
};

export interface ConsoleSidebarProps {
  collapsed?: boolean;
  footer?: ReactNode;
  presentation?: "desktop" | "dsh";
  store?: ConsoleStore;
}

export function ConsoleSidebar({
  collapsed = false,
  footer,
  presentation = "dsh",
  store = consoleStore,
}: ConsoleSidebarProps): JSX.Element {
  const state = useConsoleState(store);
  const { t } = useConsoleI18n();
  useEffect(() => { store.start(); }, [store]);

  const sessions = state.view?.sessions ?? [];
  if (collapsed) {
    return (
      <aside className="bc-sidebar bc-sidebar--collapsed" aria-label={t("providerFilters")}>
        <div className="bc-mark" title={t("sessionProjection")}><Icon name="beacon" /></div>
        {providers.slice(1).map((provider) => {
          const label = providerLabels[provider.id as ConsoleProvider];
          return (
          <button
            aria-label={`${t("providers")}: ${label}`}
            className={state.selectedProvider === provider.id ? "bc-rail-button is-active" : "bc-rail-button"}
            key={provider.id}
            onClick={() => { store.selectProvider(provider.id); }}
            type="button"
          >
            {provider.short}
          </button>
          );
        })}
      </aside>
    );
  }

  return (
    <aside
      className="bc-sidebar"
      aria-label={t("workspaceNavigation")}
      data-contrast={state.highContrast ? "high" : "normal"}
      data-theme={state.resolvedTheme}
    >
      <div className="bc-brand">
        <span className="bc-mark"><Icon name="beacon" /></span>
        <span><strong>Beacon</strong><small>{presentation === "desktop" ? "Desktop" : "Session Console"}</small></span>
      </div>

      <div className="bc-sidebar-section">
        <label className="bc-kicker" htmlFor="bc-workspace-select">{t("workspace")}</label>
        <div className="bc-select-wrap">
          <Icon name="workspace" />
          <select
            id="bc-workspace-select"
            onChange={(event) => { store.selectWorkspace(event.target.value); }}
            value={state.selectedWorkspaceId ?? ""}
          >
            {(state.workspaces?.items ?? []).map((workspace) => (
              <option key={workspace.workspaceId} value={workspace.workspaceId}>
                {workspace.displayName}
              </option>
            ))}
          </select>
        </div>
      </div>

      <nav className="bc-sidebar-section" aria-label={t("providerFilters")}>
        <span className="bc-kicker">{t("providers")}</span>
        <div className="bc-provider-list">
          {providers.map((provider) => {
            const label = provider.id === "all"
              ? t("allProviders")
              : providerLabels[provider.id];
            const count = provider.id === "all"
              ? sessions.length
              : sessions.filter((session) => session.identity.provider === provider.id).length;
            return (
              <button
                aria-pressed={state.selectedProvider === provider.id}
                className={state.selectedProvider === provider.id ? "bc-provider-row is-active" : "bc-provider-row"}
                key={provider.id}
                onClick={() => { store.selectProvider(provider.id); }}
                type="button"
              >
                <span className={`bc-provider-monogram bc-provider-${provider.id}`}>{provider.short}</span>
                <span>{label}</span>
                <span className="bc-count">{count}</span>
              </button>
            );
          })}
        </div>
      </nav>

      <div className="bc-sidebar-section bc-session-section">
        <span className="bc-kicker">{t("sessions")}</span>
        <div className="bc-session-list">
          {filteredSessions(sessions, state.selectedProvider).map((session) => (
            <SessionRow
              key={`${session.identity.provider}:${session.identity.nativeSessionId}:${session.handleId}`}
              onSelect={() => { store.selectSession(session.identity.provider, session.identity.nativeSessionId); }}
              selected={state.selectedSessionKey === sessionIdentityKey(session.identity)}
              session={session}
            />
          ))}
          {sessions.length === 0 ? <p className="bc-empty-copy">{t("noSessions")}</p> : null}
        </div>
      </div>

      <div className="bc-sidebar-footer">
        {footer}
        <div className="bc-authority-note">
          <span className="bc-status-dot is-good" />
          <span><strong>{t("authorityBanner")}</strong><small>{presentation === "desktop" ? t("beaconProjection") : t("dshDisplayShell")}</small></span>
        </div>
        {presentation === "dsh" ? (
          <>
            <div className="bc-appearance" aria-label={t("appearance")}>
              {(["light", "dark", "system"] as const).map((mode) => (
                <button
                  aria-pressed={state.appearance === mode}
                  key={mode}
                  onClick={() => { store.setAppearance(mode); }}
                  type="button"
                >
                  {t(mode)}
                </button>
              ))}
            </div>
            <button className="bc-contrast-button" onClick={store.toggleContrast} type="button">
              {state.highContrast ? t("standard") : t("enhanced")}
            </button>
          </>
        ) : null}
      </div>
    </aside>
  );
}

function SessionRow({
  onSelect,
  selected,
  session,
}: {
  onSelect: () => void;
  selected: boolean;
  session: ForeignSessionRef;
}): JSX.Element {
  const { locale, t } = useConsoleI18n();
  const continuityWarning = session.continuity.state === "lost";
  const provider = providerLabels[session.identity.provider];
  return (
    <button
      aria-label={`${provider} · ${session.identity.nativeSessionId}`}
      aria-pressed={selected}
      className={selected ? "bc-session-row is-selected" : "bc-session-row"}
      onClick={onSelect}
      type="button"
    >
      <span className={`bc-provider-monogram bc-provider-${session.identity.provider}`}>
        {provider.slice(0, session.identity.provider === "deepseek_harness" ? 3 : 2)}
      </span>
      <span className="bc-session-copy">
        <strong>{provider}</strong>
        <small title={session.identity.nativeSessionId}>{session.identity.nativeSessionId}</small>
      </span>
      <span className="bc-session-meta">
        <span><i className={`bc-status-dot ${continuityWarning ? "is-warn" : stateDot(session.state.value)}`} />{stateLabel(session.state.value, t)}</span>
        <time dateTime={session.updatedAt ?? undefined}>{formatSessionTime(session.updatedAt, locale, t("unknown"))}</time>
      </span>
    </button>
  );
}

const filteredSessions = (
  sessions: ForeignSessionRef[],
  provider: ConsoleProvider | "all",
): ForeignSessionRef[] => {
  return provider === "all"
    ? sessions
    : sessions.filter((session) => session.identity.provider === provider);
};

const stateDot = (state: string): string => {
  if (["active", "running", "completed"].includes(state)) {
    return "is-good";
  }
  if (["failed", "inactive"].includes(state)) {
    return "is-muted";
  }
  return "is-warn";
};

const stateLabel = (state: string, t: ReturnType<typeof useConsoleI18n>["t"]): string => {
  const labels: Record<string, ConsoleCopyKey> = {
    active: "active",
    completed: "completed",
    continuity_lost: "continuityLost",
    failed: "failed",
    inactive: "inactive",
    running: "running",
  };
  const key = labels[state];
  return key === undefined ? t("unknown") : t(key);
};

const formatSessionTime = (value: string | null, locale: string, unknown: string): string => {
  if (value === null) {
    return unknown;
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf())
    ? unknown
    : new Intl.DateTimeFormat(locale, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(parsed);
};
