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

Run the canonical regression suite from the Beacon repository root:

```powershell
py -3.11 -m unittest discover -s python-core\tests
```

The tests use local fakes and temporary files. They do not require a provider
credential, live provider session, or the outer development workspace.

## License

This package is licensed under the [Apache License 2.0](LICENSE). Copyright
2026 Beacon contributors.
