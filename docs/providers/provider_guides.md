# Provider guides

Already joined? Use [daily CLI](../agent/agent_entry.md) or
[daily MCP](../agent/agent_mcp.md). Read a provider guide only to configure or
troubleshoot that provider. First-time project setup is in [setup](../agent/agent_setup.md).

| Provider / task | Guide |
|---|---|
| Codex CLI or app-server; status and explicit current-turn supplement | [Codex](codex_registered_session_activation.md) |
| Claude CLI or optional Agent SDK | [Claude](claude_registered_session_activation.md) |
| Hermes CLI or optional TUI Gateway | [Hermes](hermes_registered_session_activation.md) |
| DSH exact join, new session, stop/resume | [DeepSeek Harness](deepseek_harness_managed_runtime.md) |
| Missing executable or capability | [Preflight](agent_runtime_preflight.md) |

Use only approved sessions and permissions. Beacon does not log in to provider
accounts, store credentials or take over arbitrary live desktop/TUI sessions.
Default replies: Codex and SDK/Gateway routes are explicit; Claude/Hermes CLI
and DSH retain provider-final capture. Follow the selected profile/delivered
policy, not an assumption based on the provider name alone.

Advanced references, not onboarding prerequisites:
[backend contract](../agent/provider_backend_contract.md),
[upstream interface comparison](provider_programmatic_interfaces.md).
