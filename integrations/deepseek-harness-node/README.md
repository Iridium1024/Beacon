# Optional DeepSeek Harness Node carrier

This private package pins the official DeepSeek Harness JSON-RPC runtime used by
Beacon's `deepseek_harness_sdk_stdio` backend. It is never installed globally or
automatically. Install it explicitly in this directory with `npm ci`; Beacon
preflight rejects missing, floating, or mismatched package versions.

The checked-in `cordis.yml` follows the official unattended JSON-RPC composition
at commit `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`. Its thin
`beacon-sdk-jsonrpc-server.mjs` adapter selects the official `create` or
`ctx.agents.resume({resumeSessionId})` path before initialization succeeds.
`session-probe.mjs` performs exact header-only lookup through the official JSONL
persistence service. The runtime reads credentials from its own approved
runtime home/environment. Beacon does not copy, print, or persist them.

`cordis.offline-test.yml` and `fixtures/fake-llm-adapter.mjs` are test-only.
They keep official runtime/session persistence while replacing network model
access with deterministic history evidence.

Windows uses this Node 22.19+ route. The official PyPI carrier is accepted only on
the OS/architecture combinations for which the pinned runtime wheel is published.
Neither route is enabled by default, and this repository has not run an
authenticated real-model smoke test for the backend.
