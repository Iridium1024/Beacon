import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";

import { ConsoleSidebar } from "@beacon-console/client/ConsoleSidebar.js";
import { ConsoleSurface } from "@beacon-console/client/ConsoleSurface.js";
import {
  ConsoleStore,
  createHttpConsoleDataSource,
  useConsoleState,
} from "@beacon-console/client/console-store.js";
import {
  ConsoleI18nProvider,
  useConsoleI18n,
} from "@beacon-console/client/i18n.js";
import { Icon } from "@beacon-console/client/icons.js";

import {
  type ApplicationSettings,
  readApplicationSettings,
  type TextScale,
  writeApplicationSettings,
} from "../config/application-settings.js";
import {
  type ConnectionSettings,
  type DesktopMode,
  type FakeScenario,
  type GatewayValidationCode,
  readConnectionSettings,
  validateGatewayUrl,
  writeConnectionSettings,
} from "../config/connection-settings.js";
import { createFixtureConsoleDataSource } from "../data/fixture-source.js";

export function DesktopApp(): JSX.Element {
  const [application, setApplication] = useState<ApplicationSettings>(readApplicationSettings);
  const [connection, setConnection] = useState<ConnectionSettings>(readConnectionSettings);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const store = useMemo(() => new ConsoleStore(
    connection.mode === "fake"
      ? createFixtureConsoleDataSource({ scenario: connection.fakeScenario })
      : createHttpConsoleDataSource({
          baseUrl: `${connection.gatewayUrl}/api/console/v1`,
          timeoutMs: 5_000,
        }),
  ), [connection.fakeScenario, connection.gatewayUrl, connection.mode]);
  const presentationState = useConsoleState(store);

  useEffect(() => {
    store.start();
    return () => { store.stop(); };
  }, [store]);

  useEffect(() => {
    store.setAppearance(application.appearance);
    store.setHighContrast(application.contrast === "enhanced");
    document.documentElement.lang = application.locale;
    document.title = application.locale === "zh-CN" ? "Beacon · 本机只读控制台" : "Beacon · Local read-only console";
  }, [application.appearance, application.contrast, application.locale, store]);

  const closeSettings = useCallback((): void => {
    setSettingsOpen(false);
    requestAnimationFrame(() => { settingsButtonRef.current?.focus(); });
  }, []);

  const applySettings = (nextApplication: ApplicationSettings, nextConnection: ConnectionSettings): void => {
    writeApplicationSettings(nextApplication);
    writeConnectionSettings(nextConnection);
    setApplication(nextApplication);
    setConnection(nextConnection);
    closeSettings();
  };

  return (
    <ConsoleI18nProvider locale={application.locale}>
      <BeaconShell
        application={application}
        connection={connection}
        onOpenSettings={() => { setSettingsOpen(true); }}
        settingsButtonRef={settingsButtonRef}
        store={store}
      />
      {settingsOpen ? (
        <SettingsPanel
          application={application}
          connection={connection}
          onApply={applySettings}
          onClose={closeSettings}
          resolvedTheme={presentationState.resolvedTheme}
        />
      ) : null}
    </ConsoleI18nProvider>
  );
}

function BeaconShell({
  application,
  connection,
  onOpenSettings,
  settingsButtonRef,
  store,
}: {
  application: ApplicationSettings;
  connection: ConnectionSettings;
  onOpenSettings: () => void;
  settingsButtonRef: RefObject<HTMLButtonElement>;
  store: ConsoleStore;
}): JSX.Element {
  const state = useConsoleState(store);
  return (
    <div
      className="bcd-app"
      data-contrast={state.highContrast ? "enhanced" : "standard"}
      data-text-scale={application.textScale}
      data-theme={state.resolvedTheme}
    >
      <BeaconHeader
        onOpenSettings={onOpenSettings}
        settingsButtonRef={settingsButtonRef}
        state={state}
        store={store}
      />
      <SourceBoundary mode={connection.mode} />
      <div className="bcd-shell">
        <div className="bcd-sidebar-wide">
          <ConsoleSidebar
            footer={(
              <ConnectionFooter
                mode={connection.mode}
                onOpenSettings={onOpenSettings}
                state={state.connection}
              />
            )}
            presentation="desktop"
            store={store}
          />
        </div>
        <div className="bcd-sidebar-rail">
          <ConsoleSidebar collapsed presentation="desktop" store={store} />
        </div>
        <ConsoleSurface
          connectionDetail={connection.mode === "external" ? (
            <ConnectionDiagnostics
              endpoint={connection.gatewayUrl}
              health={state.health}
              onRetry={store.reconnect}
              state={state.connection}
            />
          ) : null}
          presentation="desktop"
          sourceKind={connection.mode}
          store={store}
        />
      </div>
    </div>
  );
}

function BeaconHeader({
  onOpenSettings,
  settingsButtonRef,
  state,
  store,
}: {
  onOpenSettings: () => void;
  settingsButtonRef: RefObject<HTMLButtonElement>;
  state: ReturnType<typeof useConsoleState>;
  store: ConsoleStore;
}): JSX.Element {
  const { locale, t } = useConsoleI18n();
  const refresh = state.connection === "ready" ? store.refresh : store.reconnect;
  return (
    <header className="bcd-header">
      <div className="bcd-header-brand">
        <span className="bcd-header-mark"><Icon name="beacon" size={28} /></span>
        <strong>Beacon</strong>
      </div>
      <div className="bcd-header-actions">
        <span className={`bcd-health is-${state.connection}`}>
          <span className="bc-status-dot" />
          {state.connection === "ready"
            ? formatRefresh(state.lastRefreshedAt, locale, t("updated"))
            : connectionLabel(state.connection, t)}
        </span>
        <button aria-label={state.refreshing ? t("refreshing") : t("refresh")} className="bcd-header-button" disabled={state.refreshing} onClick={refresh} type="button">
          <Icon name="refresh" size={24} /><span>{state.refreshing ? t("refreshing") : t("refresh")}</span>
        </button>
        <button aria-label={t("settings")} className="bcd-header-button" onClick={onOpenSettings} ref={settingsButtonRef} type="button">
          <Icon name="settings" size={24} /><span>{t("settings")}</span>
        </button>
      </div>
    </header>
  );
}

function SourceBoundary({ mode }: { mode: DesktopMode }): JSX.Element {
  const { t } = useConsoleI18n();
  const synthetic = mode === "fake";
  return (
    <section className={`bcd-source-boundary is-${mode}`} aria-label={t("dataSource")}>
      <Icon name={synthetic ? "help" : "check"} size={20} />
      <span>
        <strong>{synthetic ? t("demoDataset") : t("localGatewayDataset")}</strong>
        <small>{synthetic ? t("fakeNotComputerActivity") : t("externalReadOnlyProjection")}</small>
      </span>
      <span className="bcd-source-badges">
        <span className="bcd-safety-chip">{t("local")}</span>
        <span className="bcd-safety-chip">{t("readOnly")}</span>
      </span>
    </section>
  );
}

function ConnectionFooter({
  mode,
  onOpenSettings,
  state,
}: {
  mode: DesktopMode;
  onOpenSettings: () => void;
  state: ReturnType<typeof useConsoleState>["connection"];
}): JSX.Element {
  const { t } = useConsoleI18n();
  return (
    <div className="bcd-connection-footer">
      <span className="bc-kicker">{t("connection")}</span>
      <button onClick={onOpenSettings} type="button">
        <span className={`bc-status-dot ${state === "ready" ? "is-good" : "is-warn"}`} />
        <span>
          <strong>{mode === "fake" ? t("fake") : t("externalGateway")}</strong>
          <small>{connectionLabel(state, t)}</small>
        </span>
        <Icon name="chevron" />
      </button>
    </div>
  );
}

function ConnectionDiagnostics({
  endpoint,
  health,
  onRetry,
  state,
}: {
  endpoint: string;
  health: ReturnType<typeof useConsoleState>["health"];
  onRetry: () => void;
  state: ReturnType<typeof useConsoleState>["connection"];
}): JSX.Element {
  const { t } = useConsoleI18n();
  const healthy = state === "ready";
  return (
    <section className={`bcd-diagnostics is-${healthy ? "healthy" : "failed"}`} aria-label={t("connectionHealth")}>
      <div className="bcd-diagnostics-heading">
        <span className={`bc-status-dot ${healthy ? "is-good" : "is-warn"}`} />
        <span>
          <strong>{healthy ? t("connected") : t("gatewayDisconnected")}</strong>
          <small>{healthy ? t("gatewayExternalHealthy") : t("noLiveCalls")}</small>
        </span>
        <button onClick={onRetry} type="button">{t("retry")}</button>
      </div>
      <dl>
        <div><dt>{t("dataSource")}</dt><dd>{t("externalGateway")}</dd></div>
        <div><dt>{t("gatewayEndpoint")}</dt><dd><code>{endpoint}</code></dd></div>
        <div><dt>{t("healthBoundary")}</dt><dd>{health === null ? t("waiting") : `${health.consoleSchema} · API ${health.apiVersion} · ${health.status}`}</dd></div>
        <div><dt>{t("settingsBoundaryTitle")}</dt><dd>{t("gatewayBoundary")}</dd></div>
      </dl>
      <p><strong>{t("noLiveCalls")}</strong></p>
    </section>
  );
}

type SettingsSection = "about" | "connection" | "general";

function SettingsPanel({
  application,
  connection,
  onApply,
  onClose,
  resolvedTheme,
}: {
  application: ApplicationSettings;
  connection: ConnectionSettings;
  onApply: (application: ApplicationSettings, connection: ConnectionSettings) => void;
  onClose: () => void;
  resolvedTheme: "dark" | "light";
}): JSX.Element {
  const { t } = useConsoleI18n();
  const [section, setSection] = useState<SettingsSection>("general");
  const [nextApplication, setNextApplication] = useState(application);
  const [nextConnection, setNextConnection] = useState(connection);
  const dialogRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const validation = validateGatewayUrl(nextConnection.gatewayUrl);
  const canApply = nextConnection.mode === "fake" || validation.valid;

  useEffect(() => { closeButtonRef.current?.focus(); }, []);

  const apply = (): void => {
    if (!canApply) {
      return;
    }
    onApply(nextApplication, {
      ...nextConnection,
      gatewayUrl: validation.normalizedUrl ?? connection.gatewayUrl,
    });
  };

  const onDialogKeyDown = (event: React.KeyboardEvent<HTMLElement>): void => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") {
      return;
    }
    const focusable = [...(dialogRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ) ?? [])];
    const first = focusable[0];
    const last = focusable.at(-1);
    if (first === undefined || last === undefined) {
      return;
    }
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div className="bcd-settings-backdrop" data-theme={resolvedTheme} onMouseDown={(event) => {
      if (event.currentTarget === event.target) {
        onClose();
      }
    }}>
      <section
        aria-labelledby="bcd-settings-title"
        aria-modal="true"
        className="bcd-settings"
        onKeyDown={onDialogKeyDown}
        ref={dialogRef}
        role="dialog"
      >
        <header className="bcd-settings-header">
          <div><h2 id="bcd-settings-title">{t("settings")}</h2><p>{t("localPreferences")}</p></div>
          <button aria-label={t("close")} onClick={onClose} ref={closeButtonRef} type="button"><Icon name="close" /></button>
        </header>

        <div className="bcd-settings-body">
          <nav aria-label={t("settings")} className="bcd-settings-nav" role="tablist">
            <SettingsTab active={section === "general"} label={t("general")} onClick={() => { setSection("general"); }} />
            <SettingsTab active={section === "connection"} label={t("connection")} onClick={() => { setSection("connection"); }} />
            <SettingsTab active={section === "about"} label={t("aboutThisView")} onClick={() => { setSection("about"); }} />
          </nav>
          <div className="bcd-settings-content">
            {section === "general" ? (
              <div aria-label={t("general")} className="bcd-settings-section" role="tabpanel">
                <SettingsGroup label={t("language")}>
                  <SegmentedControl
                    onChange={(locale) => { setNextApplication((current) => ({ ...current, locale })); }}
                    options={[
                      { label: "简体中文", value: "zh-CN" },
                      { label: "English (US)", value: "en-US" },
                    ]}
                    value={nextApplication.locale}
                  />
                </SettingsGroup>
                <SettingsGroup label={t("appearance")}>
                  <SegmentedControl
                    onChange={(appearance) => { setNextApplication((current) => ({ ...current, appearance })); }}
                    options={[
                      { label: t("light"), value: "light" },
                      { label: t("dark"), value: "dark" },
                      { label: t("system"), value: "system" },
                    ]}
                    value={nextApplication.appearance}
                  />
                </SettingsGroup>
                <SettingsGroup label={t("contrast")}>
                  <SegmentedControl
                    onChange={(contrast) => { setNextApplication((current) => ({ ...current, contrast })); }}
                    options={[
                      { label: t("standard"), value: "standard" },
                      { label: t("enhanced"), value: "enhanced" },
                    ]}
                    value={nextApplication.contrast}
                  />
                </SettingsGroup>
                <SettingsGroup label={t("fontSize")}>
                  <SegmentedControl<TextScale>
                    onChange={(textScale) => { setNextApplication((current) => ({ ...current, textScale })); }}
                    options={[
                      { label: "90%", value: "90" },
                      { label: "100%", value: "100" },
                      { label: "110%", value: "110" },
                    ]}
                    value={nextApplication.textScale}
                  />
                </SettingsGroup>
              </div>
            ) : null}

            {section === "connection" ? (
              <div aria-label={t("connection")} className="bcd-settings-section" role="tabpanel">
                <SettingsGroup label={t("dataSource")}>
                  <div className="bcd-mode-options">
                    <button aria-pressed={nextConnection.mode === "fake"} onClick={() => { setNextConnection((current) => ({ ...current, mode: "fake" })); }} type="button">
                      <strong>{t("fake")}</strong><span>{t("fakeDescription")}</span>
                    </button>
                    <button aria-pressed={nextConnection.mode === "external"} onClick={() => { setNextConnection((current) => ({ ...current, mode: "external" })); }} type="button">
                      <strong>{t("externalGateway")}</strong><span>{t("externalDescription")}</span>
                    </button>
                  </div>
                </SettingsGroup>
                {nextConnection.mode === "fake" ? (
                  <label className="bcd-field">
                    <span>{t("fakeScenario")}</span>
                    <select
                      onChange={(event) => { setNextConnection((current) => ({ ...current, fakeScenario: event.target.value as FakeScenario })); }}
                      value={nextConnection.fakeScenario}
                    >
                      <ScenarioOption description={t("normalDescription")} label={t("normal")} value="normal" />
                      <ScenarioOption description={t("emptyWorkspacesDescription")} label={t("emptyWorkspaces")} value="empty-workspaces" />
                      <ScenarioOption description={t("emptySessionsDescription")} label={t("emptySessions")} value="empty-sessions" />
                      <ScenarioOption description={t("truncatedDescription")} label={t("truncated")} value="truncated" />
                      <ScenarioOption description={t("rebuildDescription")} label={t("rebuildRequired")} value="rebuild-required" />
                    </select>
                  </label>
                ) : (
                  <>
                    <label className="bcd-field">
                      <span>{t("gatewayEndpoint")}</span>
                      <input
                        aria-describedby="bcd-url-help"
                        onChange={(event) => { setNextConnection((current) => ({ ...current, gatewayUrl: event.target.value })); }}
                        spellCheck={false}
                        type="url"
                        value={nextConnection.gatewayUrl}
                      />
                    </label>
                    <p className={validation.valid ? "bcd-url-help is-valid" : "bcd-url-help is-invalid"} id="bcd-url-help">
                      {t(validationCopyKey(validation.code))}
                    </p>
                  </>
                )}
                <div className="bcd-settings-boundary">
                  <strong>{t("settingsBoundaryTitle")}</strong>
                  <span>{t("settingsBoundaryDescription")}</span>
                </div>
              </div>
            ) : null}

            {section === "about" ? (
              <div aria-label={t("aboutThisView")} className="bcd-settings-section bcd-about" role="tabpanel">
                <Icon name="beacon" />
                <h3>{t("aboutThisView")}</h3>
                <p>{t("settingsAboutDescription")}</p>
                <p>{t("settingsStoredDescription")}</p>
                <dl>
                  <div><dt>Schema</dt><dd>beacon.console.v1</dd></div>
                  <div><dt>{t("availableInView")}</dt><dd>{t("viewOnly")}</dd></div>
                </dl>
              </div>
            ) : null}
          </div>
        </div>

        <div className="bcd-settings-note"><Icon name="check" /><span>{t("onlyPreferencesSaved")}</span></div>
        <footer>
          <button onClick={onClose} type="button">{t("cancel")}</button>
          <button className="is-primary" disabled={!canApply} onClick={apply} type="button">{t("savePreferences")}</button>
        </footer>
      </section>
    </div>
  );
}

function SettingsTab({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }): JSX.Element {
  return <button aria-selected={active} onClick={onClick} role="tab" type="button">{label}</button>;
}

function SettingsGroup({ children, label }: { children: React.ReactNode; label: string }): JSX.Element {
  return <fieldset className="bcd-settings-group"><legend>{label}</legend>{children}</fieldset>;
}

function SegmentedControl<T extends string>({
  onChange,
  options,
  value,
}: {
  onChange: (value: T) => void;
  options: Array<{ label: string; value: T }>;
  value: T;
}): JSX.Element {
  return (
    <div className="bcd-segmented">
      {options.map((option) => (
        <button aria-pressed={value === option.value} key={option.value} onClick={() => { onChange(option.value); }} type="button">
          {option.label}
        </button>
      ))}
    </div>
  );
}

function ScenarioOption({ description, label, value }: { description: string; label: string; value: FakeScenario }): JSX.Element {
  return <option value={value}>{label} — {description}</option>;
}

type Copy = ReturnType<typeof useConsoleI18n>["t"];

const connectionLabel = (
  state: ReturnType<typeof useConsoleState>["connection"],
  t: Copy,
): string => {
  const labels = {
    idle: t("waiting"),
    loading: t("loading"),
    ready: t("connected"),
    disconnected: t("gatewayDisconnected"),
    permission: t("permissionDenied"),
    protocol: t("protocolFailed"),
    version: t("versionFailed"),
    timeout: t("timeout"),
    error: t("unavailable"),
  } as const;
  return labels[state];
};

const validationCopyKey = (code: GatewayValidationCode): Parameters<Copy>[0] => {
  const keys = {
    accepted: "gatewayHelpAccepted",
    host: "gatewayHelpHost",
    http: "gatewayHelpHttp",
    origin: "gatewayHelpOrigin",
    parse: "gatewayHelpParse",
    port: "gatewayHelpPort",
    userinfo: "gatewayHelpUserInfo",
  } as const;
  return keys[code];
};

const formatRefresh = (value: string | null, locale: string, updated: string): string => {
  if (value === null) {
    return updated;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) {
    return updated;
  }
  return `${updated} ${new Intl.DateTimeFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(parsed)}`;
};
