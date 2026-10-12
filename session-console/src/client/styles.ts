export const CONSOLE_STYLE_ID = "beacon-session-console-v1";

export const CONSOLE_STYLES = String.raw`
.bc-sidebar,.bc-surface{box-sizing:border-box;--bc-canvas:#f3f1ec;--bc-surface:#fbfaf7;--bc-panel:#fffefa;--bc-panel-soft:#f7f4ef;--bc-ink:#292724;--bc-ink-soft:#494640;--bc-muted:#6f6962;--bc-border:#d9d3c9;--bc-border-strong:#bdb5aa;--bc-accent:#746497;--bc-accent-soft:#eee9f5;--bc-good:#2f7b60;--bc-good-soft:#e3f0ea;--bc-warn:#a06b2c;--bc-warn-soft:#f7ead5;--bc-danger:#994e49;--bc-danger-soft:#f5e2df;--bc-focus:#5c49a2;--bc-font:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--bc-ink);font-family:var(--bc-font);font-size:14px;line-height:1.48}
.bc-sidebar[data-theme="dark"],.bc-surface[data-theme="dark"]{--bc-canvas:#242321;--bc-surface:#292825;--bc-panel:#302e2b;--bc-panel-soft:#34322f;--bc-ink:#f1eee8;--bc-ink-soft:#d1cbc1;--bc-muted:#aaa399;--bc-border:#48453f;--bc-border-strong:#68635b;--bc-accent:#b1a0d2;--bc-accent-soft:#3d3747;--bc-good:#75bd9e;--bc-good-soft:#293b34;--bc-warn:#dfad67;--bc-warn-soft:#463a29;--bc-danger:#dd8d84;--bc-danger-soft:#4a302e;--bc-focus:#c0aaff}
.bc-sidebar[data-contrast="high"],.bc-surface[data-contrast="high"]{--bc-border:var(--bc-border-strong);--bc-muted:var(--bc-ink-soft)}
.bc-sidebar *,.bc-surface *{box-sizing:border-box}
.bc-sidebar button,.bc-sidebar select,.bc-surface button,.bc-surface select{font:inherit}
.bc-sidebar button:focus-visible,.bc-sidebar select:focus-visible,.bc-surface button:focus-visible,.bc-surface select:focus-visible,.bc-surface summary:focus-visible{outline:3px solid var(--bc-focus);outline-offset:2px}
.bc-sidebar svg,.bc-surface svg{display:block;flex:none}
.bc-sidebar{align-self:stretch;background:var(--bc-canvas);border-right:1px solid var(--bc-border);display:flex;flex-direction:column;height:100%;min-height:0;overflow:hidden;padding:18px 14px 14px;width:100%}
.bc-brand{align-items:center;display:flex;gap:11px;padding:1px 7px 18px}
.bc-brand strong{display:block;font-size:17px;letter-spacing:-.02em}
.bc-brand small{color:var(--bc-muted);display:block;font-size:12px;letter-spacing:.06em;text-transform:uppercase}
.bc-mark{align-items:center;background:var(--bc-accent);border-radius:10px;color:#fff;display:inline-flex;height:36px;justify-content:center;min-width:36px;width:36px}
.bc-sidebar-section{border-top:1px solid var(--bc-border);padding:15px 3px 2px}
.bc-kicker,.bc-eyebrow{color:var(--bc-muted);display:block;font-size:11px;font-weight:750;letter-spacing:.09em;text-transform:uppercase}
.bc-select-wrap{align-items:center;background:var(--bc-panel);border:1px solid var(--bc-border);border-radius:10px;display:flex;gap:8px;margin-top:8px;padding:0 9px}
.bc-select-wrap svg{color:var(--bc-accent)}
.bc-select-wrap select{appearance:auto;background:var(--bc-panel);border:0;color:var(--bc-ink);cursor:pointer;min-height:42px;min-width:0;padding:0 4px;width:100%}
.bc-provider-list{display:grid;gap:4px;margin-top:8px}
.bc-provider-row{align-items:center;background:transparent;border:1px solid transparent;border-radius:9px;color:var(--bc-ink-soft);cursor:pointer;display:grid;gap:9px;grid-template-columns:30px minmax(0,1fr) auto;min-height:40px;padding:6px 8px;text-align:left;width:100%}
.bc-provider-row:hover{background:var(--bc-panel-soft);border-color:var(--bc-border)}
.bc-provider-row:active{transform:translateY(1px)}
.bc-provider-row.is-active{background:var(--bc-accent-soft);border-color:color-mix(in srgb,var(--bc-accent) 36%,var(--bc-border));color:var(--bc-ink)}
.bc-provider-monogram{align-items:center;background:var(--bc-panel-soft);border:1px solid var(--bc-border);border-radius:7px;color:var(--bc-muted);display:inline-flex;font-size:11px;font-weight:800;height:28px;justify-content:center;letter-spacing:.02em;min-width:28px;padding:0 4px}
.bc-provider-row.is-active .bc-provider-monogram{background:var(--bc-panel);color:var(--bc-accent)}
.bc-count{color:var(--bc-muted);font-variant-numeric:tabular-nums}
.bc-session-section{display:flex;flex:1;flex-direction:column;min-height:0}
.bc-session-list{display:grid;gap:5px;margin-top:8px;overflow:auto;padding:1px 2px 1px 0}
.bc-session-row{align-items:start;background:transparent;border:1px solid transparent;border-radius:10px;color:var(--bc-ink);cursor:pointer;display:grid;gap:5px 8px;grid-template-columns:30px minmax(0,1fr);grid-template-rows:auto auto;min-height:70px;padding:8px;text-align:left;width:100%}
.bc-session-row:hover{background:var(--bc-panel-soft);border-color:var(--bc-border)}
.bc-session-row.is-selected{background:var(--bc-accent-soft);border-color:var(--bc-accent);box-shadow:inset 3px 0 0 var(--bc-accent)}
.bc-session-copy{min-width:0}
.bc-session-copy strong{display:block;font-size:13px}
.bc-session-copy small{color:var(--bc-ink-soft);display:block;font:12px/1.35 ui-monospace,SFMono-Regular,Consolas,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bc-session-copy>span{color:var(--bc-muted);display:block;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bc-session-meta{align-items:center;display:flex;gap:8px;grid-column:2;color:var(--bc-muted);font-size:11px;justify-content:space-between}
.bc-session-meta>span{align-items:center;display:inline-flex;gap:5px}
.bc-session-meta time{font-variant-numeric:tabular-nums}
.bc-status-dot{background:var(--bc-muted);border-radius:50%;display:inline-block;height:7px;min-width:7px;width:7px}
.bc-status-dot.is-good,.bc-state-chip.is-good .bc-status-dot{background:var(--bc-good);box-shadow:0 0 0 3px color-mix(in srgb,var(--bc-good) 14%,transparent)}
.bc-status-dot.is-warn,.bc-state-chip.is-warn .bc-status-dot{background:var(--bc-warn)}
.bc-status-dot.is-muted,.bc-state-chip.is-muted .bc-status-dot{background:var(--bc-muted)}
.bc-sidebar-footer{border-top:1px solid var(--bc-border);display:grid;gap:10px;margin-top:12px;padding:13px 3px 0}
.bc-authority-note{align-items:center;display:grid;gap:8px;grid-template-columns:auto 1fr;padding:0 6px}
.bc-authority-note strong,.bc-authority-note small{display:block;font-size:12px}.bc-authority-note small{color:var(--bc-muted)}
.bc-appearance{background:var(--bc-panel-soft);border:1px solid var(--bc-border);border-radius:9px;display:grid;grid-template-columns:repeat(3,1fr);padding:3px}
.bc-appearance button,.bc-contrast-button{background:transparent;border:0;border-radius:6px;color:var(--bc-muted);cursor:pointer;font-size:12px;padding:6px 3px}
.bc-appearance button[aria-pressed="true"]{background:var(--bc-panel);box-shadow:0 1px 3px rgba(0,0,0,.08);color:var(--bc-ink)}
.bc-contrast-button{text-align:center}
.bc-sidebar--collapsed{align-items:center;gap:8px;padding:14px 8px;width:64px}
.bc-rail-button{background:transparent;border:1px solid var(--bc-border);border-radius:8px;color:var(--bc-muted);cursor:pointer;font-size:11px;font-weight:800;height:38px;width:42px}
.bc-rail-button.is-active{background:var(--bc-accent-soft);border-color:var(--bc-accent);color:var(--bc-accent)}
.bc-surface{background:var(--bc-surface);height:100%;min-height:0;overflow:auto;width:100%}
.bc-topbar{align-items:center;background:var(--bc-surface);border-bottom:1px solid var(--bc-border);display:flex;gap:20px;justify-content:space-between;min-height:76px;padding:14px clamp(18px,2.4vw,34px);position:sticky;top:0;z-index:20}
.bc-topbar h1{font-size:20px;letter-spacing:-.025em;line-height:1.2;margin:2px 0}.bc-topbar p{color:var(--bc-muted);font-size:13px;margin:0}
.bc-topbar-actions{align-items:center;display:flex;gap:9px;min-width:0}
.bc-readonly-chip{align-items:center;background:var(--bc-good-soft);border:1px solid color-mix(in srgb,var(--bc-good) 35%,var(--bc-border));border-radius:99px;color:var(--bc-good);display:flex;font-size:12px;font-weight:800;gap:7px;letter-spacing:.05em;padding:6px 9px;white-space:nowrap}
.bc-refreshed{color:var(--bc-muted);font-size:12px;white-space:nowrap}
.bc-refresh-button{align-items:center;background:var(--bc-panel);border:1px solid var(--bc-border-strong);border-radius:9px;color:var(--bc-ink);cursor:pointer;display:flex;font-weight:650;gap:7px;min-height:40px;padding:8px 11px}
.bc-refresh-button:hover{border-color:var(--bc-accent);color:var(--bc-accent)}.bc-refresh-button:active{transform:translateY(1px)}.bc-refresh-button:disabled{cursor:wait;opacity:.6}
.bc-authority-banner{align-items:center;background:var(--bc-accent-soft);border-bottom:1px solid color-mix(in srgb,var(--bc-accent) 25%,var(--bc-border));color:var(--bc-ink-soft);display:flex;font-size:12px;gap:9px;min-height:40px;padding:8px clamp(18px,2.4vw,34px)}
.bc-authority-banner svg{color:var(--bc-accent)}.bc-banner-boundary{color:var(--bc-muted);margin-left:auto}
.bc-connection-notice{align-items:center;border-bottom:1px solid var(--bc-border);display:flex;gap:12px;padding:10px clamp(18px,2.4vw,34px)}
.bc-connection-notice strong,.bc-connection-notice span{font-size:13px}.bc-connection-notice span{color:var(--bc-muted)}
.bc-connection-notice.is-loading{background:var(--bc-accent-soft)}.bc-connection-notice.is-disconnected,.bc-connection-notice.is-error{background:var(--bc-danger-soft)}.bc-connection-notice.is-permission,.bc-connection-notice.is-protocol,.bc-connection-notice.is-version{background:var(--bc-warn-soft)}
.bc-content-grid{display:grid;gap:22px;grid-template-columns:minmax(0,1fr) minmax(270px,320px);margin:0 auto;max-width:1500px;padding:24px clamp(18px,2.4vw,34px) 40px}
.bc-primary,.bc-secondary{min-width:0}.bc-secondary{display:grid;align-content:start;gap:10px;padding-top:67px}
.bc-context-heading{align-items:flex-end;display:flex;gap:20px;justify-content:space-between;margin-bottom:18px}
.bc-context-heading h1{font-size:28px;letter-spacing:-.035em;line-height:1.1;margin:4px 0}.bc-context-heading p{color:var(--bc-muted);font-size:13px;margin:0;max-width:680px}
.bc-context-count{background:var(--bc-panel);border:1px solid var(--bc-border);border-radius:99px;color:var(--bc-muted);flex:none;font-size:12px;font-variant-numeric:tabular-nums;padding:5px 9px;white-space:nowrap}
.bc-mobile-session-nav{display:none}
.bc-session-detail{background:var(--bc-panel);border:1px solid var(--bc-border);border-radius:14px;box-shadow:0 8px 24px rgba(63,55,45,.05);overflow:hidden}
.bc-session-hero{align-items:center;background:linear-gradient(120deg,var(--bc-panel),color-mix(in srgb,var(--bc-accent-soft) 50%,var(--bc-panel)));border-bottom:1px solid var(--bc-border);display:grid;gap:14px;grid-template-columns:auto minmax(0,1fr) auto;padding:20px}
.bc-provider-emblem{align-items:center;background:var(--bc-accent-soft);border:1px solid color-mix(in srgb,var(--bc-accent) 42%,var(--bc-border));border-radius:12px;color:var(--bc-accent);display:flex;font-size:13px;font-weight:850;height:46px;justify-content:center;min-width:46px;padding:0 7px}
.bc-session-hero h2{font-size:23px;letter-spacing:-.025em;line-height:1.2;margin:4px 0}.bc-session-hero h2 span{overflow-wrap:anywhere}.bc-session-hero p{color:var(--bc-muted);font-size:13px;margin:0}
.bc-session-hero-actions{align-items:flex-end;display:flex;flex-direction:column;gap:6px}
.bc-state-chip{align-items:center;background:var(--bc-panel);border:1px solid var(--bc-border);border-radius:99px;color:var(--bc-ink-soft);display:inline-flex;font-size:12px;font-weight:700;gap:7px;padding:6px 10px;white-space:nowrap}
.bc-clear-selection{background:transparent;border:0;border-radius:6px;color:var(--bc-muted);cursor:pointer;font-size:12px;padding:3px 5px}.bc-clear-selection:hover{background:var(--bc-panel-soft);color:var(--bc-accent)}.bc-clear-selection:active{transform:translateY(1px)}
.bc-detail-groups{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}
.bc-detail-groups>section{min-width:0;padding:18px 20px}.bc-detail-groups>section:nth-child(2n){border-left:1px solid var(--bc-border)}.bc-detail-groups>section:nth-child(n+3){border-top:1px solid var(--bc-border)}
.bc-detail-groups h3{align-items:center;display:flex;font-size:15px;gap:8px;margin:0 0 11px}.bc-detail-groups h3 svg{color:var(--bc-accent)}
.bc-detail-groups dl{margin:0}.bc-detail-groups dl>div{display:grid;gap:12px;grid-template-columns:minmax(118px,.75fr) minmax(0,1.25fr);padding:8px 0}.bc-detail-groups dl>div+div{border-top:1px solid color-mix(in srgb,var(--bc-border) 74%,transparent)}
.bc-detail-groups dt{color:var(--bc-muted);font-size:12px}.bc-detail-groups dd{font-size:13px;font-weight:650;margin:0;min-width:0;overflow-wrap:anywhere}.bc-detail-groups dd.is-mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px}.bc-detail-groups dd small{color:var(--bc-muted);display:block;font-family:var(--bc-font);font-size:12px;font-weight:400;line-height:1.45;margin-top:3px}
.bc-disclosure{background:var(--bc-panel);border:1px solid var(--bc-border);border-radius:12px;overflow:hidden}
.bc-disclosure>summary{align-items:center;cursor:pointer;display:grid;gap:8px;grid-template-columns:minmax(0,1fr) auto auto;list-style:none;min-height:62px;padding:12px 14px}.bc-disclosure>summary::-webkit-details-marker{display:none}
.bc-disclosure>summary>span:first-child{align-items:center;display:flex;gap:10px;min-width:0}.bc-disclosure>summary>span:first-child>svg{color:var(--bc-accent)}.bc-disclosure>summary strong,.bc-disclosure>summary small{display:block}.bc-disclosure>summary strong{font-size:13px}.bc-disclosure>summary small{color:var(--bc-muted);font-size:12px;font-weight:400;line-height:1.35;margin-top:2px}
.bc-disclosure>summary:hover{color:var(--bc-accent)}.bc-disclosure>summary:active{transform:translateY(1px)}.bc-disclosure>summary>svg:last-child{color:var(--bc-muted);transition:transform .16s ease}.bc-disclosure[open]>summary>svg:last-child{transform:rotate(180deg)}
.bc-disclosure-meta{color:var(--bc-muted);font-size:12px;font-variant-numeric:tabular-nums;white-space:nowrap}
.bc-activity-projection{margin-top:14px}.bc-scope-note{background:var(--bc-accent-soft);border-top:1px solid var(--bc-border);color:var(--bc-ink-soft);font-size:12px;margin:0;padding:10px 14px}
.bc-inline-warning{background:var(--bc-warn-soft);border-top:1px solid color-mix(in srgb,var(--bc-warn) 25%,var(--bc-border));color:var(--bc-warn);font-size:12px;padding:9px 14px}
.bc-timeline{border-top:1px solid var(--bc-border);list-style:none;margin:0;max-height:520px;overflow:auto;padding:0}
.bc-event{align-items:center;border-bottom:1px solid var(--bc-border);display:grid;gap:10px;grid-template-columns:88px minmax(0,1fr) 76px;padding:12px 14px;position:relative}.bc-event:last-child{border-bottom:0}
.bc-event time{color:var(--bc-muted);font:12px/1.2 ui-monospace,SFMono-Regular,Consolas,monospace;text-align:right}
.bc-category{border:1px solid var(--bc-border);border-radius:99px;color:var(--bc-muted);font-size:11px;font-weight:800;letter-spacing:.04em;overflow:hidden;padding:3px 7px;text-align:center;text-overflow:ellipsis;text-transform:uppercase;white-space:nowrap}
.bc-category-identity{background:var(--bc-accent-soft);color:var(--bc-accent)}.bc-category-session{background:var(--bc-good-soft);color:var(--bc-good)}.bc-category-dispatch{background:var(--bc-warn-soft);color:var(--bc-warn)}.bc-category-runtime{background:var(--bc-danger-soft);color:var(--bc-danger)}
.bc-event-copy{min-width:0}.bc-event-copy strong,.bc-event-copy small{display:block}.bc-event-copy strong{font-size:13px}.bc-event-copy small{color:var(--bc-muted);font-size:12px}
.bc-event-technical{grid-column:2/-1}.bc-event-technical summary{color:var(--bc-muted);cursor:pointer;font-size:12px;width:max-content}.bc-event-technical dl{background:var(--bc-panel-soft);border-radius:8px;display:grid;gap:5px;margin:8px 0 0;padding:9px}.bc-event-technical dl div{display:grid;gap:8px;grid-template-columns:110px minmax(0,1fr)}.bc-event-technical dt{color:var(--bc-muted);font-size:11px}.bc-event-technical dd{font:11px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;margin:0;overflow-wrap:anywhere}
.bc-term-grid,.bc-interface-compare,.bc-dispatch-list{border-top:1px solid var(--bc-border);margin:0;padding:12px 14px}.bc-term-grid{display:grid;gap:12px}.bc-term-grid div+div{border-top:1px solid var(--bc-border);padding-top:10px}.bc-term-grid dt{font-size:13px;font-weight:750}.bc-term-grid dd{color:var(--bc-muted);font-size:12px;line-height:1.5;margin:3px 0 0}
.bc-dispatch-list div{display:grid;gap:8px;grid-template-columns:minmax(0,.8fr) minmax(0,1.2fr);padding:8px 0}.bc-dispatch-list div+div{border-top:1px solid var(--bc-border)}.bc-dispatch-list dt,.bc-dispatch-list dd{font:11px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere}.bc-dispatch-list dd{margin:0}.bc-dispatch-list dd small{color:var(--bc-muted);display:block;font-family:var(--bc-font);font-size:12px;margin-top:3px}
.bc-capability-detail{border-top:1px solid var(--bc-border);padding:14px}.bc-capability-detail h3{font-size:15px;margin:0}.bc-capability-detail>p{color:var(--bc-muted);font-size:12px;margin:3px 0 12px}
.bc-interface-compare{background:var(--bc-panel-soft);border:1px solid var(--bc-border);border-radius:8px}.bc-interface-compare div{display:grid;gap:7px;grid-template-columns:105px minmax(0,1fr);padding:4px 0}.bc-interface-compare dt{color:var(--bc-muted);font-size:11px}.bc-interface-compare dd{font-size:12px;margin:0;overflow-wrap:anywhere}
.bc-capability-facts{display:grid;gap:6px;grid-template-columns:repeat(2,minmax(0,1fr));margin-top:10px}.bc-capability-facts span{align-items:center;border:1px solid var(--bc-border);border-radius:7px;color:var(--bc-muted);display:flex;font-size:12px;justify-content:space-between;padding:6px 7px}.bc-capability-facts strong{font-size:12px}.bc-capability-facts .is-yes strong{color:var(--bc-good)}.bc-capability-facts .is-unknown strong{color:var(--bc-warn)}
.bc-view-only-note{background:var(--bc-accent-soft);border-radius:8px;color:var(--bc-ink-soft)!important;padding:8px 9px}.bc-limitations ul{border-top:1px solid var(--bc-border);color:var(--bc-muted);display:grid;font-size:12px;gap:8px;margin:0;padding:13px 29px 15px}
.bc-empty-copy{color:var(--bc-muted);font-size:12px;margin:0;padding:14px;text-align:center}.bc-no-session,.bc-empty-surface{align-items:center;display:flex;flex-direction:column;justify-content:center;min-height:320px;padding:40px;text-align:center}.bc-no-session{background:var(--bc-panel);border:1px solid var(--bc-border);border-radius:14px}.bc-no-session svg,.bc-empty-icon,.bc-loader{color:var(--bc-accent)}.bc-no-session h2,.bc-empty-surface h1{font-size:20px;margin:13px 0 5px}.bc-no-session p,.bc-empty-surface p{color:var(--bc-muted);font-size:13px;margin:0;max-width:480px}.bc-empty-icon,.bc-loader{align-items:center;background:var(--bc-accent-soft);border:1px solid var(--bc-border);border-radius:50%;display:flex;height:48px;justify-content:center;width:48px}.bc-loader svg{animation:bc-pulse 1.4s ease-in-out infinite}
@keyframes bc-pulse{0%,100%{opacity:.35}50%{opacity:1}}
@media(max-width:1100px){.bc-content-grid{grid-template-columns:minmax(0,1fr) 280px}.bc-refreshed{display:none}.bc-detail-groups{grid-template-columns:1fr}.bc-detail-groups>section:nth-child(2n){border-left:0}.bc-detail-groups>section:nth-child(n+2){border-top:1px solid var(--bc-border)}}
@media(max-width:820px){.bc-content-grid{display:block}.bc-secondary{padding-top:16px}.bc-banner-boundary{display:none}.bc-topbar{align-items:flex-start;flex-direction:column}.bc-topbar-actions{flex-wrap:wrap}}
@media(max-width:620px){.bc-authority-banner{padding:8px 14px}.bc-content-grid{padding:18px 14px 30px}.bc-context-heading{align-items:flex-start}.bc-context-heading h1{font-size:25px}.bc-context-count{margin-top:18px}.bc-mobile-session-nav{display:block;margin-bottom:14px}.bc-mobile-select-grid{display:grid;gap:10px;grid-template-columns:1fr}.bc-mobile-select-grid label{display:grid;gap:5px}.bc-mobile-select-grid label>span{color:var(--bc-muted);font-size:11px;font-weight:750;letter-spacing:.06em;text-transform:uppercase}.bc-mobile-select-grid select{appearance:auto;background:var(--bc-panel);border:1px solid var(--bc-border-strong);border-radius:10px;color:var(--bc-ink);min-height:44px;padding:0 10px;width:100%}.bc-mobile-session-list{display:grid;gap:7px;margin-top:12px;max-height:132px;overflow:auto;padding-right:2px}.bc-mobile-session-list button{align-items:center;background:var(--bc-panel);border:1px solid var(--bc-border);border-radius:10px;color:var(--bc-ink);display:flex;justify-content:space-between;min-height:58px;padding:8px 11px;text-align:left;width:100%}.bc-mobile-session-list button.is-selected{background:var(--bc-accent-soft);border-color:var(--bc-accent)}.bc-mobile-session-list strong,.bc-mobile-session-list small{display:block}.bc-mobile-session-list strong{font-size:13px}.bc-mobile-session-list small{color:var(--bc-muted);font:12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace}.bc-mobile-session-list time{color:var(--bc-muted);font-size:11px;margin-left:10px;text-align:right}.bc-session-hero{align-items:start;grid-template-columns:auto minmax(0,1fr);padding:16px}.bc-session-hero h2{font-size:19px}.bc-session-hero-actions{align-items:center;flex-direction:row;grid-column:1/-1}.bc-detail-groups>section{padding:16px}.bc-detail-groups dl>div{grid-template-columns:1fr}.bc-detail-groups dd{margin-top:-6px}.bc-disclosure>summary{min-height:66px;padding:12px}.bc-disclosure>summary small{font-size:11px}.bc-disclosure-meta{display:none}.bc-event{grid-template-columns:78px minmax(0,1fr) 60px;padding:11px}.bc-event-technical{grid-column:1/-1}.bc-event time{font-size:11px}.bc-category{font-size:10.5px}.bc-secondary{display:grid;gap:9px}.bc-topbar{padding:12px 14px}}
@media(prefers-reduced-motion:reduce){.bc-sidebar *,.bc-surface *{animation-duration:.001ms!important;animation-iteration-count:1!important;scroll-behavior:auto!important;transition-duration:.001ms!important}}
@media(prefers-reduced-transparency:reduce){.bc-session-hero{background:var(--bc-panel)}.bc-session-detail{box-shadow:none}}
@media(prefers-contrast:more){.bc-sidebar,.bc-surface{--bc-border:var(--bc-border-strong);--bc-muted:var(--bc-ink-soft)}}
`;
