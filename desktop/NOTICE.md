# Notices

Beacon Desktop is an Apache-2.0 Beacon component. Its application code is
original Beacon work.

The validation host uses these directly pinned upstream projects:

- Tauri v2 (`@tauri-apps/cli` 2.11.4, `tauri` 2.11.5,
  `tauri-build` 2.6.3), dual licensed Apache-2.0 OR MIT;
- React and React DOM 18.3.1, MIT;
- Vite 7.3.6, MIT.
- Playwright Test 1.62.1, Apache-2.0 (development and deterministic browser
  validation only; not a product runtime dependency).

Complete resolved npm and Rust dependency versions are recorded in
`package-lock.json` and `src-tauri/Cargo.lock`. Upstream license texts remain
with the respective distributions and registries.

The purple beacon application icon was generated as original P3-B artwork with
OpenAI ImageGen on 2026-08-30. It does not copy the DSH or zixi brand or asset
set. The generated PNG was converted locally into the Windows ICO container;
no third-party icon asset is included.

The Desktop reuses Beacon's own P3-A React components, fixture, protocol, and
styles from `../session-console/src`. The optional DSH/zixi review notices for
that adapter remain in `../session-console/NOTICE.md`; Desktop does not bundle
DSH or zixi source or assets.
