# Beacon Python Core

This package provides Beacon's local Python runtime. Install it from the
standalone Beacon repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .\python-core
.\.venv\Scripts\beacon.exe --help
```

On Linux/macOS, use `python3.11`, `./.venv/bin/python`, and
`./.venv/bin/beacon` instead.

The editable install supplies PyYAML and the `beacon` console command. The
compatible module entrypoint remains available as
`python -m agent_os.local_runtime`.

The opt-in Claude Agent SDK backend uses an optional dependency:

```powershell
py -3.11 -m pip install -e ".\python-core[claude-agent-sdk]"
```

The supported SDK range is `>=0.2.127,<0.3.0`. The default `claude_cli`
backend does not require this extra. Runtime preflight never installs or repairs
the package and never starts a real Claude session. The compatibility layer was
audited against the public `0.2.144` shape and detects its newer result-error,
conversation-reset, and result-origin signals optionally; `0.2.144` is not the
minimum version. No authenticated Claude provider/session smoke was performed
as part of that audit.

The opt-in Hermes `tui_gateway` backend is an external-runtime integration; it
does not install Hermes into Beacon. Read-only preflight requires the selected
Python interpreter to expose the exact stable `hermes-agent==0.19.0` Gateway
shape and launches it with `python -u -m tui_gateway.entry`. Local `0.18.0`,
the current upstream-main `0.20.5` shape, and unknown versions fail closed.
The default `cli` backend remains the rollback route. No authenticated Hermes
provider/session smoke was performed as part of this implementation.

Run the canonical regression suite from the Beacon repository root:

```powershell
py -3.11 -m unittest discover -s python-core\tests
```

The tests use local fakes and temporary files. They do not require a provider
credential, live provider session, or the outer development workspace.

## License

This package is licensed under the [Apache License 2.0](LICENSE). Copyright
2026 Beacon contributors.
