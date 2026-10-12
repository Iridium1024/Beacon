import { useEffect, type ReactNode } from "react";

import type {
  ConsoleAgentView,
  ConsoleProvider,
  ConsoleTimelineEvent,
  DispatchProjection,
  ForeignSessionRef,
  ProviderBackendView,
} from "../shared/contracts.js";
import {
  consoleStore,
  sessionIdentityKey,
  type ConsoleConnectionState,
  type ConsoleStore,
  useConsoleState,
} from "./console-store.js";
import { useConsoleI18n, type ConsoleCopyKey } from "./i18n.js";
import { Icon } from "./icons.js";

const providerLabels: Record<string, string> = {
  claude: "Claude",
  codex: "Codex",
  hermes: "Hermes",
  deepseek_harness: "DeepSeek Harness",
};

export type ConsoleSourceKind = "embedded" | "external" | "fake";

export interface ConsoleSurfaceProps {
  connectionDetail?: ReactNode;
  presentation?: "desktop" | "dsh";
  sourceKind?: ConsoleSourceKind;
  store?: ConsoleStore;
}

export function ConsoleSurface({
  connectionDetail,
  presentation = "dsh",
  sourceKind = "embedded",
  store = consoleStore,
}: ConsoleSurfaceProps): JSX.Element {
  const state = useConsoleState(store);
  const { locale, t } = useConsoleI18n();
  useEffect(() => { store.start(); }, [store]);

  const view = state.view;
  const events = state.timeline?.events ?? [];
  const visibleSessions = view?.sessions.filter((session) => (
    state.selectedProvider === "all" || session.identity.provider === state.selectedProvider
  )) ?? [];
  const selectedSession = visibleSessions.find(
    (session) => sessionIdentityKey(session.identity) === state.selectedSessionKey,
  ) ?? null;
  const selectedAgent = selectedSession === null
    ? null
    : view?.agents.find((agent) => agent.agentId === selectedSession.agentId) ?? null;
  const selectedBackend = selectedSession === null
    ? null
    : view?.providerBackends.find((backend) => backend.provider === selectedSession.identity.provider) ?? null;

  return (
    <main
      className="bc-surface"
      data-contrast={state.highContrast ? "high" : "normal"}
      data-theme={state.resolvedTheme}
    >
      {presentation === "dsh" ? (
        <header className="bc-topbar">
          <div>
            <h1>Beacon Session Console</h1>
            <p>{t("readOnlyMode")}</p>
          </div>
          <div className="bc-topbar-actions">
            <span className="bc-readonly-chip"><span className="bc-status-dot is-good" />{t("local")} · {t("readOnly")}</span>
            <span className="bc-refreshed">{formatRefresh(state.lastRefreshedAt, locale, t("updated"))}</span>
            <button className="bc-refresh-button" disabled={state.refreshing} onClick={store.refresh} type="button">
              <Icon name="refresh" size={20} />{state.refreshing ? t("refreshing") : t("refresh")}
            </button>
          </div>
        </header>
      ) : null}

      <div className="bc-authority-banner">
        <Icon name="beacon" size={18} />
        <span><strong>{t("authorityBanner")}</strong> · {t("sessionProjection")}</span>
        <span className="bc-banner-boundary">{t("noControlMethods")}</span>
      </div>

      <ConnectionNotice state={state.connection} message={state.connectionMessage} />
      {connectionDetail}

      {view === null ? (
        <EmptySurface loading={state.connection === "loading" || state.connection === "idle"} />
      ) : (
        <div className="bc-content-grid">
          <section className="bc-primary" aria-label={t("sessionDetails")}>
            <div className="bc-context-heading">
              <div>
                <span className="bc-eyebrow">{view.workspace.displayName}</span>
                <h1>{t("sessions")}</h1>
                <p>{t("sessionFirstDescription")}</p>
              </div>
              <span className="bc-context-count">{visibleSessions.length} / {view.sessions.length}</span>
            </div>

            <MobileSessionNavigator
              sessions={visibleSessions}
              store={store}
              workspaces={state.workspaces?.items ?? []}
              selectedProvider={state.selectedProvider}
              selectedSessionKey={state.selectedSessionKey}
              selectedWorkspaceId={state.selectedWorkspaceId}
            />

            {selectedSession === null ? (
              <NoSessionSelection />
            ) : (
              <SessionDetail
                agent={selectedAgent}
                backend={selectedBackend}
                session={selectedSession}
                sourceKind={sourceKind}
                store={store}
                workspaceName={view.workspace.displayName}
              />
            )}

            <ActivityProjection
              events={events}
              rebuildRequired={state.timeline?.rebuildRequired === true}
              total={view.timeline.page.total}
              truncated={state.timeline?.truncated === true}
              nextCursor={state.timeline?.nextCursor ?? null}
            />
          </section>

          <aside className="bc-secondary" aria-label={t("secondaryInformation")}>
            <TermsPanel />
            <DispatchPanel
              agentId={selectedAgent?.agentId ?? null}
              dispatches={view.dispatches}
            />
            <CapabilityPanel backend={selectedBackend} />
            <details className="bc-disclosure bc-limitations">
              <summary><span><Icon name="help" size={20} /><span><strong>{t("projectionLimits")}</strong><small>{t("projectionLimitsDescription")}</small></span></span><Icon name="chevron" /></summary>
              <ul>{view.limitations.map((item) => <li key={item}>{localizeLimitation(item, locale, t)}</li>)}</ul>
            </details>
          </aside>
        </div>
      )}
    </main>
  );
}

function MobileSessionNavigator({
  selectedProvider,
  selectedSessionKey,
  selectedWorkspaceId,
  sessions,
  store,
  workspaces,
}: {
  selectedProvider: ConsoleProvider | "all";
  selectedSessionKey: string | null;
  selectedWorkspaceId: string | null;
  sessions: ForeignSessionRef[];
  store: ConsoleStore;
  workspaces: Array<{ workspaceId: string; displayName: string }>;
}): JSX.Element {
  const { locale, t } = useConsoleI18n();
  const options: Array<[ConsoleProvider | "all", string]> = [
    ["all", t("allProviders")],
    ["claude", "Claude"],
    ["codex", "Codex"],
    ["hermes", "Hermes"],
    ["deepseek_harness", "DeepSeek Harness"],
  ];
  return (
    <section className="bc-mobile-session-nav" aria-label={t("workspaceNavigation")}>
      <div className="bc-mobile-select-grid">
        <label><span>{t("workspace")}</span><select aria-label={t("workspace")} onChange={(event) => { store.selectWorkspace(event.target.value); }} value={selectedWorkspaceId ?? ""}>{workspaces.map((workspace) => <option key={workspace.workspaceId} value={workspace.workspaceId}>{workspace.displayName}</option>)}</select></label>
        <label><span>{t("providers")}</span><select aria-label={t("providers")} onChange={(event) => { store.selectProvider(event.target.value as ConsoleProvider | "all"); }} value={selectedProvider}>{options.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
      </div>
      <div className="bc-mobile-session-list" aria-label={t("sessions")}>
        {sessions.map((session) => {
          const selected = selectedSessionKey === sessionIdentityKey(session.identity);
          return (
            <button
              aria-pressed={selected}
              className={selected ? "is-selected" : undefined}
              key={sessionIdentityKey(session.identity)}
              onClick={() => { store.selectSession(session.identity.provider, session.identity.nativeSessionId); }}
              type="button"
            >
              <span><strong>{providerLabels[session.identity.provider]}</strong><small>{session.identity.nativeSessionId}</small></span>
              <time dateTime={session.updatedAt ?? undefined}>{formatShortDate(session.updatedAt, locale, t("unknown"))}</time>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function SessionDetail({
  agent,
  backend,
  session,
  sourceKind,
  store,
  workspaceName,
}: {
  agent: ConsoleAgentView | null;
  backend: ProviderBackendView | null;
  session: ForeignSessionRef;
  sourceKind: ConsoleSourceKind;
  store: ConsoleStore;
  workspaceName: string;
}): JSX.Element {
  const { locale, t } = useConsoleI18n();
  const provider = providerLabels[session.identity.provider] ?? session.identity.provider;
  const state = statePresentation(session.state.value, t);
  const source = sourcePresentation(sourceKind, t);
  const recovery = recoveryPresentation(session, backend, t);
  return (
    <article className="bc-session-detail" aria-labelledby="bc-session-detail-title">
      <header className="bc-session-hero">
        <div className={`bc-provider-emblem bc-provider-${session.identity.provider}`}>{provider.slice(0, session.identity.provider === "deepseek_harness" ? 3 : 2)}</div>
        <div>
          <span className="bc-eyebrow">{t("sessionDetails")}</span>
          <h2 id="bc-session-detail-title">{provider} · <span>{session.identity.nativeSessionId}</span></h2>
          <p>{workspaceName} · {t("readOnlySessionDescription")}</p>
        </div>
        <div className="bc-session-hero-actions">
          <span className={`bc-state-chip ${state.tone}`}><i className="bc-status-dot" />{state.label}</span>
          <button className="bc-clear-selection" onClick={store.clearSessionSelection} type="button">{t("clearSessionSelection")}</button>
        </div>
      </header>

      <div className="bc-detail-groups">
        <section>
          <h3><Icon name="agent" size={20} />{t("sessionIdentity")}</h3>
          <dl>
            <DetailRow label={t("provider")} value={provider} />
            <DetailRow help={recovery.nativeIdHelp} label={t("nativeSessionId")} mono value={session.identity.nativeSessionId} />
            <DetailRow help={t("beaconHandleHelp")} label={t("beaconHandle")} mono value={session.handleId} />
            <DetailRow help={agent === null ? t("linkedAgentMissing") : agent.agentId} label={t("linkedAgent")} value={agent?.displayName ?? t("missing")} />
          </dl>
        </section>

        <section>
          <h3><Icon name="activity" size={20} />{t("statusAndTime")}</h3>
          <dl>
            <DetailRow label={t("status")} value={state.label} />
            <DetailRow label={t("lastObserved")} value={formatDateTime(session.updatedAt, locale, t("missing"))} />
            <DetailRow label={t("workingDirectorySummary")} mono value={session.cwdSummary ?? t("missing")} />
            <DetailRow label={t("sourceSequence")} mono value={session.sourceEventSequence === null ? t("missing") : String(session.sourceEventSequence)} />
          </dl>
        </section>

        <section>
          <h3><Icon name="workspace" size={20} />{t("sourceAndOwnership")}</h3>
          <dl>
            <DetailRow help={source.help} label={t("projectionSource")} value={source.label} />
            <DetailRow label={t("projectionMarker")} value={session.foreignProjectionOnly ? t("foreignProjection") : t("nativeDshProjection")} />
            <DetailRow label={t("beaconAuthority")} value={t("beaconProjectionAuthority")} />
          </dl>
        </section>

        <section>
          <h3><Icon name="capability" size={20} />{t("continuityAndRecovery")}</h3>
          <dl>
            <DetailRow label={t("continuityState")} value={continuityLabel(session.continuity.state, t)} />
            <DetailRow help={session.continuity.scope || t("missing")} label={t("continuityScope")} value={continuityScopeLabel(session.continuity.scope, t)} />
            <DetailRow help={recovery.help} label={t("recoverySemantics")} value={recovery.label} />
          </dl>
        </section>
      </div>
    </article>
  );
}

function DetailRow({ help, label, mono = false, value }: { help?: string; label: string; mono?: boolean; value: string }): JSX.Element {
  return <div><dt>{label}</dt><dd className={mono ? "is-mono" : undefined}>{value}{help === undefined ? null : <small>{help}</small>}</dd></div>;
}

function ActivityProjection({ events, nextCursor, rebuildRequired, total, truncated }: { events: ConsoleTimelineEvent[]; nextCursor: string | null; rebuildRequired: boolean; total: number; truncated: boolean }): JSX.Element {
  const { t } = useConsoleI18n();
  return (
    <details className="bc-disclosure bc-activity-projection">
      <summary><span><Icon name="timeline" size={20} /><span><strong>{t("boundedActivity")}</strong><small>{t("boundedActivityDescription")}</small></span></span><span className="bc-disclosure-meta">{events.length} / {total}</span><Icon name="chevron" /></summary>
      <p className="bc-scope-note">{t("workspaceActivityScope")}</p>
      {truncated ? <div className="bc-inline-warning">{t("timelineTruncated")} {nextCursor}</div> : null}
      {rebuildRequired ? <div className="bc-inline-warning" role="status">{t("timelineRebuild")}</div> : null}
      <ol className="bc-timeline">{[...events].reverse().map((event) => <TimelineEvent event={event} key={event.eventId} />)}</ol>
      {events.length === 0 ? <p className="bc-empty-copy">{t("noTimeline")}</p> : null}
    </details>
  );
}

function TimelineEvent({ event }: { event: ConsoleTimelineEvent }): JSX.Element {
  const { locale, t } = useConsoleI18n();
  return (
    <li className="bc-event">
      <span className={`bc-category bc-category-${event.category.value}`}>{categoryLabel(event, t)}</span>
      <span className="bc-event-copy"><strong>{eventSummary(event.eventKind, t)}</strong><small>{t("redactedEventFact")}</small></span>
      <time dateTime={event.occurredAt}>{formatTime(event.occurredAt, locale)}</time>
      <details className="bc-event-technical"><summary>{t("eventTechnicalDetails")}</summary><dl><div><dt>{t("eventKind")}</dt><dd>{event.eventKind}</dd></div><div><dt>{t("aggregateType")}</dt><dd>{event.aggregateType}</dd></div><div><dt>{t("aggregateId")}</dt><dd>{event.aggregateId}</dd></div><div><dt>{t("sourceSequence")}</dt><dd>{event.sourceEventSequence}</dd></div></dl></details>
    </li>
  );
}

function TermsPanel(): JSX.Element {
  const { t } = useConsoleI18n();
  const definitions = [[t("dispatch"), t("dispatchDefinition")], [t("backend"), t("backendDefinition")], [t("capability"), t("capabilityDefinition")], [t("ownedLive"), t("ownedLiveDefinition")], [t("continuity"), t("continuityDefinition")]];
  return <details className="bc-disclosure bc-help-panel"><summary><span><Icon name="help" size={20} /><span><strong>{t("help")}</strong><small>{t("helpDescription")}</small></span></span><Icon name="chevron" /></summary><dl className="bc-term-grid">{definitions.map(([term, definition]) => <div key={term}><dt>{term}</dt><dd>{definition}</dd></div>)}</dl></details>;
}

function DispatchPanel({ agentId, dispatches }: { agentId: string | null; dispatches: DispatchProjection[] }): JSX.Element {
  const { t } = useConsoleI18n();
  const relevant = agentId === null ? [] : dispatches.filter((dispatch) => dispatch.sourceAgentId === agentId || dispatch.targetAgentId === agentId);
  return (
    <details className="bc-disclosure"><summary><span><Icon name="activity" size={20} /><span><strong>{t("dispatchFacts")}</strong><small>{t("dispatchDescription")}</small></span></span><span className="bc-disclosure-meta">{relevant.length}</span><Icon name="chevron" /></summary>{relevant.length === 0 ? <p className="bc-empty-copy">{t("noDispatches")}</p> : <dl className="bc-dispatch-list">{relevant.map((dispatch) => <div key={dispatch.dispatchId}><dt>{dispatch.dispatchId}</dt><dd>{dispatch.sourceAgentId} → {dispatch.targetAgentId}<small>{t("status")}: {enumStateLabel(dispatch.status.value, t)}</small></dd></div>)}</dl>}</details>
  );
}

function CapabilityPanel({ backend }: { backend: ProviderBackendView | null }): JSX.Element {
  const { locale, t } = useConsoleI18n();
  return <details className="bc-disclosure"><summary><span><Icon name="capability" size={20} /><span><strong>{t("technicalAndCapability")}</strong><small>{t("technicalDescription")}</small></span></span><Icon name="chevron" /></summary>{backend === null ? <p className="bc-empty-copy">{t("capabilityUnavailable")}</p> : <CapabilityCard backend={backend} locale={locale} />}</details>;
}

function CapabilityCard({ backend, locale }: { backend: ProviderBackendView; locale: string }): JSX.Element {
  const { t } = useConsoleI18n();
  const provider = providerLabels[backend.provider] ?? backend.provider;
  return (
    <div className="bc-capability-detail"><h3>{provider}</h3><p>{humanImplementation(backend, locale)}</p><dl className="bc-interface-compare"><div><dt>{t("officialInterface")}</dt><dd>{backend.officialInterface}</dd></div><div><dt>{t("backendId")}</dt><dd>{backend.backendId}</dd></div><div><dt>{t("lifecycle")}</dt><dd>{enumLabel(backend.lifecycle, t("unknown"))}</dd></div><div><dt>{t("statusAuthority")}</dt><dd>{enumLabel(backend.statusAuthority, t("unknown"))}</dd></div></dl><div className="bc-capability-facts"><CapabilityFact label={t("send")} value={backend.capabilities.canSend} /><CapabilityFact label={t("resume")} value={backend.capabilities.canResume} /><CapabilityFact label={t("status")} value={backend.capabilities.canReadStatus} /><CapabilityFact label={t("ownedLive")} value={backend.capabilities.canReadOwnedLiveStatus} /><CapabilityFact label={t("supplement")} value={backend.capabilities.canSupplementActiveTurn} /><CapabilityFact label={t("cancel")} value={backend.capabilities.canCancel} /><CapabilityFact label={t("approval")} value={backend.capabilities.canHandleApprovalRequests} /><CapabilityFact label={t("history")} value={backend.capabilities.canReadHistory} /><CapabilityFact label={t("crossProcess")} value={backend.capabilities.canResumeAcrossProcess} /><CapabilityFact label={t("multiSession")} value={backend.capabilities.canManageMultipleThreads} /></div><p className="bc-view-only-note">{t("viewOnly")}</p></div>
  );
}

function CapabilityFact({ label, value }: { label: string; value: boolean | null }): JSX.Element {
  const { t } = useConsoleI18n();
  const state = value === null ? "unknown" : value ? "yes" : "no";
  return <span className={`is-${state}`}>{label}<strong>{value === null ? t("unknown") : value ? t("yes") : t("no")}</strong></span>;
}

function NoSessionSelection(): JSX.Element {
  const { t } = useConsoleI18n();
  return <section className="bc-no-session"><Icon name="agent" size={24} /><h2>{t("noSessionSelected")}</h2><p>{t("noSessionSelectedDescription")}</p></section>;
}

function ConnectionNotice({ state, message }: { state: ConsoleConnectionState; message: string | null }): JSX.Element | null {
  const { t } = useConsoleI18n();
  if (["ready", "idle"].includes(state)) return null;
  const labels: Record<ConsoleConnectionState, string> = { loading: t("loading"), disconnected: t("gatewayDisconnected"), permission: t("permissionDenied"), protocol: t("protocolFailed"), version: t("versionFailed"), timeout: t("timeout"), error: t("unavailable"), ready: t("connected"), idle: t("waiting") };
  const descriptions: Record<ConsoleConnectionState, string> = {
    loading: t("connectionLoadingDescription"),
    disconnected: t("connectionDisconnectedDescription"),
    permission: t("connectionPermissionDescription"),
    protocol: t("connectionProtocolDescription"),
    version: t("connectionVersionDescription"),
    timeout: t("connectionTimeoutDescription"),
    error: t("connectionErrorDescription"),
    ready: t("connected"),
    idle: t("waiting"),
  };
  return <div className={`bc-connection-notice is-${state}`} data-raw-diagnostic={message ?? undefined} role="status" aria-live="polite"><strong>{labels[state]}</strong><span>{descriptions[state]}</span></div>;
}

function EmptySurface({ loading }: { loading: boolean }): JSX.Element {
  const { t } = useConsoleI18n();
  return <section className="bc-empty-surface"><span className={loading ? "bc-loader" : "bc-empty-icon"}><Icon name="activity" size={20} /></span><h1>{loading ? t("loading") : t("noProjection")}</h1><p>{t("noProjectionDescription")}</p></section>;
}

const statePresentation = (state: string, t: (key: ConsoleCopyKey) => string): { label: string; tone: string } => {
  const keys: Record<string, ConsoleCopyKey> = { active: "active", completed: "completed", continuity_lost: "continuityLost", failed: "failed", inactive: "inactive", running: "running" };
  const good = ["active", "completed", "running"].includes(state);
  return { label: t(keys[state] ?? "unknown"), tone: good ? "is-good" : state === "continuity_lost" ? "is-warn" : "is-muted" };
};

const recoveryPresentation = (session: ForeignSessionRef, backend: ProviderBackendView | null, t: (key: ConsoleCopyKey) => string): { label: string; help: string; nativeIdHelp: string } => {
  if (session.continuity.resumeAcrossRuntimeRestart === true) return { label: t("resumeAcrossRuntimeKnown"), help: t("resumeAcrossRuntimeHelp"), nativeIdHelp: t("nativeIdResumableKnown") };
  if (session.continuity.resumeAcrossRuntimeRestart === false) return { label: t("noResumeAcrossRuntime"), help: t("noResumeAcrossRuntimeHelp"), nativeIdHelp: t("nativeIdNotGuaranteed") };
  if (backend?.capabilities.canResume === false) return { label: t("resumeUnsupported"), help: t("resumeUnsupportedHelp"), nativeIdHelp: t("nativeIdNotGuaranteed") };
  return { label: t("recoveryUnknown"), help: t("recoveryUnknownHelp"), nativeIdHelp: t("nativeIdNotGuaranteed") };
};

const sourcePresentation = (source: ConsoleSourceKind, t: (key: ConsoleCopyKey) => string): { label: string; help: string } => {
  if (source === "fake") return { label: t("syntheticFixture"), help: t("syntheticSourceDescription") };
  if (source === "external") return { label: t("externalGatewayProjection"), help: t("externalSourceDescription") };
  return { label: t("embeddedProjection"), help: t("embeddedSourceDescription") };
};

const continuityLabel = (state: string, t: (key: ConsoleCopyKey) => string): string => {
  const labels: Record<string, ConsoleCopyKey> = {
    generation_bound: "generationBound",
    native_session_available: "nativeSessionAvailable",
    resume_required: "resumeRequired",
    lost: "continuityLost",
    observed: "observed",
  };
  return t(labels[state] ?? "unknown");
};

const continuityScopeLabel = (scope: string, t: (key: ConsoleCopyKey) => string): string => {
  const labels: Record<string, ConsoleCopyKey> = {
    owned_runtime_generation: "scopeOwnedRuntimeGeneration",
    persistent_native_session: "scopePersistentNativeSession",
    registered_provider_session: "scopeRegisteredProviderSession",
  };
  return scope === "" ? t("missing") : t(labels[scope] ?? "unknown");
};

const enumStateLabel = (state: string, t: (key: ConsoleCopyKey) => string): string => {
  const labels: Record<string, ConsoleCopyKey> = { completed: "completed", failed: "failed", waiting_response: "waitingResponse" };
  return t(labels[state] ?? "unknown");
};

const eventSummary = (kind: string, t: (key: ConsoleCopyKey) => string): string => {
  const labels: Record<string, ConsoleCopyKey> = { "agent_registration.changed": "eventAgentRegistration", "agent_endpoint.changed": "eventAgentEndpoint", "codex_registered_session_handle.changed": "eventSessionHandle", "deepseek_harness_registered_session_handle.changed": "eventSessionHandle", "deepseek_harness_runtime_lifecycle.recorded": "eventRuntimeLifecycle", "hermes_registered_session_handle.changed": "eventSessionHandle", "agent_dispatch.changed": "eventDispatch", "run_session.changed": "eventRunSession", "context.update_appended": "eventObserved" };
  return t(labels[kind] ?? "eventObserved");
};

const categoryLabel = (event: ConsoleTimelineEvent, t: (key: ConsoleCopyKey) => string): string => {
  const labels: Record<string, ConsoleCopyKey> = { dispatch: "categoryDispatch", identity: "categoryIdentity", lifecycle: "categoryLifecycle", runtime: "categoryRuntime", session: "categorySession" };
  return event.category.known ? t(labels[event.category.value] ?? "unknown") : t("unknown");
};

const localizeLimitation = (value: string, locale: string, t: (key: ConsoleCopyKey) => string): string => {
  if (locale !== "zh-CN") return value;
  if (value.includes("prompt, transcript")) return t("limitNoSensitiveContent");
  if (value.includes("prompt, resume")) return t("limitNoWriteMethods");
  if (value.includes("do not own foreign")) return t("limitNoProviderOwnership");
  if (value.includes("not authentication")) return t("limitLoopbackNotAuth");
  return t("projectionLimitsDescription");
};

const enumLabel = ({ known, rawValue, value }: { known: boolean; rawValue: string; value: string }, unknown: string): string => known ? value : `${unknown} · ${rawValue}`;
const formatTime = (value: string, locale: string): string => { const parsed = new Date(value); return Number.isNaN(parsed.valueOf()) ? "—" : new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(parsed); };
const formatDateTime = (value: string | null, locale: string, missing: string): string => { if (value === null) return missing; const parsed = new Date(value); return Number.isNaN(parsed.valueOf()) ? missing : new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(parsed); };
const formatShortDate = (value: string | null, locale: string, missing: string): string => { if (value === null) return missing; const parsed = new Date(value); return Number.isNaN(parsed.valueOf()) ? missing : new Intl.DateTimeFormat(locale, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(parsed); };
const formatRefresh = (value: string | null, locale: string, updated: string): string => value === null ? "—" : `${updated} ${formatTime(value, locale)}`;

const humanImplementation = (backend: ProviderBackendView, locale: string): string => {
  const labels: Record<string, [string, string]> = { claude: ["Short-lived Agent SDK observation", "短生命周期 Agent SDK 观察"], codex: ["Short-lived app-server observation", "短生命周期 app-server 观察"], hermes: ["Registered-session observation", "已注册会话观察"], deepseek_harness: ["Managed runtime observation", "托管运行时观察"] };
  const pair = labels[backend.provider];
  return pair === undefined ? backend.beaconImplementation : pair[locale === "zh-CN" ? 1 : 0];
};
