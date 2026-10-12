# Defaults

Provider control defaults are deliberately conservative:

- Claude activation backend: `cli`.
- Claude CLI reply writeback: `provider_final_capture` for compatibility.
- Claude Agent SDK reply writeback: `explicit_only`.
- No automatic fallback between `claude_agent_sdk` and `claude_cli`.

The Agent SDK dependency is optional and is never installed by runtime
preflight. Missing or unsupported SDK versions fail before ticket delivery.
Supported older versions may omit newer result-error, conversation-reset, and
origin types without failing preflight. When present, those signals are handled
fail-closed; the `0.2.144` compatibility audit did not change the default
backend or constitute an authenticated provider smoke.
