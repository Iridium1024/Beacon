from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping, Sequence

from agent_os import __version__
from agent_os.application.services.local_platform_application import (
    LocalPlatformApplication,
)
from agent_os.application.services.provider_session_profile import (
    ProviderSessionRegistry,
    ProviderSessionRegistryPathResolution,
    provider_session_registry_path_resolution,
    resolve_provider_session_registry_path,
)
from agent_os.application.services.agent_runtime_preflight import (
    SUPPORTED_AGENT_RUNTIME_TOOLS,
)
from agent_os.domain.entities.context import ContextUpdateKind
from agent_os.infrastructure.config import (
    LocalPlatformSettings,
    openai_compatible_provider_settings_from_env,
    provider_connection_spec_from_env,
)
from agent_os.stdio import configure_utf8_stdio


CONTEXT_UPDATE_KIND_CHOICES = tuple(kind.value for kind in ContextUpdateKind)

_GLOBAL_OPTIONS_WITH_VALUE = {
    "--agent-adapter-mode",
    "--database",
    "--openai-compatible-api-key-env-var",
    "--openai-compatible-base-url",
    "--openai-compatible-max-tokens",
    "--openai-compatible-model",
    "--openai-compatible-provider-name",
    "--openai-compatible-reasoning-effort",
    "--openai-compatible-temperature",
    "--openai-compatible-thinking-type",
    "--openai-compatible-timeout-seconds",
    "--plugins-directory",
    "--profile",
    "--provider-session-registry",
    "--provider-api-key-env-var",
    "--provider-api-shape",
    "--provider-base-url",
    "--provider-input-mode",
    "--provider-max-tokens",
    "--provider-model",
    "--provider-name",
    "--provider-reasoning-effort",
    "--provider-temperature",
    "--provider-thinking-type",
    "--provider-timeout-seconds",
    "--provider-user-agent",
    "--workspace-root",
}

_NO_RUNTIME_SETTINGS_COMMANDS = {
    "agent-help",
    "provider-session-membership-list",
    "provider-session-profile-deactivate",
    "provider-session-profile-get",
    "provider-session-profile-list",
    "provider-session-profile-register",
}

_WORKSPACE_ID_REQUIRED_COMMANDS = {
    "agent-activation-revoke",
    "agent-activation-status",
    "agent-activation-wake",
    "agent-create",
    "agent-dispatch-create",
    "agent-dispatch-daemon-start",
    "agent-dispatch-daemon-status",
    "agent-dispatch-lease-acquire",
    "agent-dispatch-lease-reconcile",
    "agent-dispatch-lease-release",
    "agent-dispatch-list",
    "agent-dispatch-send",
    "agent-dispatch-status",
    "agent-dispatch-worker-run-once",
    "agent-endpoint-deactivate",
    "agent-endpoint-get",
    "agent-endpoint-identity",
    "agent-endpoint-list",
    "agent-endpoint-login",
    "agent-endpoint-login-discovered",
    "agent-endpoint-status",
    "agent-onboarding-status",
    "agent-provider-onboard",
    "provider-session-workspace-join",
    "provider-session-workspace-leave",
    "agent-exchange-request-close",
    "agent-exchange-request-create",
    "agent-exchange-request-get",
    "agent-exchange-request-list",
    "agent-exchange-request-policy",
    "agent-exchange-request-policy-update",
    "agent-exchange-request-respond",
    "agent-exchange-status",
    "agent-exchange-thread-close",
    "agent-exchange-thread-follow-up-create",
    "agent-exchange-thread-get",
    "agent-exchange-thread-list",
    "agent-exchange-thread-requests",
    "agent-exchange-thread-visibility-update",
    "agent-exchange-wake-watch",
    "agent-provider-runtime-status",
    "agent-runtime-permission-get",
    "agent-runtime-permissions",
    "agent-session-handle-register-discovered",
    "agent-wake-daemon",
    "agent-wake-delivery-list",
    "agent-wake-status",
    "agent-wake-ticket-get",
    "claude-registered-session-activate",
    "claude-session-handle-deactivate",
    "claude-session-handle-get",
    "claude-session-handle-list",
    "claude-session-handle-register",
    "codex-registered-session-activate",
    "codex-session-handle-deactivate",
    "codex-session-handle-get",
    "codex-session-handle-list",
    "codex-session-handle-register",
    "context-append",
    "context-get",
    "context-update-get",
    "context-updates",
    "conversation-archive",
    "conversation-create",
    "conversation-get",
    "conversation-list",
    "conversation-message-append",
    "conversation-messages",
    "agent-delegated-wake-grant-consume",
    "agent-delegated-wake-grant-create",
    "agent-delegated-wake-grant-revoke",
    "agent-delegated-wake-grant-status",
    "hermes-registered-session-activate",
    "hermes-session-handle-deactivate",
    "hermes-session-handle-get",
    "hermes-session-handle-list",
    "hermes-session-handle-register",
    "invoke",
    "project-directory-coordination-complete",
    "project-directory-coordination-declare",
    "project-directory-coordination-status",
    "project-directory-coordination-update",
    "records-file-operations",
    "records-invocations",
    "session-timeline",
    "workspace-archive",
    "workspace-open",
}


def main(argv: Sequence[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = _build_parser()
    raw_argv = tuple(sys.argv[1:] if argv is None else argv)
    pretty = "--pretty" in raw_argv

    try:
        _, command = _command_from_argv(raw_argv)
        explicit_profile = _profile_path_from_argv(raw_argv)
        profile = (
            {}
            if command in _NO_RUNTIME_SETTINGS_COMMANDS
            and explicit_profile is None
            else _local_runtime_profile(explicit_profile)
        )
        args = parser.parse_args(_argv_with_workspace_id_default(raw_argv, profile))
        _apply_workspace_id_default(args, profile)
        if args.command == "agent-help":
            result = _agent_help(args.topic)
        elif args.command in _NO_RUNTIME_SETTINGS_COMMANDS:
            result = _dispatch_provider_session_registry_command(args, profile)
        elif args.command in {"agent-workspace-init", "local-runtime-profile-init"}:
            result = _initialize_agent_workspace(args)
        else:
            application = LocalPlatformApplication(_settings_from_args(args, profile))
            result = _dispatch(application, args)
    except (OSError, TypeError, ValueError) as exc:
        _write_json(
            {
                "ok": False,
                "error": {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                },
            },
            pretty=pretty,
            stream=sys.stderr,
        )
        return 1

    if _text_output_requested(args, result):
        sys.stdout.write(_text_output(args, result).rstrip())
        sys.stdout.write("\n")
    else:
        _write_json(result, pretty=args.pretty, stream=sys.stdout)
    return 1 if isinstance(result, dict) and result.get("ok") is False else 0


def _add_runtime_status_policy_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--runtime-status-policy",
        choices=("auto", "enabled", "disabled"),
        default=argparse.SUPPRESS,
    )
    group.add_argument(
        "--read-live-runtime-status",
        dest="runtime_status_policy",
        action="store_const",
        const="enabled",
        default=argparse.SUPPRESS,
        help="Backward-compatible alias for --runtime-status-policy enabled.",
    )
    parser.set_defaults(runtime_status_policy="auto")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="beacon",
        description="Run Beacon local coordination operations without UI or HTTP.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument("--profile")
    parser.add_argument("--database")
    parser.add_argument("--workspace-root")
    parser.add_argument("--plugins-directory")
    parser.add_argument("--provider-session-registry")
    parser.add_argument("--no-init-schema", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument(
        "--agent-adapter-mode",
        default=os.environ.get(
            "AGENT_OS_LOCAL_AGENT_ADAPTER_MODE",
            "deterministic-placeholder",
        ),
    )
    parser.add_argument("--openai-compatible-base-url")
    parser.add_argument("--openai-compatible-model")
    parser.add_argument("--openai-compatible-provider-name")
    parser.add_argument("--openai-compatible-api-key-env-var")
    parser.add_argument("--openai-compatible-timeout-seconds", type=float)
    parser.add_argument("--openai-compatible-temperature", type=float)
    parser.add_argument("--openai-compatible-max-tokens", type=int)
    parser.add_argument("--openai-compatible-reasoning-effort")
    parser.add_argument("--openai-compatible-thinking-type")
    parser.add_argument("--provider-api-shape")
    parser.add_argument("--provider-base-url")
    parser.add_argument("--provider-model")
    parser.add_argument("--provider-name")
    parser.add_argument("--provider-api-key-env-var")
    parser.add_argument("--provider-timeout-seconds", type=float)
    parser.add_argument("--provider-temperature", type=float)
    parser.add_argument("--provider-max-tokens", type=int)
    parser.add_argument("--provider-reasoning-effort")
    parser.add_argument("--provider-thinking-type")
    parser.add_argument("--provider-input-mode")
    parser.add_argument("--provider-user-agent")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init")

    agent_help = subparsers.add_parser("agent-help")
    agent_help.add_argument(
        "--topic",
        default="onboarding",
        choices=("onboarding", "session", "endpoint", "dispatch", "status"),
    )
    agent_help.add_argument("--format", choices=("pretty", "json"), default="pretty")

    profile_register = subparsers.add_parser("provider-session-profile-register")
    profile_register.add_argument("--profile-id")
    profile_register.add_argument(
        "--provider",
        choices=("claude", "claude-cli", "claude-code", "codex", "codex-cli", "hermes", "hermes-cli", "hermes-desktop"),
        required=True,
    )
    profile_register.add_argument("--session-id", required=True)
    profile_register.add_argument("--profile-alias", required=True)
    profile_register.add_argument("--cwd", required=True)
    profile_register.add_argument("--source-path")
    profile_register.add_argument("--hermes-home")
    profile_register.add_argument("--hermes-session-source")
    profile_register.add_argument("--created-by", required=True)
    profile_register.add_argument("--reason", required=True)
    profile_register.add_argument("--metadata-json")

    profile_list = subparsers.add_parser("provider-session-profile-list")
    profile_list.add_argument(
        "--provider",
        choices=("claude", "claude-cli", "claude-code", "codex", "codex-cli", "hermes", "hermes-cli", "hermes-desktop"),
    )
    profile_list.add_argument("--include-inactive", action="store_true")

    profile_get = subparsers.add_parser("provider-session-profile-get")
    profile_get.add_argument("--profile-id")
    profile_get.add_argument("--profile-alias")
    profile_get.add_argument("--include-inactive-memberships", action="store_true")

    profile_deactivate = subparsers.add_parser("provider-session-profile-deactivate")
    profile_deactivate.add_argument("--profile-id", required=True)
    profile_deactivate.add_argument("--deactivated-by", required=True)
    profile_deactivate.add_argument("--reason", required=True)
    profile_deactivate.add_argument("--confirm-deactivate-profile", action="store_true")

    membership_list = subparsers.add_parser("provider-session-membership-list")
    membership_list.add_argument("--session-profile-id", "--profile-id", dest="profile_id")
    membership_list.add_argument("--workspace-id")
    membership_list.add_argument("--include-inactive", action="store_true")

    workspace_init = subparsers.add_parser(
        "agent-workspace-init",
        aliases=("local-runtime-profile-init",),
    )
    workspace_init.add_argument("--project-root", required=True)
    workspace_init.add_argument("--workspace-id", required=True)
    workspace_init.add_argument("--display-name", required=True)
    workspace_init.add_argument("--base-directory")
    workspace_init.add_argument("--profile-path")
    workspace_init.add_argument(
        "--pretty",
        action="store_true",
        default=argparse.SUPPRESS,
    )

    runtime_preflight = subparsers.add_parser(
        "agent-runtime-preflight",
        aliases=("agent-runtime-doctor",),
    )
    runtime_preflight.add_argument(
        "--tool",
        action="append",
        choices=SUPPORTED_AGENT_RUNTIME_TOOLS,
    )
    runtime_preflight.add_argument("--timeout-seconds", type=float, default=8.0)
    runtime_preflight.add_argument("--ticket-path")
    runtime_preflight.add_argument("--response-path")

    create = subparsers.add_parser("workspace-create")
    create.add_argument("--workspace-id")
    create.add_argument("--context-id")
    create.add_argument("--agent-id")
    create.add_argument("--display-name", required=True)
    create.add_argument("--root-path")

    subparsers.add_parser("workspace-list")

    open_workspace = subparsers.add_parser("workspace-open")
    open_workspace.add_argument("--workspace-id", required=True)

    archive = subparsers.add_parser("workspace-archive")
    archive.add_argument("--workspace-id", required=True)

    agent_create = subparsers.add_parser("agent-create")
    agent_create.add_argument("--workspace-id", required=True)
    agent_create.add_argument("--agent-id")
    agent_create.add_argument("--name", required=True)
    agent_create.add_argument("--description", required=True)
    agent_create.add_argument("--default-model")
    agent_create.add_argument("--capabilities-json")
    agent_create.add_argument("--tool-permissions-json")
    agent_create.add_argument("--runtime-config-json")
    agent_create.add_argument("--metadata-json")

    runtime_permissions = subparsers.add_parser("agent-runtime-permissions")
    runtime_permissions.add_argument("--workspace-id", required=True)

    runtime_permission_get = subparsers.add_parser("agent-runtime-permission-get")
    runtime_permission_get.add_argument("--workspace-id", required=True)
    runtime_permission_get.add_argument("--agent-id", required=True)

    exchange_instructions = subparsers.add_parser("agent-exchange-instructions")
    exchange_instructions.add_argument("--workspace-id")

    exchange_request_instructions = subparsers.add_parser(
        "agent-exchange-request-instructions"
    )
    exchange_request_instructions.add_argument("--workspace-id")

    exchange_request_policy = subparsers.add_parser(
        "agent-exchange-request-policy"
    )
    exchange_request_policy.add_argument("--workspace-id", required=True)

    exchange_request_policy_update = subparsers.add_parser(
        "agent-exchange-request-policy-update"
    )
    exchange_request_policy_update.add_argument("--workspace-id", required=True)
    exchange_request_policy_update.add_argument("--authorization-mode")
    exchange_request_policy_update.add_argument("--sub-request-policy")
    exchange_request_policy_update.add_argument(
        "--thread-workspace-visible",
        choices=("true", "false"),
    )
    exchange_request_policy_update.add_argument("--follow-up-policy")
    exchange_request_policy_update.add_argument("--allowed-sub-request-agent-ids-json")
    exchange_request_policy_update.add_argument("--max-request-length", type=int)
    exchange_request_policy_update.add_argument("--max-response-length", type=int)
    exchange_request_policy_update.add_argument("--max-response-tokens", type=int)
    exchange_request_policy_update.add_argument("--max-turns", type=int)
    exchange_request_policy_update.add_argument("--max-sub-request-depth", type=int)
    exchange_request_policy_update.add_argument("--max-child-requests", type=int)
    exchange_request_policy_update.add_argument(
        "--auto-append-exchange-result-to-shared-context",
        action="store_true",
    )
    exchange_request_policy_update.add_argument("--metadata-json")

    exchange_request_create = subparsers.add_parser(
        "agent-exchange-request-create"
    )
    exchange_request_create.add_argument("--workspace-id", required=True)
    exchange_request_create.add_argument("--exchange-request-id")
    exchange_request_create.add_argument("--source-agent-id", required=True)
    exchange_request_create.add_argument("--target-agent-id", required=True)
    exchange_request_create.add_argument("--request-kind", required=True)
    exchange_request_create.add_argument("--request-summary", required=True)
    exchange_request_create.add_argument("--agent-session-id")
    exchange_request_create.add_argument("--connection-instance-id")
    exchange_request_create.add_argument("--detail-refs-json")
    exchange_request_create.add_argument("--detail-ref", action="append", default=[])
    exchange_request_create.add_argument("--linked-task-id")
    exchange_request_create.add_argument("--linked-conversation-id")
    exchange_request_create.add_argument("--linked-activation-id")
    exchange_request_create.add_argument("--linked-delegated-wake-grant-id")
    exchange_request_create.add_argument("--parent-request-id")
    exchange_request_create.add_argument("--root-request-id")
    exchange_request_create.add_argument("--thread-id")
    exchange_request_create.add_argument("--turn-index", type=int)
    exchange_request_create.add_argument("--expires-at")
    exchange_request_create.add_argument("--requires-user-review", action="store_true")
    exchange_request_create.add_argument("--metadata-json")
    exchange_request_create.add_argument("--metadata", action="append", default=[])

    exchange_request_list = subparsers.add_parser("agent-exchange-request-list")
    exchange_request_list.add_argument("--workspace-id", required=True)
    exchange_request_list.add_argument("--source-agent-id")
    exchange_request_list.add_argument("--target-agent-id")
    exchange_request_list.add_argument("--status")

    exchange_request_get = subparsers.add_parser("agent-exchange-request-get")
    exchange_request_get.add_argument("--workspace-id", required=True)
    exchange_request_get.add_argument("--exchange-request-id", required=True)
    exchange_request_get.add_argument(
        "--format",
        choices=("json", "compact"),
        default="json",
    )
    exchange_request_get.add_argument(
        "--waiting-response-stale-threshold-seconds",
        type=int,
        default=600,
    )

    exchange_status = subparsers.add_parser("agent-exchange-status")
    exchange_status.add_argument("--workspace-id", required=True)
    exchange_status.add_argument("--exchange-request-id")
    exchange_status.add_argument("--dispatch-id")
    exchange_status.add_argument("--thread-id")
    _add_runtime_status_policy_arguments(exchange_status)
    exchange_status.add_argument(
        "--waiting-response-stale-threshold-seconds",
        type=int,
        default=600,
    )
    exchange_status.add_argument(
        "--format",
        choices=("json", "compact"),
        default="json",
    )

    exchange_request_respond = subparsers.add_parser(
        "agent-exchange-request-respond"
    )
    exchange_request_respond.add_argument("--workspace-id", required=True)
    exchange_request_respond.add_argument("--exchange-request-id", required=True)
    exchange_request_respond.add_argument("--responding-agent-id", required=True)
    exchange_request_respond.add_argument("--response-summary", required=True)
    exchange_request_respond.add_argument("--requires-user-review", action="store_true")
    exchange_request_respond.add_argument("--response-source")
    exchange_request_respond.add_argument("--actual-writer-agent-id")
    exchange_request_respond.add_argument("--metadata-json")

    exchange_request_close = subparsers.add_parser("agent-exchange-request-close")
    exchange_request_close.add_argument("--workspace-id", required=True)
    exchange_request_close.add_argument("--exchange-request-id", required=True)
    exchange_request_close.add_argument("--terminal-reason", default="closed")
    exchange_request_close.add_argument("--requires-user-review", action="store_true")
    exchange_request_close.add_argument("--metadata-json")

    dispatch_create = subparsers.add_parser("agent-dispatch-create")
    dispatch_create.add_argument("--workspace-id", required=True)
    dispatch_create.add_argument("--dispatch-id")
    dispatch_create.add_argument("--exchange-request-id")
    dispatch_create.add_argument("--source-agent-id", required=True)
    dispatch_create.add_argument("--target-agent-id", required=True)
    dispatch_create.add_argument("--source-handle-id")
    dispatch_create.add_argument("--target-handle-id")
    dispatch_create.add_argument("--target-provider")
    dispatch_create.add_argument(
        "--reply-policy",
        default="source_handle_optional",
        choices=("message_only", "source_handle_optional", "source_handle_required"),
    )
    dispatch_create.add_argument("--request-kind", required=True)
    dispatch_create.add_argument("--request-summary", required=True)
    dispatch_create.add_argument("--detail-refs-json")
    dispatch_create.add_argument("--detail-ref", action="append", default=[])
    dispatch_create.add_argument("--linked-task-id")
    dispatch_create.add_argument("--linked-conversation-id")
    dispatch_create.add_argument("--linked-activation-id")
    dispatch_create.add_argument("--linked-delegated-wake-grant-id")
    dispatch_create.add_argument("--parent-request-id")
    dispatch_create.add_argument("--root-request-id")
    dispatch_create.add_argument("--thread-id")
    dispatch_create.add_argument("--turn-index", type=int)
    dispatch_create.add_argument("--expires-at")
    dispatch_create.add_argument("--requires-user-review", action="store_true")
    dispatch_create.add_argument("--metadata-json")
    dispatch_create.add_argument("--metadata", action="append", default=[])
    dispatch_create.add_argument("--dry-run", action="store_true")

    dispatch_send = subparsers.add_parser("agent-dispatch-send")
    dispatch_send.add_argument("--workspace-id", required=True)
    dispatch_send.add_argument("--dispatch-id")
    dispatch_send.add_argument("--exchange-request-id")
    dispatch_send.add_argument("--from", "--from-endpoint", dest="from_endpoint_alias")
    dispatch_send.add_argument("--as", dest="acting_endpoint_alias")
    dispatch_send.add_argument("--to", "--to-endpoint", dest="to_endpoint_alias")
    dispatch_send.add_argument("--source-agent-id")
    dispatch_send.add_argument("--target-agent-id")
    dispatch_send.add_argument("--source-handle-id")
    dispatch_send.add_argument("--target-handle-id")
    dispatch_send.add_argument("--target-provider")
    dispatch_send.add_argument(
        "--reply-policy",
        choices=("message_only", "source_handle_optional", "source_handle_required"),
    )
    dispatch_send.add_argument("--message")
    dispatch_send.add_argument("--request-kind")
    dispatch_send.add_argument("--request-summary")
    dispatch_send.add_argument("--detail-refs-json")
    dispatch_send.add_argument("--detail-ref", action="append", default=[])
    dispatch_send.add_argument("--linked-task-id")
    dispatch_send.add_argument("--linked-conversation-id")
    dispatch_send.add_argument("--linked-activation-id")
    dispatch_send.add_argument("--linked-delegated-wake-grant-id")
    dispatch_send.add_argument("--parent-request-id")
    dispatch_send.add_argument("--root-request-id")
    dispatch_send.add_argument("--thread-id")
    dispatch_send.add_argument("--turn-index", type=int)
    dispatch_send.add_argument("--expires-at")
    dispatch_send.add_argument("--requires-user-review", action="store_true")
    dispatch_send.add_argument("--metadata-json")
    dispatch_send.add_argument("--metadata", action="append", default=[])
    dispatch_send.add_argument(
        "--delivery-mode",
        choices=("queued", "worker_dry_run", "worker_execute"),
    )
    dispatch_send.add_argument("--wait", choices=("once",))
    dispatch_send.add_argument("--queued", action="store_true")
    dispatch_send.add_argument("--dispatcher-id", default="agent-dispatch-worker")
    dispatch_send.add_argument("--lease-ttl-seconds", type=int, default=300)
    dispatch_send.add_argument("--retry-delay-seconds", type=int, default=300)
    dispatch_send.add_argument("--handoff-directory")
    dispatch_send.add_argument("--platform-workspace-root")
    dispatch_send.add_argument("--config-path")
    dispatch_send.add_argument(
        "--claude-executable",
        "--claude-path",
        dest="claude_executable",
        default="claude",
    )
    dispatch_send.add_argument(
        "--no-claude-default-platform-workspace-add-dir",
        action="store_true",
    )
    dispatch_send.add_argument("--claude-add-dir", action="append", default=[])
    dispatch_send.add_argument("--claude-allowed-tool", action="append", default=[])
    dispatch_send.add_argument("--claude-permission-mode")
    dispatch_send.add_argument("--claude-settings-path")
    dispatch_send.add_argument(
        "--codex-executable",
        "--codex-path",
        dest="codex_executable",
        default="codex",
    )
    dispatch_send.add_argument(
        "--no-codex-default-platform-workspace-add-dir",
        action="store_true",
    )
    dispatch_send.add_argument("--codex-add-dir", action="append", default=[])
    dispatch_send.add_argument("--codex-sandbox-mode")
    dispatch_send.add_argument("--codex-approval-policy")
    dispatch_send.add_argument(
        "--codex-git-repo-check-policy",
        choices=("skip", "strict"),
    )
    dispatch_send.add_argument(
        "--hermes-executable",
        "--hermes-path",
        dest="hermes_executable",
        default="hermes",
    )
    dispatch_send.add_argument("--hermes-home")
    dispatch_send.add_argument("--hermes-source-tag", default="agent-os")
    dispatch_send.add_argument("--hermes-max-turns", type=int)
    dispatch_send.add_argument("--activation-timeout-seconds", type=int, default=120)
    dispatch_send.add_argument("--ignore-busy-target", action="store_true")
    _add_runtime_status_policy_arguments(dispatch_send)
    dispatch_send.add_argument("--dry-run", action="store_true")

    dispatch_list = subparsers.add_parser("agent-dispatch-list")
    dispatch_list.add_argument("--workspace-id", required=True)
    dispatch_list.add_argument("--source-agent-id")
    dispatch_list.add_argument("--target-agent-id")
    dispatch_list.add_argument(
        "--status",
        choices=(
            "dry_run",
            "queued",
            "leased",
            "waiting_response",
            "retry_scheduled",
            "cancelled",
            "failed",
            "completed",
        ),
    )
    dispatch_list.add_argument("--limit", type=int, default=20)

    dispatch_status = subparsers.add_parser("agent-dispatch-status")
    dispatch_status.add_argument("--workspace-id", required=True)
    dispatch_status.add_argument("--dispatch-id")
    dispatch_status.add_argument("--exchange-request-id")
    _add_runtime_status_policy_arguments(dispatch_status)
    dispatch_status.add_argument(
        "--waiting-response-stale-threshold-seconds",
        type=int,
        default=600,
    )
    dispatch_status.add_argument(
        "--format",
        choices=("json", "compact"),
        default="json",
    )

    dispatch_lease_acquire = subparsers.add_parser("agent-dispatch-lease-acquire")
    dispatch_lease_acquire.add_argument("--workspace-id", required=True)
    dispatch_lease_acquire.add_argument("--dispatch-id", required=True)
    dispatch_lease_acquire.add_argument("--lease-id")
    dispatch_lease_acquire.add_argument("--acquired-by")
    dispatch_lease_acquire.add_argument("--lease-ttl-seconds", type=int)
    dispatch_lease_acquire.add_argument("--metadata-json")

    dispatch_lease_release = subparsers.add_parser("agent-dispatch-lease-release")
    dispatch_lease_release.add_argument("--workspace-id", required=True)
    dispatch_lease_release.add_argument("--lease-id", required=True)
    dispatch_lease_release.add_argument("--released-by")
    dispatch_lease_release.add_argument(
        "--final-dispatch-status",
        default="queued",
        choices=(
            "queued",
            "waiting_response",
            "retry_scheduled",
            "cancelled",
            "failed",
            "completed",
        ),
    )
    dispatch_lease_release.add_argument("--metadata-json")

    dispatch_lease_reconcile = subparsers.add_parser(
        "agent-dispatch-lease-reconcile"
    )
    dispatch_lease_reconcile.add_argument("--workspace-id", required=True)
    dispatch_lease_reconcile.add_argument("--dispatch-id")
    dispatch_lease_reconcile.add_argument("--lease-id")
    dispatch_lease_reconcile.add_argument(
        "--recovered-by",
        default="agent-dispatch-lease-reconciler",
    )
    dispatch_lease_reconcile.add_argument(
        "--recovery-delay-seconds",
        type=int,
        default=0,
    )
    dispatch_lease_reconcile.add_argument("--dry-run", action="store_true")
    dispatch_lease_reconcile.add_argument("--execute", action="store_true")

    dispatch_worker = subparsers.add_parser("agent-dispatch-worker-run-once")
    dispatch_worker.add_argument("--workspace-id", required=True)
    dispatch_worker.add_argument("--dispatch-id")
    dispatch_worker.add_argument("--target-agent-id")
    dispatch_worker.add_argument("--dispatcher-id", default="agent-dispatch-worker")
    dispatch_worker.add_argument("--limit", type=int, default=1)
    dispatch_worker.add_argument("--lease-ttl-seconds", type=int, default=300)
    dispatch_worker.add_argument("--retry-delay-seconds", type=int, default=300)
    dispatch_worker.add_argument("--handoff-directory")
    dispatch_worker.add_argument("--platform-workspace-root")
    dispatch_worker.add_argument("--config-path")
    dispatch_worker.add_argument(
        "--claude-executable",
        "--claude-path",
        dest="claude_executable",
        default="claude",
    )
    dispatch_worker.add_argument(
        "--no-claude-default-platform-workspace-add-dir",
        action="store_true",
    )
    dispatch_worker.add_argument("--claude-add-dir", action="append", default=[])
    dispatch_worker.add_argument("--claude-allowed-tool", action="append", default=[])
    dispatch_worker.add_argument("--claude-permission-mode")
    dispatch_worker.add_argument("--claude-settings-path")
    dispatch_worker.add_argument(
        "--codex-executable",
        "--codex-path",
        dest="codex_executable",
        default="codex",
    )
    dispatch_worker.add_argument(
        "--no-codex-default-platform-workspace-add-dir",
        action="store_true",
    )
    dispatch_worker.add_argument("--codex-add-dir", action="append", default=[])
    dispatch_worker.add_argument("--codex-sandbox-mode")
    dispatch_worker.add_argument("--codex-approval-policy")
    dispatch_worker.add_argument(
        "--codex-git-repo-check-policy",
        choices=("skip", "strict"),
    )
    dispatch_worker.add_argument(
        "--hermes-executable",
        "--hermes-path",
        dest="hermes_executable",
        default="hermes",
    )
    dispatch_worker.add_argument("--hermes-home")
    dispatch_worker.add_argument("--hermes-source-tag", default="agent-os")
    dispatch_worker.add_argument("--hermes-max-turns", type=int)
    dispatch_worker.add_argument("--activation-timeout-seconds", type=int, default=120)
    dispatch_worker.add_argument("--ignore-busy-target", action="store_true")
    _add_runtime_status_policy_arguments(dispatch_worker)
    dispatch_worker.add_argument("--dry-run", action="store_true")
    dispatch_worker.add_argument("--execute", action="store_true")

    dispatch_daemon_status = subparsers.add_parser("agent-dispatch-daemon-status")
    dispatch_daemon_status.add_argument("--workspace-id", required=True)
    dispatch_daemon_status.add_argument("--dispatcher-id")

    dispatch_daemon_start = subparsers.add_parser("agent-dispatch-daemon-start")
    dispatch_daemon_start.add_argument("--workspace-id", required=True)
    dispatch_daemon_start.add_argument("--dispatch-id")
    dispatch_daemon_start.add_argument("--target-agent-id")
    dispatch_daemon_start.add_argument(
        "--dispatcher-id",
        default="agent-dispatch-daemon",
    )
    dispatch_daemon_start.add_argument("--limit", type=int, default=1)
    dispatch_daemon_start.add_argument("--lease-ttl-seconds", type=int, default=300)
    dispatch_daemon_start.add_argument("--retry-delay-seconds", type=int, default=300)
    dispatch_daemon_start.add_argument("--handoff-directory")
    dispatch_daemon_start.add_argument("--platform-workspace-root")
    dispatch_daemon_start.add_argument("--config-path")
    dispatch_daemon_start.add_argument(
        "--claude-executable",
        "--claude-path",
        dest="claude_executable",
        default="claude",
    )
    dispatch_daemon_start.add_argument(
        "--no-claude-default-platform-workspace-add-dir",
        action="store_true",
    )
    dispatch_daemon_start.add_argument("--claude-add-dir", action="append", default=[])
    dispatch_daemon_start.add_argument(
        "--claude-allowed-tool",
        action="append",
        default=[],
    )
    dispatch_daemon_start.add_argument("--claude-permission-mode")
    dispatch_daemon_start.add_argument("--claude-settings-path")
    dispatch_daemon_start.add_argument(
        "--codex-executable",
        "--codex-path",
        dest="codex_executable",
        default="codex",
    )
    dispatch_daemon_start.add_argument(
        "--no-codex-default-platform-workspace-add-dir",
        action="store_true",
    )
    dispatch_daemon_start.add_argument("--codex-add-dir", action="append", default=[])
    dispatch_daemon_start.add_argument("--codex-sandbox-mode")
    dispatch_daemon_start.add_argument("--codex-approval-policy")
    dispatch_daemon_start.add_argument(
        "--codex-git-repo-check-policy",
        choices=("skip", "strict"),
    )
    dispatch_daemon_start.add_argument(
        "--hermes-executable",
        "--hermes-path",
        dest="hermes_executable",
        default="hermes",
    )
    dispatch_daemon_start.add_argument("--hermes-home")
    dispatch_daemon_start.add_argument("--hermes-source-tag", default="agent-os")
    dispatch_daemon_start.add_argument("--hermes-max-turns", type=int)
    dispatch_daemon_start.add_argument(
        "--activation-timeout-seconds",
        type=int,
        default=120,
    )
    dispatch_daemon_start.add_argument("--ignore-busy-target", action="store_true")
    _add_runtime_status_policy_arguments(dispatch_daemon_start)
    dispatch_daemon_start.add_argument("--poll-interval-ms", type=int, default=5000)
    dispatch_daemon_start.add_argument("--heartbeat-interval-ms", type=int)
    dispatch_daemon_start.add_argument("--once", action="store_true")
    dispatch_daemon_start.add_argument("--dry-run", action="store_true")
    dispatch_daemon_start.add_argument("--wait", action="store_true")
    dispatch_daemon_start.add_argument("--python-executable")
    dispatch_daemon_start.add_argument("--log-directory")

    exchange_thread_instructions = subparsers.add_parser(
        "agent-exchange-thread-instructions"
    )
    exchange_thread_instructions.add_argument("--workspace-id")

    exchange_thread_list = subparsers.add_parser("agent-exchange-thread-list")
    exchange_thread_list.add_argument("--workspace-id", required=True)
    exchange_thread_list.add_argument("--requesting-agent-id")
    exchange_thread_list.add_argument("--status")
    exchange_thread_list.add_argument("--visibility")

    exchange_thread_get = subparsers.add_parser("agent-exchange-thread-get")
    exchange_thread_get.add_argument("--workspace-id", required=True)
    exchange_thread_get.add_argument("--thread-id", required=True)
    exchange_thread_get.add_argument("--requesting-agent-id")

    exchange_thread_requests = subparsers.add_parser(
        "agent-exchange-thread-requests"
    )
    exchange_thread_requests.add_argument("--workspace-id", required=True)
    exchange_thread_requests.add_argument("--thread-id", required=True)
    exchange_thread_requests.add_argument("--requesting-agent-id")

    exchange_thread_follow_up = subparsers.add_parser(
        "agent-exchange-thread-follow-up-create"
    )
    exchange_thread_follow_up.add_argument("--workspace-id", required=True)
    exchange_thread_follow_up.add_argument("--thread-id", required=True)
    exchange_thread_follow_up.add_argument("--exchange-request-id")
    exchange_thread_follow_up.add_argument("--parent-request-id")
    exchange_thread_follow_up.add_argument("--source-agent-id", required=True)
    exchange_thread_follow_up.add_argument("--target-agent-id", required=True)
    exchange_thread_follow_up.add_argument("--request-kind", required=True)
    exchange_thread_follow_up.add_argument("--request-summary", required=True)
    exchange_thread_follow_up.add_argument("--detail-refs-json")
    exchange_thread_follow_up.add_argument("--detail-ref", action="append", default=[])
    exchange_thread_follow_up.add_argument("--linked-task-id")
    exchange_thread_follow_up.add_argument("--linked-conversation-id")
    exchange_thread_follow_up.add_argument("--linked-activation-id")
    exchange_thread_follow_up.add_argument("--linked-delegated-wake-grant-id")
    exchange_thread_follow_up.add_argument("--requires-user-review", action="store_true")
    exchange_thread_follow_up.add_argument("--metadata-json")

    exchange_thread_visibility = subparsers.add_parser(
        "agent-exchange-thread-visibility-update"
    )
    exchange_thread_visibility.add_argument("--workspace-id", required=True)
    exchange_thread_visibility.add_argument("--thread-id", required=True)
    exchange_thread_visibility.add_argument("--updated-by-agent-id", required=True)
    exchange_thread_visibility.add_argument("--visibility", required=True)
    exchange_thread_visibility.add_argument("--metadata-json")

    exchange_thread_close = subparsers.add_parser("agent-exchange-thread-close")
    exchange_thread_close.add_argument("--workspace-id", required=True)
    exchange_thread_close.add_argument("--thread-id", required=True)
    exchange_thread_close.add_argument("--terminal-reason", default="closed")
    exchange_thread_close.add_argument("--closed-by-agent-id")
    exchange_thread_close.add_argument("--metadata-json")

    wake_instructions = subparsers.add_parser("agent-wake-instructions")
    wake_instructions.add_argument("--workspace-id")
    wake_instructions.add_argument("--agent-id")

    wake_watch = subparsers.add_parser("agent-exchange-wake-watch")
    _add_agent_wake_watch_args(wake_watch)
    wake_daemon = subparsers.add_parser("agent-wake-daemon")
    _add_agent_wake_watch_args(wake_daemon)

    wake_delivery_list = subparsers.add_parser("agent-wake-delivery-list")
    wake_delivery_list.add_argument("--workspace-id", required=True)
    wake_delivery_list.add_argument("--agent-id")
    wake_delivery_list.add_argument("--exchange-request-id")
    wake_delivery_list.add_argument("--wake-ticket-id")
    wake_delivery_list.add_argument("--status")
    wake_delivery_list.add_argument("--limit", type=int, default=20)

    wake_status = subparsers.add_parser("agent-wake-status")
    wake_status.add_argument("--workspace-id", required=True)
    wake_status.add_argument("--exchange-request-id", required=True)

    wake_ticket_get = subparsers.add_parser("agent-wake-ticket-get")
    wake_ticket_get.add_argument("--workspace-id", required=True)
    wake_ticket_get.add_argument("--exchange-request-id")
    wake_ticket_get.add_argument("--wake-ticket-id")

    session_discover = subparsers.add_parser("agent-session-discover")
    session_discover.add_argument(
        "--provider",
        choices=("all", "claude", "codex", "hermes"),
        required=True,
    )
    session_discover.add_argument("--limit", type=int, default=20)
    session_discover.add_argument("--cwd")
    session_discover.add_argument("--claude-home")
    session_discover.add_argument("--codex-home")
    session_discover.add_argument("--hermes-home")
    session_discover.add_argument(
        "--hermes-executable",
        "--hermes-path",
        dest="hermes_executable",
        default="hermes",
    )
    session_discover.add_argument("--hermes-source")
    session_discover.add_argument("--hermes-timeout-seconds", type=float, default=15.0)
    session_discover.add_argument("--current-session-id")
    session_discover.add_argument("--include-turn-snippets", action="store_true")
    session_discover.add_argument(
        "--include-full-session-history",
        action="store_true",
    )
    session_discover.add_argument("--snippet-turn-index", type=int)
    session_discover.add_argument("--snippet-max-chars", type=int, default=160)
    session_discover.add_argument("--provider-account-label")
    session_discover.add_argument("--vendor-account-label")
    session_discover.add_argument("--relay-account-label")

    session_register_discovered = subparsers.add_parser(
        "agent-session-handle-register-discovered"
    )
    session_register_discovered.add_argument("--workspace-id", required=True)
    session_register_discovered.add_argument("--agent-id", required=True)
    session_register_discovered.add_argument(
        "--provider",
        choices=("claude", "codex", "hermes"),
        required=True,
    )
    session_register_discovered.add_argument("--session-id", required=True)
    session_register_discovered.add_argument("--handle-id")
    session_register_discovered.add_argument("--created-by", required=True)
    session_register_discovered.add_argument("--reason", required=True)
    session_register_discovered.add_argument("--metadata-json")
    session_register_discovered.add_argument("--limit", type=int, default=20)
    session_register_discovered.add_argument("--cwd")
    session_register_discovered.add_argument("--claude-home")
    session_register_discovered.add_argument("--codex-home")
    session_register_discovered.add_argument("--hermes-home")
    session_register_discovered.add_argument(
        "--hermes-executable",
        "--hermes-path",
        dest="hermes_executable",
        default="hermes",
    )
    session_register_discovered.add_argument("--hermes-source")
    session_register_discovered.add_argument(
        "--hermes-timeout-seconds",
        type=float,
        default=15.0,
    )
    session_register_discovered.add_argument("--current-session-id")
    session_register_discovered.add_argument(
        "--include-turn-snippets",
        action="store_true",
    )
    session_register_discovered.add_argument("--snippet-turn-index", type=int)
    session_register_discovered.add_argument("--snippet-max-chars", type=int, default=160)

    endpoint_login_discovered = subparsers.add_parser(
        "agent-endpoint-login-discovered"
    )
    endpoint_login_discovered.add_argument("--workspace-id", required=True)
    endpoint_login_discovered.add_argument("--agent-id", required=True)
    endpoint_login_discovered.add_argument(
        "--provider",
        choices=("claude", "codex", "hermes"),
        required=True,
    )
    endpoint_login_discovered.add_argument("--session-id")
    endpoint_login_discovered.add_argument("--handle-id")
    endpoint_login_discovered.add_argument("--endpoint-id")
    endpoint_login_discovered.add_argument("--alias", required=True)
    endpoint_login_discovered.add_argument(
        "--direction",
        default="send_receive",
        choices=("send_only", "receive_only", "send_receive"),
    )
    endpoint_login_discovered.add_argument(
        "--default-reply-policy",
        default="source_handle_required",
        choices=("message_only", "source_handle_optional", "source_handle_required"),
    )
    endpoint_login_discovered.add_argument(
        "--contact-policy",
        default="open",
        choices=("open", "contacts_only", "block_all"),
    )
    endpoint_login_discovered.add_argument("--created-by", required=True)
    endpoint_login_discovered.add_argument("--reason", required=True)
    endpoint_login_discovered.add_argument("--metadata-json")
    endpoint_login_discovered.add_argument(
        "--allow-source-alias",
        action="append",
        default=[],
    )
    endpoint_login_discovered.add_argument(
        "--allow-source-agent-id",
        action="append",
        default=[],
    )
    endpoint_login_discovered.add_argument(
        "--allow-source-handle-id",
        action="append",
        default=[],
    )
    endpoint_login_discovered.add_argument(
        "--block-source-alias",
        action="append",
        default=[],
    )
    endpoint_login_discovered.add_argument(
        "--block-source-agent-id",
        action="append",
        default=[],
    )
    endpoint_login_discovered.add_argument(
        "--block-source-handle-id",
        action="append",
        default=[],
    )
    endpoint_login_discovered.add_argument("--limit", type=int, default=20)
    endpoint_login_discovered.add_argument("--cwd")
    endpoint_login_discovered.add_argument("--claude-home")
    endpoint_login_discovered.add_argument("--codex-home")
    endpoint_login_discovered.add_argument("--hermes-home")
    endpoint_login_discovered.add_argument(
        "--hermes-executable",
        "--hermes-path",
        dest="hermes_executable",
        default="hermes",
    )
    endpoint_login_discovered.add_argument("--hermes-source")
    endpoint_login_discovered.add_argument(
        "--hermes-timeout-seconds",
        type=float,
        default=15.0,
    )
    endpoint_login_discovered.add_argument("--current-session-id")
    endpoint_login_discovered.add_argument("--include-turn-snippets", action="store_true")
    endpoint_login_discovered.add_argument("--snippet-turn-index", type=int)
    endpoint_login_discovered.add_argument("--snippet-max-chars", type=int, default=160)

    onboarding_status = subparsers.add_parser("agent-onboarding-status")
    onboarding_status.add_argument("--workspace-id", required=True)
    onboarding_status.add_argument("--agent-id")
    onboarding_status.add_argument(
        "--endpoint-alias",
        "--alias",
        dest="endpoint_alias",
    )
    onboarding_status.add_argument(
        "--provider",
        choices=("claude", "claude-cli", "claude-code", "codex", "codex-cli", "hermes", "hermes-cli", "hermes-desktop"),
    )
    _add_runtime_status_policy_arguments(onboarding_status)
    onboarding_status.add_argument("--format", choices=("json", "pretty"), default="json")

    workspace_join = subparsers.add_parser("provider-session-workspace-join")
    workspace_join.add_argument("--workspace-id", required=True)
    workspace_join.add_argument("--session-profile-id", "--profile-id", dest="profile_id", required=True)
    workspace_join.add_argument("--agent-id", required=True)
    workspace_join.add_argument("--agent-name", required=True)
    workspace_join.add_argument(
        "--description",
        default="Beacon provider endpoint agent.",
    )
    workspace_join.add_argument("--endpoint-alias", "--alias", dest="endpoint_alias", required=True)
    workspace_join.add_argument(
        "--direction",
        default="send_receive",
        choices=("send", "receive", "both", "send_only", "receive_only", "send_receive"),
    )
    workspace_join.add_argument(
        "--default-reply-policy",
        default="standard",
        choices=("standard", "manual", "none", "message_only", "source_handle_optional", "source_handle_required"),
    )
    workspace_join.add_argument(
        "--contact-policy",
        default="open",
        choices=("open", "contacts_only", "block_all"),
    )
    workspace_join.add_argument("--handle-id")
    workspace_join.add_argument("--endpoint-id")
    workspace_join.add_argument("--created-by", required=True)
    workspace_join.add_argument("--reason", required=True)
    workspace_join.add_argument("--metadata-json")
    workspace_join.add_argument("--no-reuse-existing", action="store_true")

    workspace_leave = subparsers.add_parser("provider-session-workspace-leave")
    workspace_leave.add_argument("--workspace-id", required=True)
    workspace_leave.add_argument("--session-profile-id", "--profile-id", dest="profile_id", required=True)
    workspace_leave.add_argument("--left-by", default="local-user")
    workspace_leave.add_argument("--reason", required=True)
    workspace_leave.add_argument("--keep-endpoint", action="store_true")
    workspace_leave.add_argument("--deactivate-provider-handle", action="store_true")

    provider_onboard = subparsers.add_parser("agent-provider-onboard")
    provider_onboard.add_argument("--workspace-id", required=True)
    provider_onboard.add_argument(
        "--provider",
        choices=("claude", "codex", "hermes"),
        required=True,
    )
    provider_onboard.add_argument("--agent-id", required=True)
    provider_onboard.add_argument("--agent-name", required=True)
    provider_onboard.add_argument(
        "--description",
        default="Beacon provider endpoint agent.",
    )
    provider_onboard.add_argument(
        "--endpoint-alias",
        "--alias",
        dest="endpoint_alias",
        required=True,
    )
    provider_onboard.add_argument(
        "--direction",
        default="both",
        choices=(
            "send",
            "receive",
            "both",
            "send_only",
            "receive_only",
            "send_receive",
        ),
    )
    provider_onboard.add_argument(
        "--default-reply-policy",
        default="standard",
        choices=(
            "standard",
            "manual",
            "none",
            "message_only",
            "source_handle_optional",
            "source_handle_required",
        ),
    )
    provider_onboard.add_argument(
        "--contact-policy",
        default="open",
        choices=("open", "contacts_only", "block_all"),
    )
    provider_onboard.add_argument("--session-id")
    provider_onboard.add_argument("--claude-session-uuid")
    provider_onboard.add_argument("--codex-session-id")
    provider_onboard.add_argument("--hermes-session-id")
    provider_onboard.add_argument("--handle-id")
    provider_onboard.add_argument("--endpoint-id")
    provider_onboard.add_argument("--created-by", default="user")
    provider_onboard.add_argument("--reason", default="agent provider onboard")
    provider_onboard.add_argument("--metadata-json")
    provider_onboard.add_argument("--no-reuse-existing", action="store_true")
    provider_onboard.add_argument("--dry-run", action="store_true")
    provider_onboard.add_argument("--format", choices=("json",), default="json")
    provider_onboard.add_argument("--allow-source-alias", action="append", default=[])
    provider_onboard.add_argument("--allow-source-agent-id", action="append", default=[])
    provider_onboard.add_argument("--allow-source-handle-id", action="append", default=[])
    provider_onboard.add_argument("--block-source-alias", action="append", default=[])
    provider_onboard.add_argument("--block-source-agent-id", action="append", default=[])
    provider_onboard.add_argument("--block-source-handle-id", action="append", default=[])
    provider_onboard.add_argument("--limit", type=int, default=20)
    provider_onboard.add_argument("--cwd")
    provider_onboard.add_argument("--claude-home")
    provider_onboard.add_argument("--codex-home")
    provider_onboard.add_argument("--hermes-home")
    provider_onboard.add_argument(
        "--hermes-executable",
        "--hermes-path",
        dest="hermes_executable",
        default="hermes",
    )
    provider_onboard.add_argument("--hermes-source")
    provider_onboard.add_argument(
        "--hermes-timeout-seconds",
        type=float,
        default=15.0,
    )
    provider_onboard.add_argument("--current-session-id")
    provider_onboard.add_argument("--discover-current-session", action="store_true")
    provider_onboard.add_argument("--include-turn-snippets", action="store_true")
    provider_onboard.add_argument("--snippet-turn-index", type=int)
    provider_onboard.add_argument("--snippet-max-chars", type=int, default=160)

    endpoint_login = subparsers.add_parser("agent-endpoint-login")
    endpoint_login.add_argument("--workspace-id", required=True)
    endpoint_login.add_argument("--agent-id", required=True)
    endpoint_login.add_argument("--endpoint-id")
    endpoint_login.add_argument("--alias", required=True)
    endpoint_login.add_argument(
        "--provider",
        choices=("claude", "claude-cli", "claude-code", "codex", "codex-cli", "hermes", "hermes-cli", "hermes-desktop"),
        required=True,
    )
    endpoint_login.add_argument("--provider-handle-id", required=True)
    endpoint_login.add_argument(
        "--direction",
        default="send_receive",
        choices=("send_only", "receive_only", "send_receive"),
    )
    endpoint_login.add_argument(
        "--default-reply-policy",
        default="source_handle_required",
        choices=("message_only", "source_handle_optional", "source_handle_required"),
    )
    endpoint_login.add_argument(
        "--contact-policy",
        default="open",
        choices=("open", "contacts_only", "block_all"),
    )
    endpoint_login.add_argument("--created-by", required=True)
    endpoint_login.add_argument("--reason", required=True)
    endpoint_login.add_argument("--metadata-json")
    endpoint_login.add_argument("--allow-source-alias", action="append", default=[])
    endpoint_login.add_argument("--allow-source-agent-id", action="append", default=[])
    endpoint_login.add_argument("--allow-source-handle-id", action="append", default=[])
    endpoint_login.add_argument("--block-source-alias", action="append", default=[])
    endpoint_login.add_argument("--block-source-agent-id", action="append", default=[])
    endpoint_login.add_argument("--block-source-handle-id", action="append", default=[])

    endpoint_list = subparsers.add_parser("agent-endpoint-list")
    endpoint_list.add_argument("--workspace-id", required=True)
    endpoint_list.add_argument("--agent-id")
    endpoint_list.add_argument(
        "--provider",
        choices=("claude", "codex", "hermes"),
    )
    endpoint_list.add_argument("--include-inactive", action="store_true")

    endpoint_get = subparsers.add_parser("agent-endpoint-get")
    endpoint_get.add_argument("--workspace-id", required=True)
    endpoint_get.add_argument("--endpoint-id")
    endpoint_get.add_argument("--alias")

    endpoint_identity = subparsers.add_parser("agent-endpoint-identity")
    endpoint_identity.add_argument("--workspace-id", required=True)
    endpoint_identity.add_argument("--alias", required=True)

    endpoint_status = subparsers.add_parser("agent-endpoint-status")
    endpoint_status.add_argument("--workspace-id", required=True)
    endpoint_status.add_argument("--endpoint-id")
    endpoint_status.add_argument("--alias")
    endpoint_status.add_argument("--limit", type=int, default=20)
    _add_runtime_status_policy_arguments(endpoint_status)

    provider_runtime_status = subparsers.add_parser(
        "agent-provider-runtime-status"
    )
    provider_runtime_status.add_argument("--workspace-id", required=True)
    provider_runtime_status.add_argument("--provider")
    provider_runtime_status.add_argument("--provider-handle-id")
    provider_runtime_status.add_argument("--endpoint-id")
    provider_runtime_status.add_argument("--alias")
    _add_runtime_status_policy_arguments(provider_runtime_status)

    endpoint_deactivate = subparsers.add_parser("agent-endpoint-deactivate")
    endpoint_deactivate.add_argument("--workspace-id", required=True)
    endpoint_deactivate.add_argument("--endpoint-id")
    endpoint_deactivate.add_argument("--alias")
    endpoint_deactivate.add_argument("--deactivated-by", required=True)
    endpoint_deactivate.add_argument("--reason", required=True)

    claude_handle_register = subparsers.add_parser("claude-session-handle-register")
    claude_handle_register.add_argument("--workspace-id", required=True)
    claude_handle_register.add_argument("--agent-id", required=True)
    claude_handle_register.add_argument("--handle-id")
    claude_handle_register.add_argument("--claude-session-uuid", required=True)
    claude_handle_register.add_argument("--cwd", required=True)
    claude_handle_register.add_argument("--source-path")
    claude_handle_register.add_argument("--created-by", required=True)
    claude_handle_register.add_argument("--reason", required=True)
    claude_handle_register.add_argument("--metadata-json")

    claude_handle_list = subparsers.add_parser("claude-session-handle-list")
    claude_handle_list.add_argument("--workspace-id", required=True)
    claude_handle_list.add_argument("--agent-id")
    claude_handle_list.add_argument("--include-inactive", action="store_true")

    claude_handle_get = subparsers.add_parser("claude-session-handle-get")
    claude_handle_get.add_argument("--workspace-id", required=True)
    claude_handle_get.add_argument("--handle-id", required=True)

    claude_handle_deactivate = subparsers.add_parser(
        "claude-session-handle-deactivate"
    )
    claude_handle_deactivate.add_argument("--workspace-id", required=True)
    claude_handle_deactivate.add_argument("--handle-id", required=True)
    claude_handle_deactivate.add_argument("--deactivated-by", required=True)
    claude_handle_deactivate.add_argument("--reason", required=True)

    claude_activate = subparsers.add_parser("claude-registered-session-activate")
    claude_activate.add_argument("--workspace-id", required=True)
    claude_activate.add_argument("--agent-id", required=True)
    claude_activate.add_argument("--handle-id", required=True)
    claude_activate.add_argument("--exchange-request-id", required=True)
    claude_activate.add_argument("--handoff-directory")
    claude_activate.add_argument("--claude-executable", default="claude")
    claude_activate.add_argument("--platform-workspace-root")
    claude_activate.add_argument(
        "--no-default-platform-workspace-add-dir",
        action="store_true",
    )
    claude_activate.add_argument("--add-dir", action="append", default=[])
    claude_activate.add_argument("--allowed-tool", action="append", default=[])
    claude_activate.add_argument("--permission-mode")
    claude_activate.add_argument("--settings-path")
    claude_activate.add_argument("--timeout-seconds", type=int, default=120)
    claude_activate.add_argument("--dry-run", action="store_true")
    claude_activate.add_argument("--execute", action="store_true")

    codex_handle_register = subparsers.add_parser("codex-session-handle-register")
    codex_handle_register.add_argument("--workspace-id", required=True)
    codex_handle_register.add_argument("--agent-id", required=True)
    codex_handle_register.add_argument("--handle-id")
    codex_handle_register.add_argument("--codex-session-id", required=True)
    codex_handle_register.add_argument("--cwd", required=True)
    codex_handle_register.add_argument("--source-path")
    codex_handle_register.add_argument("--created-by", required=True)
    codex_handle_register.add_argument("--reason", required=True)
    codex_handle_register.add_argument("--metadata-json")

    codex_handle_list = subparsers.add_parser("codex-session-handle-list")
    codex_handle_list.add_argument("--workspace-id", required=True)
    codex_handle_list.add_argument("--agent-id")
    codex_handle_list.add_argument("--include-inactive", action="store_true")

    codex_handle_get = subparsers.add_parser("codex-session-handle-get")
    codex_handle_get.add_argument("--workspace-id", required=True)
    codex_handle_get.add_argument("--handle-id", required=True)

    codex_handle_deactivate = subparsers.add_parser(
        "codex-session-handle-deactivate"
    )
    codex_handle_deactivate.add_argument("--workspace-id", required=True)
    codex_handle_deactivate.add_argument("--handle-id", required=True)
    codex_handle_deactivate.add_argument("--deactivated-by", required=True)
    codex_handle_deactivate.add_argument("--reason", required=True)

    codex_activate = subparsers.add_parser("codex-registered-session-activate")
    codex_activate.add_argument("--workspace-id", required=True)
    codex_activate.add_argument("--agent-id", required=True)
    codex_activate.add_argument("--handle-id", required=True)
    codex_activate.add_argument("--exchange-request-id", required=True)
    codex_activate.add_argument("--handoff-directory")
    codex_activate.add_argument(
        "--codex-executable",
        "--codex-path",
        dest="codex_executable",
        default="codex",
    )
    codex_activate.add_argument("--platform-workspace-root")
    codex_activate.add_argument(
        "--no-default-platform-workspace-add-dir",
        action="store_true",
    )
    codex_activate.add_argument("--add-dir", action="append", default=[])
    codex_activate.add_argument("--sandbox-mode")
    codex_activate.add_argument("--approval-policy")
    codex_activate.add_argument(
        "--codex-git-repo-check-policy",
        choices=("skip", "strict"),
    )
    codex_activate.add_argument("--timeout-seconds", type=int, default=120)
    codex_activate.add_argument("--dry-run", action="store_true")
    codex_activate.add_argument("--execute", action="store_true")

    hermes_handle_register = subparsers.add_parser("hermes-session-handle-register")
    hermes_handle_register.add_argument("--workspace-id", required=True)
    hermes_handle_register.add_argument("--agent-id", required=True)
    hermes_handle_register.add_argument("--handle-id")
    hermes_handle_register.add_argument("--hermes-session-id", required=True)
    hermes_handle_register.add_argument("--cwd", required=True)
    hermes_handle_register.add_argument("--source-path")
    hermes_handle_register.add_argument("--hermes-home")
    hermes_handle_register.add_argument("--hermes-session-source")
    hermes_handle_register.add_argument("--created-by", required=True)
    hermes_handle_register.add_argument("--reason", required=True)
    hermes_handle_register.add_argument("--metadata-json")

    hermes_handle_list = subparsers.add_parser("hermes-session-handle-list")
    hermes_handle_list.add_argument("--workspace-id", required=True)
    hermes_handle_list.add_argument("--agent-id")
    hermes_handle_list.add_argument("--include-inactive", action="store_true")

    hermes_handle_get = subparsers.add_parser("hermes-session-handle-get")
    hermes_handle_get.add_argument("--workspace-id", required=True)
    hermes_handle_get.add_argument("--handle-id", required=True)

    hermes_handle_deactivate = subparsers.add_parser(
        "hermes-session-handle-deactivate"
    )
    hermes_handle_deactivate.add_argument("--workspace-id", required=True)
    hermes_handle_deactivate.add_argument("--handle-id", required=True)
    hermes_handle_deactivate.add_argument("--deactivated-by", required=True)
    hermes_handle_deactivate.add_argument("--reason", required=True)

    hermes_activate = subparsers.add_parser("hermes-registered-session-activate")
    hermes_activate.add_argument("--workspace-id", required=True)
    hermes_activate.add_argument("--agent-id", required=True)
    hermes_activate.add_argument("--handle-id", required=True)
    hermes_activate.add_argument("--exchange-request-id", required=True)
    hermes_activate.add_argument("--handoff-directory")
    hermes_activate.add_argument(
        "--hermes-executable",
        "--hermes-path",
        dest="hermes_executable",
        default="hermes",
    )
    hermes_activate.add_argument("--platform-workspace-root")
    hermes_activate.add_argument("--hermes-home")
    hermes_activate.add_argument("--source-tag", default="agent-os")
    hermes_activate.add_argument("--max-turns", type=int)
    hermes_activate.add_argument("--timeout-seconds", type=int, default=120)
    hermes_activate.add_argument("--dry-run", action="store_true")
    hermes_activate.add_argument("--execute", action="store_true")

    activation_instructions = subparsers.add_parser("agent-activation-instructions")
    activation_instructions.add_argument("--workspace-id")

    activation_wake = subparsers.add_parser("agent-activation-wake")
    activation_wake.add_argument("--workspace-id", required=True)
    activation_wake.add_argument("--agent-id", required=True)
    activation_wake.add_argument("--activation-id")
    activation_wake.add_argument("--created-by", required=True)
    activation_wake.add_argument("--reason", required=True)
    activation_wake.add_argument("--mode", default="manual_wake_safe_mode")
    activation_wake.add_argument("--connection-surface", default="cli")
    activation_wake.add_argument("--task-id")
    activation_wake.add_argument("--conversation-id")
    activation_wake.add_argument("--budget-json")
    activation_wake.add_argument("--ttl-seconds", type=int)
    activation_wake.add_argument("--max-operations", type=int)
    activation_wake.add_argument("--max-writes", type=int)
    activation_wake.add_argument("--max-agent-to-agent-turns", type=int)
    activation_wake.add_argument("--max-context-reads", type=int)
    activation_wake.add_argument("--max-estimated-tokens", type=int)
    activation_wake.add_argument("--allowed-contribution-kinds-json")
    activation_wake.add_argument("--metadata-json")

    activation_status = subparsers.add_parser("agent-activation-status")
    activation_status.add_argument("--workspace-id", required=True)
    activation_status.add_argument("--agent-id")
    activation_status.add_argument("--activation-id")
    activation_status.add_argument("--list", action="store_true")

    activation_revoke = subparsers.add_parser("agent-activation-revoke")
    activation_revoke.add_argument("--workspace-id", required=True)
    activation_revoke.add_argument("--agent-id", required=True)
    activation_revoke.add_argument("--activation-id")
    activation_revoke.add_argument("--revoked-by", required=True)
    activation_revoke.add_argument("--reason", required=True)

    delegated_wake_instructions = subparsers.add_parser(
        "agent-delegated-wake-grant-instructions"
    )
    delegated_wake_instructions.add_argument("--workspace-id")

    delegated_wake_create = subparsers.add_parser(
        "agent-delegated-wake-grant-create"
    )
    delegated_wake_create.add_argument("--workspace-id", required=True)
    delegated_wake_create.add_argument("--delegated-wake-grant-id")
    delegated_wake_create.add_argument("--source-agent-id", required=True)
    delegated_wake_create.add_argument("--target-agent-id", required=True)
    delegated_wake_create.add_argument("--created-by", required=True)
    delegated_wake_create.add_argument("--reason", required=True)
    delegated_wake_create.add_argument(
        "--mode", default="user_authorized_one_time"
    )
    delegated_wake_create.add_argument("--task-id")
    delegated_wake_create.add_argument("--conversation-id")
    delegated_wake_create.add_argument(
        "--target-activation-mode", default="manual_wake_safe_mode"
    )
    delegated_wake_create.add_argument("--target-activation-budget-json")
    delegated_wake_create.add_argument("--target-ttl-seconds", type=int)
    delegated_wake_create.add_argument("--target-max-writes", type=int)
    delegated_wake_create.add_argument("--target-max-operations", type=int)
    delegated_wake_create.add_argument("--target-max-agent-to-agent-turns", type=int)
    delegated_wake_create.add_argument("--target-max-context-reads", type=int)
    delegated_wake_create.add_argument("--allowed-contribution-kinds-json")
    delegated_wake_create.add_argument("--expires-at")
    delegated_wake_create.add_argument("--metadata-json")

    delegated_wake_status = subparsers.add_parser(
        "agent-delegated-wake-grant-status"
    )
    delegated_wake_status.add_argument("--workspace-id", required=True)
    delegated_wake_status.add_argument("--delegated-wake-grant-id")
    delegated_wake_status.add_argument("--source-agent-id")
    delegated_wake_status.add_argument("--list", action="store_true")

    delegated_wake_consume = subparsers.add_parser(
        "agent-delegated-wake-grant-consume"
    )
    delegated_wake_consume.add_argument("--workspace-id", required=True)
    delegated_wake_consume.add_argument(
        "--delegated-wake-grant-id", required=True
    )
    delegated_wake_consume.add_argument("--consuming-agent-id", required=True)

    delegated_wake_revoke = subparsers.add_parser(
        "agent-delegated-wake-grant-revoke"
    )
    delegated_wake_revoke.add_argument("--workspace-id", required=True)
    delegated_wake_revoke.add_argument(
        "--delegated-wake-grant-id", required=True
    )
    delegated_wake_revoke.add_argument("--revoked-by", required=True)
    delegated_wake_revoke.add_argument("--reason", required=True)

    directory_instructions = subparsers.add_parser(
        "project-directory-coordination-instructions"
    )
    directory_instructions.add_argument("--workspace-id")

    directory_declare = subparsers.add_parser(
        "project-directory-coordination-declare"
    )
    directory_declare.add_argument("--workspace-id", required=True)
    directory_declare.add_argument("--directory-coordination-id")
    directory_declare.add_argument("--declared-agent-id", required=True)
    directory_declare.add_argument("--project-root", required=True)
    directory_declare.add_argument("--git-repository-id")
    directory_declare.add_argument("--linked-task-id")
    directory_declare.add_argument("--linked-conversation-id")
    directory_declare.add_argument("--declared-path-scopes-json")
    directory_declare.add_argument("--directory-access-intent", default="edit_planned")
    directory_declare.add_argument("--last-known-git-head")
    directory_declare.add_argument("--last-known-branch")
    directory_declare.add_argument("--dirty-state", default="unknown")
    directory_declare.add_argument("--uncommitted-change-summary")
    directory_declare.add_argument("--test-summary")
    directory_declare.add_argument(
        "--recommended-commit-policy", default="commit_after_task"
    )
    directory_declare.add_argument("--handoff-note")
    directory_declare.add_argument("--requires-user-review", action="store_true")
    directory_declare.add_argument("--metadata-json")

    directory_status = subparsers.add_parser(
        "project-directory-coordination-status"
    )
    directory_status.add_argument("--workspace-id", required=True)
    directory_status.add_argument("--directory-coordination-id")
    directory_status.add_argument("--list", action="store_true")

    directory_update = subparsers.add_parser(
        "project-directory-coordination-update"
    )
    directory_update.add_argument("--workspace-id", required=True)
    directory_update.add_argument("--directory-coordination-id", required=True)
    directory_update.add_argument("--directory-access-intent")
    directory_update.add_argument("--declared-path-scopes-json")
    directory_update.add_argument("--last-known-git-head")
    directory_update.add_argument("--last-known-branch")
    directory_update.add_argument("--dirty-state")
    directory_update.add_argument("--uncommitted-change-summary")
    directory_update.add_argument("--test-summary")
    directory_update.add_argument("--recommended-commit-policy")
    directory_update.add_argument("--handoff-note")
    directory_update.add_argument("--requires-user-review", action="store_true")
    directory_update.add_argument("--metadata-json")

    directory_complete = subparsers.add_parser(
        "project-directory-coordination-complete"
    )
    directory_complete.add_argument("--workspace-id", required=True)
    directory_complete.add_argument("--directory-coordination-id", required=True)
    directory_complete.add_argument("--last-known-git-head")
    directory_complete.add_argument("--last-known-branch")
    directory_complete.add_argument("--dirty-state")
    directory_complete.add_argument("--uncommitted-change-summary")
    directory_complete.add_argument("--test-summary")
    directory_complete.add_argument("--recommended-commit-policy")
    directory_complete.add_argument("--handoff-note")
    directory_complete.add_argument("--requires-user-review", action="store_true")
    directory_complete.add_argument("--metadata-json")

    conversation_create = subparsers.add_parser("conversation-create")
    conversation_create.add_argument("--workspace-id", required=True)
    conversation_create.add_argument("--conversation-id")
    conversation_create.add_argument("--agent-id")
    conversation_create.add_argument("--title", required=True)
    conversation_create.add_argument("--metadata-json")

    conversation_list = subparsers.add_parser("conversation-list")
    conversation_list.add_argument("--workspace-id", required=True)

    conversation_get = subparsers.add_parser("conversation-get")
    conversation_get.add_argument("--workspace-id", required=True)
    conversation_get.add_argument("--conversation-id", required=True)

    conversation_archive = subparsers.add_parser("conversation-archive")
    conversation_archive.add_argument("--workspace-id", required=True)
    conversation_archive.add_argument("--conversation-id", required=True)

    conversation_message_append = subparsers.add_parser("conversation-message-append")
    conversation_message_append.add_argument("--workspace-id", required=True)
    conversation_message_append.add_argument("--conversation-id", required=True)
    conversation_message_append.add_argument("--message-id")
    conversation_message_append.add_argument("--role", required=True)
    conversation_message_append.add_argument("--content", required=True)
    conversation_message_append.add_argument("--agent-id")
    conversation_message_append.add_argument("--invocation-id")
    conversation_message_append.add_argument("--context-update-id")
    conversation_message_append.add_argument("--run-session-id")
    conversation_message_append.add_argument("--metadata-json")
    conversation_message_append.add_argument("--metadata", action="append", default=[])
    conversation_message_append.add_argument("--exchange-attribution-json")
    _add_exchange_attribution_args(conversation_message_append)

    conversation_messages = subparsers.add_parser("conversation-messages")
    conversation_messages.add_argument("--workspace-id", required=True)
    conversation_messages.add_argument("--conversation-id", required=True)
    conversation_messages.add_argument("--limit", type=int)
    conversation_messages.add_argument("--offset", type=int, default=0)

    invoke = subparsers.add_parser("invoke")
    invoke.add_argument("--workspace-id", required=True)
    invoke.add_argument("--agent-id")
    invoke.add_argument("--instruction", required=True)
    invoke.add_argument("--invocation-id")
    invoke.add_argument("--requested-at")
    invoke.add_argument("--session-id")
    invoke.add_argument("--idempotency-key")
    invoke.add_argument("--correlation-id")
    invoke.add_argument("--conversation-id")

    invoke_json = subparsers.add_parser("invoke-json")
    invoke_json.add_argument("--payload-json")
    invoke_json.add_argument("--payload", action="append", default=[])

    context_get = subparsers.add_parser("context-get")
    context_get.add_argument("--workspace-id", required=True)

    context_updates = subparsers.add_parser("context-updates")
    context_updates.add_argument("--workspace-id", required=True)
    context_updates.add_argument("--limit", type=int, default=20)
    context_updates.add_argument("--offset", type=int, default=0)
    context_updates.add_argument("--update-kind", choices=CONTEXT_UPDATE_KIND_CHOICES)

    context_update_get = subparsers.add_parser("context-update-get")
    context_update_get.add_argument("--workspace-id", required=True)
    context_update_get.add_argument("--update-id", required=True)

    context_append = subparsers.add_parser("context-append")
    context_append.add_argument("--workspace-id", required=True)
    context_append.add_argument("--summary", required=True)
    context_append.add_argument(
        "--update-kind",
        choices=CONTEXT_UPDATE_KIND_CHOICES,
        default=ContextUpdateKind.NOTE.value,
    )
    context_append.add_argument("--update-id")
    context_append.add_argument("--patch-json")
    context_append.add_argument("--payload-json")
    context_append.add_argument("--payload", action="append", default=[])
    context_append.add_argument("--session-id")
    context_append.add_argument("--exchange-attribution-json")
    _add_exchange_attribution_args(context_append)

    invocations = subparsers.add_parser("records-invocations")
    invocations.add_argument("--workspace-id", required=True)

    file_operations = subparsers.add_parser("records-file-operations")
    file_operations.add_argument("--workspace-id", required=True)

    timeline = subparsers.add_parser("session-timeline")
    timeline.add_argument("--workspace-id", required=True)
    timeline.add_argument("--session-id", required=True)

    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--workspace-id", default="workspace-local-smoke-1")
    smoke.add_argument("--display-name", default="Local Smoke Workspace")
    smoke.add_argument("--root-path")
    smoke.add_argument(
        "--instruction",
        default="Run local smoke invocation.",
    )
    smoke.add_argument("--invocation-id", default="invoke-local-smoke-1")
    smoke.add_argument("--session-id", default="session-local-smoke-1")

    return parser


def _add_agent_wake_watch_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--config")
    parser.add_argument("--wake-mode")
    parser.add_argument("--enabled", choices=("true", "false"))
    parser.add_argument("--poll-interval-ms", type=int)
    parser.add_argument("--max-wake-attempts-per-request", type=int)
    parser.add_argument("--cooldown-ms", type=int)
    parser.add_argument("--handoff-directory")
    parser.add_argument("--command-argv-json")
    parser.add_argument("--child-process-policy")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="info")
    parser.add_argument("--heartbeat-interval-ms", type=int)


def _settings_from_args(
    args: argparse.Namespace,
    profile: Mapping[str, object] | None = None,
) -> LocalPlatformSettings:
    profile = profile if profile is not None else _local_runtime_profile(args.profile)
    provider_settings = None
    provider_connection = None
    if args.agent_adapter_mode == "openai-compatible-provider":
        provider_settings = openai_compatible_provider_settings_from_env(
            _openai_compatible_env(args),
            parameters=_openai_compatible_parameters(args),
        )
    if args.agent_adapter_mode == "provider-api-shape":
        provider_connection = provider_connection_spec_from_env(
            _provider_env(args),
            parameters=_provider_parameters(args),
        )
    database = _runtime_setting(
        "database",
        args.database,
        profile,
        env_keys=("AGENT_OS_DATABASE", "AGENT_OS_DB_PATH"),
        profile_keys=("database", "databasePath", "dbPath"),
    )
    workspace_root = _runtime_setting(
        "workspace_root",
        args.workspace_root,
        profile,
        env_keys=("AGENT_OS_WORKSPACE_ROOT",),
        profile_keys=("workspaceRoot", "workspace_root"),
    )
    plugins_directory = _runtime_setting(
        "plugins_directory",
        args.plugins_directory,
        profile,
        env_keys=("AGENT_OS_PLUGINS_DIRECTORY", "AGENT_OS_PLUGINS_DIR"),
        profile_keys=("pluginsDirectory", "plugins_directory", "pluginsDir"),
    )
    registry_resolution = _provider_session_registry_resolution(
        args.provider_session_registry,
        profile,
        workspace_root=workspace_root,
    )
    return LocalPlatformSettings(
        database=database,
        workspace_root=workspace_root,
        plugins_directory=plugins_directory,
        agent_invocation_adapter_mode=args.agent_adapter_mode,
        profile_path=_profile_path_text(
            args.profile or os.environ.get("AGENT_OS_LOCAL_RUNTIME_PROFILE")
        ),
        provider_session_registry=registry_resolution.registry_path,
        provider_session_registry_source=registry_resolution.registry_path_source,
        provider_session_registry_source_key=(
            registry_resolution.registry_path_source_key
        ),
        openai_compatible_provider=provider_settings,
        provider_connection=provider_connection,
        initialize_schema=not args.no_init_schema,
    )


def _initialize_agent_workspace(args: argparse.Namespace) -> Mapping[str, object]:
    workspace_id = _workspace_id_text(args.workspace_id)
    project_root = _resolved_path(args.project_root, "projectRoot")
    project_root.mkdir(parents=True, exist_ok=True)
    base_directory = _workspace_init_base_directory(
        project_root,
        args.base_directory,
    )
    workspace_base = base_directory / "workspaces" / _safe_workspace_directory_name(
        workspace_id
    )
    profile_path = _workspace_init_profile_path(
        project_root,
        base_directory,
        workspace_id,
        args.profile_path,
    )

    database_path = workspace_base / "platform.sqlite3"
    workspace_root = workspace_base / "workspace-root"
    plugins_directory = workspace_base / "plugins"
    wake_tickets_directory = workspace_base / "wake-tickets"
    dispatch_state_directory = workspace_base / "dispatch-state"
    output_directory = workspace_base / "output"
    registry_resolution = _provider_session_registry_resolution(
        args.provider_session_registry,
        {},
        base_directory=base_directory,
    )
    provider_session_registry = Path(registry_resolution.registry_path)

    for path in (
        workspace_base,
        workspace_root,
        plugins_directory,
        wake_tickets_directory,
        dispatch_state_directory,
        output_directory,
        profile_path.parent,
    ):
        path.mkdir(parents=True, exist_ok=True)

    settings = LocalPlatformSettings(
        database=str(database_path),
        workspace_root=str(workspace_root),
        plugins_directory=str(plugins_directory),
    )
    application = LocalPlatformApplication(settings)
    workspace_created = True
    try:
        workspace = application.create_workspace(
            workspace_id=workspace_id,
            display_name=_non_empty_text(args.display_name, "displayName"),
            root_path=str(workspace_root),
        )
    except ValueError as exc:
        if "workspace state already exists" not in str(exc):
            raise
        workspace_created = False
        workspace = {
            "workspace": application.open_workspace(workspace_id),
            "created": False,
        }

    local_absolute_paths = {
        "projectRoot": str(project_root),
        "baseDirectory": str(base_directory),
        "workspaceBase": str(workspace_base),
        "databasePath": str(database_path),
        "workspaceRoot": str(workspace_root),
        "pluginsDirectory": str(plugins_directory),
        "wakeTicketsDirectory": str(wake_tickets_directory),
        "dispatchStateDirectory": str(dispatch_state_directory),
        "outputDirectory": str(output_directory),
        "profilePath": str(profile_path),
        "providerSessionRegistry": str(provider_session_registry),
    }
    project_relative_paths = {
        key: _relative_path_text(project_root, Path(value))
        for key, value in local_absolute_paths.items()
    }
    profile_payload = {
        "schema": "agent_os_local_runtime_profile.v1",
        "localRuntime": {
            "workspaceId": workspace_id,
            "databasePath": str(database_path),
            "workspaceRoot": str(workspace_root),
            "pluginsDirectory": str(plugins_directory),
            "projectRoot": str(project_root),
            "baseDirectory": str(base_directory),
            "workspaceBase": str(workspace_base),
            "wakeTicketsDirectory": str(wake_tickets_directory),
            "dispatchStateDirectory": str(dispatch_state_directory),
            "outputDirectory": str(output_directory),
            "providerSessionRegistry": str(provider_session_registry),
            "providerSessionRegistryPathSource": (
                registry_resolution.registry_path_source
            ),
            "providerSessionRegistryPathSourceKey": (
                registry_resolution.registry_path_source_key
            ),
        },
        "pathPolicy": {
            "localAbsolutePaths": local_absolute_paths,
            "projectRelativePaths": project_relative_paths,
            "localOnlyDirectory": _relative_path_text(project_root, base_directory),
            "doNotCommit": True,
            "note": (
                "This profile contains local absolute paths for this machine. "
                "Regenerate it after moving the project."
            ),
        },
    }
    profile_path.write_text(
        json.dumps(profile_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "schema": "agent_workspace_init.v1",
        "initialized": True,
        "workspaceCreated": workspace_created,
        "workspaceId": workspace_id,
        "displayName": _non_empty_text(args.display_name, "displayName"),
        "workspace": workspace,
        "profile": {
            "path": str(profile_path),
            "schema": profile_payload["schema"],
            "argument": f"--profile {profile_path}",
            "environment": {
                "AGENT_OS_LOCAL_RUNTIME_PROFILE": str(profile_path),
            },
        },
        "paths": {
            "localAbsolutePaths": local_absolute_paths,
            "projectRelativePaths": project_relative_paths,
            "localOnlyDirectory": _relative_path_text(project_root, base_directory),
            "doNotCommit": True,
        },
        **registry_resolution.to_metadata(),
        "nextCommands": {
            "workspaceOpen": (
                "python -m agent_os.local_runtime "
                f"--profile {profile_path} workspace-open"
            ),
            "dispatchSend": (
                "python -m agent_os.local_runtime "
                f"--profile {profile_path} agent-dispatch-send"
            ),
            "endpointLogin": (
                "python -m agent_os.local_runtime "
                f"--profile {profile_path} agent-endpoint-login"
            ),
            "dispatchWorkerRunOnce": (
                "python -m agent_os.local_runtime "
                f"--profile {profile_path} agent-dispatch-worker-run-once"
            ),
        },
    }


def _start_agent_dispatch_daemon(
    application: LocalPlatformApplication,
    args: argparse.Namespace,
) -> Mapping[str, object]:
    if args.wait and not args.once:
        raise ValueError("--wait requires --once to keep daemon startup bounded.")
    profile_path = _profile_path_text(args.profile)
    argv = _agent_dispatch_daemon_argv(application.settings, args, profile_path)
    process_hint = {
        "launcher": "agent_os.local_runtime",
        "launchMode": "subprocess_argv",
        "usesShell": False,
        "argv": argv,
    }
    started_at = datetime.now(timezone.utc)
    application.record_agent_dispatch_daemon_liveness(
        workspace_id=args.workspace_id,
        dispatcher_id=args.dispatcher_id,
        state="starting",
        profile_path=profile_path,
        process_hint=process_hint,
        started_at=started_at,
        last_heartbeat_at=started_at,
    )
    environment = os.environ.copy()
    if profile_path is not None:
        environment["AGENT_OS_LOCAL_RUNTIME_PROFILE"] = profile_path
    if args.wait:
        try:
            completed = subprocess.run(
                argv,
                cwd=str(Path.cwd()),
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                shell=False,
            )
        except OSError as exc:
            return _agent_dispatch_daemon_start_failure(
                application,
                args,
                profile_path=profile_path,
                process_hint=process_hint,
                exc=exc,
            )
        status = application.get_agent_dispatch_daemon_status(
            workspace_id=args.workspace_id,
            dispatcher_id=args.dispatcher_id,
        )
        return {
            "schema": "agent_dispatch_daemon_start.v1",
            "workspaceId": args.workspace_id,
            "dispatcherId": args.dispatcher_id,
            "profilePath": profile_path,
            "launchMode": "subprocess_argv",
            "usesShell": False,
            "background": False,
            "waited": True,
            "processStarted": True,
            "processExitCode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "argv": argv,
            "daemonStatus": status,
            "dispatcherRunning": status["dispatcherRunning"],
        }

    log_directory = _agent_dispatch_daemon_log_directory(application.settings, args)
    log_directory.mkdir(parents=True, exist_ok=True)
    stdout_path = log_directory / f"{args.dispatcher_id}.stdout.log"
    stderr_path = log_directory / f"{args.dispatcher_id}.stderr.log"
    stdout_handle = stdout_path.open("a", encoding="utf-8")
    stderr_handle = stderr_path.open("a", encoding="utf-8")
    try:
        popen_kwargs: dict[str, object] = {}
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0,
            )
        else:
            popen_kwargs["start_new_session"] = True
        process = subprocess.Popen(
            argv,
            cwd=str(Path.cwd()),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            shell=False,
            **popen_kwargs,
        )
    except OSError as exc:
        return _agent_dispatch_daemon_start_failure(
            application,
            args,
            profile_path=profile_path,
            process_hint=process_hint,
            exc=exc,
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()
    application.record_agent_dispatch_daemon_liveness(
        workspace_id=args.workspace_id,
        dispatcher_id=args.dispatcher_id,
        state="starting",
        profile_path=profile_path,
        pid=process.pid,
        process_hint={**process_hint, "pid": process.pid},
        started_at=started_at,
        last_heartbeat_at=started_at,
    )
    status = application.get_agent_dispatch_daemon_status(
        workspace_id=args.workspace_id,
        dispatcher_id=args.dispatcher_id,
    )
    return {
        "schema": "agent_dispatch_daemon_start.v1",
        "workspaceId": args.workspace_id,
        "dispatcherId": args.dispatcher_id,
        "profilePath": profile_path,
        "launchMode": "subprocess_argv",
        "usesShell": False,
        "background": True,
        "waited": False,
        "processStarted": True,
        "pid": process.pid,
        "stdoutPath": str(stdout_path),
        "stderrPath": str(stderr_path),
        "argv": argv,
        "daemonStatus": status,
        "dispatcherRunning": status["dispatcherRunning"],
    }


def _agent_dispatch_daemon_start_failure(
    application: LocalPlatformApplication,
    args: argparse.Namespace,
    *,
    profile_path: str | None,
    process_hint: Mapping[str, object],
    exc: OSError,
) -> Mapping[str, object]:
    now = datetime.now(timezone.utc)
    application.record_agent_dispatch_daemon_liveness(
        workspace_id=args.workspace_id,
        dispatcher_id=args.dispatcher_id,
        state="failed",
        profile_path=profile_path,
        process_hint=process_hint,
        last_error_at=now,
        last_exit_at=now,
        last_exit_reason="startup_failed",
        error_summary=f"{exc.__class__.__name__}: {exc}",
    )
    status = application.get_agent_dispatch_daemon_status(
        workspace_id=args.workspace_id,
        dispatcher_id=args.dispatcher_id,
    )
    return {
        "schema": "agent_dispatch_daemon_start.v1",
        "workspaceId": args.workspace_id,
        "dispatcherId": args.dispatcher_id,
        "profilePath": profile_path,
        "launchMode": "subprocess_argv",
        "usesShell": False,
        "background": not args.wait,
        "waited": bool(args.wait),
        "processStarted": False,
        "error": {
            "type": exc.__class__.__name__,
            "message": str(exc),
        },
        "argv": list(process_hint["argv"]),
        "daemonStatus": status,
        "dispatcherRunning": status["dispatcherRunning"],
    }


def _agent_dispatch_daemon_argv(
    settings: LocalPlatformSettings,
    args: argparse.Namespace,
    profile_path: str | None,
) -> list[str]:
    argv = [
        args.python_executable or sys.executable,
        "-m",
        "agent_os.agent_dispatch_daemon",
    ]
    if profile_path is not None:
        argv.extend(["--profile", profile_path])
    else:
        argv.extend(
            [
                "--database",
                settings.database,
                "--workspace-root",
                settings.workspace_root,
                "--plugins-directory",
                settings.plugins_directory,
            ]
        )
    if args.no_init_schema:
        argv.append("--no-init-schema")
    _append_argv_option(argv, "--workspace-id", args.workspace_id)
    _append_argv_option(argv, "--dispatch-id", args.dispatch_id)
    _append_argv_option(argv, "--target-agent-id", args.target_agent_id)
    _append_argv_option(argv, "--dispatcher-id", args.dispatcher_id)
    _append_argv_option(argv, "--limit", args.limit)
    _append_argv_option(argv, "--lease-ttl-seconds", args.lease_ttl_seconds)
    _append_argv_option(argv, "--retry-delay-seconds", args.retry_delay_seconds)
    _append_argv_option(argv, "--handoff-directory", args.handoff_directory)
    _append_argv_option(argv, "--platform-workspace-root", args.platform_workspace_root)
    _append_argv_option(argv, "--config-path", args.config_path)
    _append_argv_option(argv, "--claude-executable", args.claude_executable)
    if args.no_claude_default_platform_workspace_add_dir:
        argv.append("--no-claude-default-platform-workspace-add-dir")
    for value in args.claude_add_dir:
        _append_argv_option(argv, "--claude-add-dir", value)
    for value in args.claude_allowed_tool:
        _append_argv_option(argv, "--claude-allowed-tool", value)
    _append_argv_option(argv, "--claude-permission-mode", args.claude_permission_mode)
    _append_argv_option(argv, "--claude-settings-path", args.claude_settings_path)
    _append_argv_option(argv, "--codex-executable", args.codex_executable)
    if args.no_codex_default_platform_workspace_add_dir:
        argv.append("--no-codex-default-platform-workspace-add-dir")
    for value in args.codex_add_dir:
        _append_argv_option(argv, "--codex-add-dir", value)
    _append_argv_option(argv, "--codex-sandbox-mode", args.codex_sandbox_mode)
    _append_argv_option(argv, "--codex-approval-policy", args.codex_approval_policy)
    _append_argv_option(
        argv,
        "--codex-git-repo-check-policy",
        args.codex_git_repo_check_policy,
    )
    _append_argv_option(argv, "--hermes-executable", args.hermes_executable)
    _append_argv_option(argv, "--hermes-home", args.hermes_home)
    _append_argv_option(argv, "--hermes-source-tag", args.hermes_source_tag)
    _append_argv_option(argv, "--hermes-max-turns", args.hermes_max_turns)
    _append_argv_option(
        argv,
        "--activation-timeout-seconds",
        args.activation_timeout_seconds,
    )
    if args.ignore_busy_target:
        argv.append("--ignore-busy-target")
    _append_argv_option(
        argv,
        "--runtime-status-policy",
        args.runtime_status_policy,
    )
    _append_argv_option(argv, "--poll-interval-ms", args.poll_interval_ms)
    _append_argv_option(argv, "--heartbeat-interval-ms", args.heartbeat_interval_ms)
    if args.once:
        argv.append("--once")
    if args.dry_run:
        argv.append("--dry-run")
    return argv


def _append_argv_option(
    argv: list[str],
    option: str,
    value: object | None,
) -> None:
    if value is None:
        return
    argv.extend([option, str(value)])


def _profile_path_text(value: str | None) -> str | None:
    path = value or os.environ.get("AGENT_OS_LOCAL_RUNTIME_PROFILE")
    if path is None or not path.strip():
        return None
    return str(Path(path).expanduser().resolve(strict=False))


def _agent_dispatch_daemon_log_directory(
    settings: LocalPlatformSettings,
    args: argparse.Namespace,
) -> Path:
    if args.log_directory is not None and args.log_directory.strip():
        return Path(args.log_directory).expanduser().resolve(strict=False)
    return (
        Path(settings.workspace_root).expanduser().resolve(strict=False).parent
        / "daemon-logs"
    )


def _local_runtime_profile(profile_path: str | None) -> Mapping[str, object]:
    path = profile_path or os.environ.get("AGENT_OS_LOCAL_RUNTIME_PROFILE")
    if path is None or not path.strip():
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError("local runtime profile must be a JSON object.")
    raw_profile = loaded.get("localRuntime", loaded)
    if not isinstance(raw_profile, dict):
        raise ValueError("localRuntime profile must be a JSON object.")
    return raw_profile


def _codex_git_repo_check_policy(
    args: argparse.Namespace,
    profile: Mapping[str, object],
) -> tuple[str, str]:
    explicit = getattr(args, "codex_git_repo_check_policy", None)
    if explicit is not None:
        return _validated_codex_git_repo_check_policy(explicit), "explicit_cli"
    for key in ("codexGitRepoCheckPolicy", "codex_git_repo_check_policy"):
        value = profile.get(key)
        if value is not None:
            return _validated_codex_git_repo_check_policy(value), "profile"
    return "skip", "default"


def _validated_codex_git_repo_check_policy(value: object) -> str:
    if not isinstance(value, str) or value.strip() not in {"skip", "strict"}:
        raise ValueError("codexGitRepoCheckPolicy must be 'skip' or 'strict'.")
    return value.strip()


def _profile_path_from_argv(argv: Sequence[str]) -> str | None:
    for index, item in enumerate(argv):
        if item == "--profile" and index + 1 < len(argv):
            return argv[index + 1]
        if item.startswith("--profile="):
            return item.split("=", 1)[1]
    return None


def _argv_with_workspace_id_default(
    argv: Sequence[str],
    profile: Mapping[str, object],
) -> tuple[str, ...]:
    command_index, command = _command_from_argv(argv)
    if command_index is None or command not in _WORKSPACE_ID_REQUIRED_COMMANDS:
        return tuple(argv)
    if "--workspace-id" in argv or any(
        item.startswith("--workspace-id=") for item in argv
    ):
        return tuple(argv)
    workspace_id = _workspace_id_default(profile)
    if workspace_id is None:
        return tuple(argv)
    updated = list(argv)
    updated[command_index + 1:command_index + 1] = ["--workspace-id", workspace_id]
    return tuple(updated)


def _command_from_argv(argv: Sequence[str]) -> tuple[int | None, str | None]:
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == "--":
            if index + 1 < len(argv):
                return index + 1, argv[index + 1]
            return None, None
        if item.startswith("--"):
            if "=" not in item and item in _GLOBAL_OPTIONS_WITH_VALUE:
                index += 2
            else:
                index += 1
            continue
        return index, item
    return None, None


def _apply_workspace_id_default(
    args: argparse.Namespace,
    profile: Mapping[str, object],
) -> None:
    if not hasattr(args, "workspace_id"):
        return
    value = getattr(args, "workspace_id")
    if isinstance(value, str) and value.strip():
        setattr(args, "workspace_id", value.strip())
        return
    default = _workspace_id_default(profile)
    if default is not None:
        setattr(args, "workspace_id", default)


def _workspace_id_default(profile: Mapping[str, object]) -> str | None:
    for key in ("workspaceId", "workspace_id", "workspace"):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None:
            raise ValueError(f"profile {key} must be a string.")
    for key in ("AGENT_OS_WORKSPACE_ID", "AGENT_OS_WORKSPACE"):
        value = os.environ.get(key)
        if value is not None and value.strip():
            return value.strip()
    return None


def _workspace_id_text(value: str | None) -> str:
    return _non_empty_text(value, "workspaceId")


def _non_empty_text(value: str | None, field_name: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _resolved_path(value: str | None, field_name: str) -> Path:
    return Path(_non_empty_text(value, field_name)).expanduser().resolve(strict=False)


def _workspace_init_base_directory(
    project_root: Path,
    raw_base_directory: str | None,
) -> Path:
    if raw_base_directory is None or not raw_base_directory.strip():
        return (project_root / ".beacon").resolve(strict=False)
    base = Path(raw_base_directory.strip()).expanduser()
    if not base.is_absolute():
        base = project_root / base
    return base.resolve(strict=False)


def _workspace_init_profile_path(
    project_root: Path,
    base_directory: Path,
    workspace_id: str,
    raw_profile_path: str | None,
) -> Path:
    if raw_profile_path is None or not raw_profile_path.strip():
        return (
            base_directory
            / "profiles"
            / f"{_safe_workspace_directory_name(workspace_id)}.local-runtime.json"
        ).resolve(strict=False)
    profile_path = Path(raw_profile_path.strip()).expanduser()
    if not profile_path.is_absolute():
        profile_path = project_root / profile_path
    return profile_path.resolve(strict=False)


def _safe_workspace_directory_name(workspace_id: str) -> str:
    name = _non_empty_text(workspace_id, "workspaceId")
    if name in {".", ".."} or any(char in name for char in '<>:"/\\|?*'):
        raise ValueError(
            "workspaceId must be safe for a single local directory name."
        )
    return name


def _relative_path_text(root: Path, path: Path) -> str | None:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return None


def _provider_session_registry_resolution(
    explicit: str | None,
    profile: Mapping[str, object],
    *,
    workspace_root: str | None = None,
    base_directory: Path | None = None,
) -> ProviderSessionRegistryPathResolution:
    return resolve_provider_session_registry_path(
        explicit=explicit,
        profile=profile,
        workspace_root=workspace_root,
        base_directory=base_directory,
    )


def _provider_session_registry_path(
    explicit: str | None,
    profile: Mapping[str, object],
    *,
    workspace_root: str | None = None,
) -> str:
    return _provider_session_registry_resolution(
        explicit,
        profile,
        workspace_root=workspace_root,
    ).registry_path


def _provider_session_registry_resolution_from_settings(
    settings: LocalPlatformSettings,
) -> ProviderSessionRegistryPathResolution:
    if settings.provider_session_registry is not None:
        return provider_session_registry_path_resolution(
            settings.provider_session_registry,
            source=(
                settings.provider_session_registry_source or "workspace_derived"
            ),
            source_key=(
                settings.provider_session_registry_source_key or "workspaceRoot"
            ),
        )
    return resolve_provider_session_registry_path(
        workspace_root=settings.workspace_root,
    )


def _with_provider_session_registry_resolution(
    result: Mapping[str, object],
    resolution: ProviderSessionRegistryPathResolution,
) -> Mapping[str, object]:
    refreshed = provider_session_registry_path_resolution(
        resolution.registry_path,
        source=resolution.registry_path_source,
        source_key=resolution.registry_path_source_key,
    )
    return {**dict(result), **refreshed.to_metadata()}


def _provider_session_registry_lookup_error(
    error: ValueError,
    resolution: ProviderSessionRegistryPathResolution,
    *,
    profile_id: str | None = None,
    profile_alias: str | None = None,
) -> ValueError:
    if "provider session profile not found" not in str(error):
        return error
    selector = (
        f"profile id {profile_id}"
        if profile_id is not None
        else (
            f"profile alias {profile_alias}"
            if profile_alias is not None
            else "requested profile"
        )
    )
    source_key = (
        f", source key {resolution.registry_path_source_key}"
        if resolution.registry_path_source_key is not None
        else ""
    )
    return ValueError(
        "provider session profile not found for "
        f"{selector}. Resolved registry path: {resolution.registry_path}; "
        f"source: {resolution.registry_path_source}{source_key}. "
        "Register and join must use the same registry. Retry with: "
        f'--provider-session-registry "{resolution.registry_path}".'
    )


def _runtime_setting(
    logical_name: str,
    explicit: str | None,
    profile: Mapping[str, object],
    *,
    env_keys: tuple[str, ...],
    profile_keys: tuple[str, ...],
) -> str:
    if explicit is not None and explicit.strip():
        return explicit
    for key in profile_keys:
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None:
            raise ValueError(f"profile {key} must be a string.")
    for key in env_keys:
        value = os.environ.get(key)
        if value is not None and value.strip():
            return value.strip()
    raise ValueError(
        f"{logical_name} is required; pass --{logical_name.replace('_', '-')}, "
        "pass --profile <path> or set AGENT_OS_LOCAL_RUNTIME_PROFILE with profile "
        f"key(s) {', '.join(profile_keys)}, or configure environment variable(s) "
        f"{', '.join(env_keys)}."
    )


def _openai_compatible_env(args: argparse.Namespace) -> dict[str, str]:
    env = dict(os.environ)
    _set_env_override(
        env,
        "AGENT_OS_OPENAI_COMPAT_BASE_URL",
        args.openai_compatible_base_url,
    )
    _set_env_override(
        env,
        "AGENT_OS_OPENAI_COMPAT_MODEL",
        args.openai_compatible_model,
    )
    _set_env_override(
        env,
        "AGENT_OS_OPENAI_COMPAT_PROVIDER_NAME",
        args.openai_compatible_provider_name,
    )
    _set_env_override(
        env,
        "AGENT_OS_OPENAI_COMPAT_API_KEY_ENV_VAR",
        args.openai_compatible_api_key_env_var,
    )
    if args.openai_compatible_timeout_seconds is not None:
        env["AGENT_OS_OPENAI_COMPAT_TIMEOUT_SECONDS"] = str(
            args.openai_compatible_timeout_seconds
        )
    return env


def _openai_compatible_parameters(args: argparse.Namespace) -> dict[str, object]:
    parameters: dict[str, object] = {}
    temperature = _optional_float_env(
        "AGENT_OS_OPENAI_COMPAT_TEMPERATURE",
        args.openai_compatible_temperature,
    )
    max_tokens = _optional_int_env(
        "AGENT_OS_OPENAI_COMPAT_MAX_TOKENS",
        args.openai_compatible_max_tokens,
    )
    reasoning_effort = _optional_text_env(
        "AGENT_OS_OPENAI_COMPAT_REASONING_EFFORT",
        args.openai_compatible_reasoning_effort,
    )
    thinking_type = _optional_text_env(
        "AGENT_OS_OPENAI_COMPAT_THINKING_TYPE",
        args.openai_compatible_thinking_type,
    )
    if temperature is not None:
        parameters["temperature"] = temperature
    if max_tokens is not None:
        parameters["max_tokens"] = max_tokens
    if reasoning_effort is not None:
        parameters["reasoning_effort"] = reasoning_effort
    if thinking_type is not None:
        parameters["thinking"] = {"type": thinking_type}
    return parameters


def _provider_env(args: argparse.Namespace) -> dict[str, str]:
    env = dict(os.environ)
    _set_env_override(env, "AGENT_OS_PROVIDER_API_SHAPE", args.provider_api_shape)
    _set_env_override(env, "AGENT_OS_PROVIDER_BASE_URL", args.provider_base_url)
    _set_env_override(env, "AGENT_OS_PROVIDER_MODEL", args.provider_model)
    _set_env_override(env, "AGENT_OS_PROVIDER_NAME", args.provider_name)
    _set_env_override(
        env,
        "AGENT_OS_PROVIDER_API_KEY_ENV_VAR",
        args.provider_api_key_env_var,
    )
    if args.provider_timeout_seconds is not None:
        env["AGENT_OS_PROVIDER_TIMEOUT_SECONDS"] = str(args.provider_timeout_seconds)
    return env


def _provider_parameters(args: argparse.Namespace) -> dict[str, object]:
    parameters: dict[str, object] = {}
    temperature = _optional_float_env(
        "AGENT_OS_PROVIDER_TEMPERATURE",
        args.provider_temperature,
    )
    max_tokens = _optional_int_env(
        "AGENT_OS_PROVIDER_MAX_TOKENS",
        args.provider_max_tokens,
    )
    reasoning_effort = _optional_text_env(
        "AGENT_OS_PROVIDER_REASONING_EFFORT",
        args.provider_reasoning_effort,
    )
    thinking_type = _optional_text_env(
        "AGENT_OS_PROVIDER_THINKING_TYPE",
        args.provider_thinking_type,
    )
    input_mode = _optional_text_env(
        "AGENT_OS_PROVIDER_INPUT_MODE",
        args.provider_input_mode,
    )
    user_agent = _optional_text_env(
        "AGENT_OS_PROVIDER_USER_AGENT",
        args.provider_user_agent,
    )
    if temperature is not None:
        parameters["temperature"] = temperature
    if max_tokens is not None:
        parameters["max_tokens"] = max_tokens
    if reasoning_effort is not None:
        parameters["reasoning_effort"] = reasoning_effort
    if thinking_type is not None:
        parameters["thinking"] = {"type": thinking_type}
    if input_mode is not None:
        parameters["input_mode"] = input_mode
    if user_agent is not None:
        parameters["provider_user_agent"] = user_agent
    return parameters


def _set_env_override(
    env: dict[str, str],
    key: str,
    value: str | None,
) -> None:
    if value is not None:
        env[key] = value


def _optional_float_env(key: str, explicit: float | None) -> float | None:
    if explicit is not None:
        return explicit
    value = os.environ.get(key)
    if value is None or not value.strip():
        return None
    return float(value)


def _optional_int_env(key: str, explicit: int | None) -> int | None:
    if explicit is not None:
        return explicit
    value = os.environ.get(key)
    if value is None or not value.strip():
        return None
    return int(value)


def _optional_text_env(key: str, explicit: str | None) -> str | None:
    if explicit is not None:
        return explicit
    value = os.environ.get(key)
    if value is None or not value.strip():
        return None
    return value.strip()


def _dispatch(
    application: LocalPlatformApplication,
    args: argparse.Namespace,
) -> object:
    if args.command == "init":
        return application.initialize_database()
    if args.command in {"agent-runtime-preflight", "agent-runtime-doctor"}:
        return application.agent_runtime_preflight(
            tools=tuple(args.tool or ()),
            timeout_seconds=args.timeout_seconds,
            ticket_path=args.ticket_path,
            response_path=args.response_path,
        )
    if args.command == "workspace-create":
        return application.create_workspace(
            workspace_id=args.workspace_id,
            context_id=args.context_id,
            agent_id=args.agent_id,
            display_name=args.display_name,
            root_path=args.root_path,
        )
    if args.command == "workspace-list":
        return application.list_workspaces()
    if args.command == "workspace-open":
        return application.open_workspace(args.workspace_id)
    if args.command == "workspace-archive":
        return application.archive_workspace(args.workspace_id)
    if args.command == "agent-create":
        return application.create_agent(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            name=args.name,
            description=args.description,
            default_model=args.default_model,
            capabilities=tuple(
                _json_object_list(args.capabilities_json, "capabilities-json")
            ),
            tool_permissions=tuple(
                _json_string_list(
                    args.tool_permissions_json,
                    "tool-permissions-json",
                )
            ),
            runtime_config=_json_object(
                args.runtime_config_json,
                "runtime-config-json",
            ),
            metadata=_json_object(args.metadata_json, "metadata-json"),
        )
    if args.command == "agent-runtime-permissions":
        return application.list_agent_runtime_permissions(args.workspace_id)
    if args.command == "agent-runtime-permission-get":
        return application.get_agent_runtime_permissions(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
        )
    if args.command == "agent-exchange-instructions":
        return application.agent_exchange_instructions(args.workspace_id)
    if args.command == "agent-exchange-request-instructions":
        return application.agent_exchange_request_instructions(args.workspace_id)
    if args.command == "agent-exchange-request-policy":
        return application.get_agent_exchange_request_policy(args.workspace_id)
    if args.command == "agent-exchange-request-policy-update":
        return application.update_agent_exchange_request_policy(
            workspace_id=args.workspace_id,
            authorization_mode=args.authorization_mode,
            sub_request_policy=args.sub_request_policy,
            thread_workspace_visible=(
                _optional_cli_bool(args.thread_workspace_visible)
            ),
            follow_up_policy=args.follow_up_policy,
            allowed_sub_request_agent_ids=(
                tuple(
                    _optional_json_string_list(
                        args.allowed_sub_request_agent_ids_json,
                        "allowed-sub-request-agent-ids-json",
                    )
                )
                if args.allowed_sub_request_agent_ids_json is not None
                else None
            ),
            max_request_length=args.max_request_length,
            max_response_length=args.max_response_length,
            max_response_tokens=args.max_response_tokens,
            max_turns=args.max_turns,
            max_sub_request_depth=args.max_sub_request_depth,
            max_child_requests=args.max_child_requests,
            auto_append_exchange_result_to_shared_context=(
                True
                if args.auto_append_exchange_result_to_shared_context
                else None
            ),
            metadata=_json_object(args.metadata_json, "metadata-json"),
        )
    if args.command == "agent-exchange-request-create":
        return application.create_agent_exchange_request(
            workspace_id=args.workspace_id,
            exchange_request_id=args.exchange_request_id,
            source_agent_id=args.source_agent_id,
            target_agent_id=args.target_agent_id,
            request_kind=args.request_kind,
            request_summary=args.request_summary,
            agent_session_id=args.agent_session_id,
            connection_instance_id=args.connection_instance_id,
            detail_refs=_detail_refs_from_args(args),
            linked_task_id=args.linked_task_id,
            linked_conversation_id=args.linked_conversation_id,
            linked_activation_id=args.linked_activation_id,
            linked_delegated_wake_grant_id=args.linked_delegated_wake_grant_id,
            parent_request_id=args.parent_request_id,
            root_request_id=args.root_request_id,
            thread_id=args.thread_id,
            turn_index=args.turn_index,
            expires_at=args.expires_at,
            requires_user_review=args.requires_user_review,
            metadata=_metadata_from_args(args),
        )
    if args.command == "agent-exchange-request-list":
        return application.list_agent_exchange_requests(
            workspace_id=args.workspace_id,
            source_agent_id=args.source_agent_id,
            target_agent_id=args.target_agent_id,
            status=args.status,
        )
    if args.command == "agent-exchange-request-get":
        if args.format == "compact":
            return _agent_exchange_compact_status(
                application.get_agent_exchange_status_summary(
                    workspace_id=args.workspace_id,
                    exchange_request_id=args.exchange_request_id,
                    waiting_response_stale_threshold_seconds=(
                        args.waiting_response_stale_threshold_seconds
                    ),
                )
            )
        return application.get_agent_exchange_request_status(
            workspace_id=args.workspace_id,
            exchange_request_id=args.exchange_request_id,
        )
    if args.command == "agent-exchange-status":
        result = application.get_agent_exchange_status_summary(
            workspace_id=args.workspace_id,
            exchange_request_id=args.exchange_request_id,
            dispatch_id=args.dispatch_id,
            thread_id=args.thread_id,
            read_live_runtime_status=args.runtime_status_policy,
            waiting_response_stale_threshold_seconds=(
                args.waiting_response_stale_threshold_seconds
            ),
        )
        return _agent_exchange_compact_status(result) if args.format == "compact" else result
    if args.command == "agent-exchange-request-respond":
        return application.respond_agent_exchange_request(
            workspace_id=args.workspace_id,
            exchange_request_id=args.exchange_request_id,
            responding_agent_id=args.responding_agent_id,
            response_summary=args.response_summary,
            requires_user_review=(
                True if args.requires_user_review else None
            ),
            metadata=_response_metadata_from_args(args),
        )
    if args.command == "agent-exchange-request-close":
        return application.close_agent_exchange_request(
            workspace_id=args.workspace_id,
            exchange_request_id=args.exchange_request_id,
            terminal_reason=args.terminal_reason,
            requires_user_review=(
                True if args.requires_user_review else None
            ),
            metadata=_json_object(args.metadata_json, "metadata-json"),
        )
    if args.command == "agent-dispatch-create":
        return application.create_agent_dispatch(
            workspace_id=args.workspace_id,
            dispatch_id=args.dispatch_id,
            exchange_request_id=args.exchange_request_id,
            source_agent_id=args.source_agent_id,
            target_agent_id=args.target_agent_id,
            source_handle_id=args.source_handle_id,
            target_handle_id=args.target_handle_id,
            target_provider=args.target_provider,
            reply_policy=args.reply_policy,
            request_kind=args.request_kind,
            request_summary=args.request_summary,
            detail_refs=_detail_refs_from_args(args),
            linked_task_id=args.linked_task_id,
            linked_conversation_id=args.linked_conversation_id,
            linked_activation_id=args.linked_activation_id,
            linked_delegated_wake_grant_id=args.linked_delegated_wake_grant_id,
            parent_request_id=args.parent_request_id,
            root_request_id=args.root_request_id,
            thread_id=args.thread_id,
            turn_index=args.turn_index,
            expires_at=_optional_datetime_arg(args.expires_at, "expires-at"),
            requires_user_review=args.requires_user_review,
            metadata=_metadata_from_args(args),
            dry_run=args.dry_run,
        )
    if args.command == "agent-dispatch-send":
        codex_repo_check_policy, codex_repo_check_policy_source = (
            _codex_git_repo_check_policy(
                args,
                _local_runtime_profile(application.settings.profile_path),
            )
        )
        return application.send_agent_dispatch(
            workspace_id=args.workspace_id,
            dispatch_id=args.dispatch_id,
            exchange_request_id=args.exchange_request_id,
            acting_endpoint_alias=args.acting_endpoint_alias,
            from_endpoint_alias=args.from_endpoint_alias,
            to_endpoint_alias=args.to_endpoint_alias,
            source_agent_id=args.source_agent_id,
            target_agent_id=args.target_agent_id,
            source_handle_id=args.source_handle_id,
            target_handle_id=args.target_handle_id,
            target_provider=args.target_provider,
            reply_policy=args.reply_policy,
            request_kind=args.request_kind,
            request_summary=args.request_summary,
            message=args.message,
            detail_refs=_detail_refs_from_args(args),
            linked_task_id=args.linked_task_id,
            linked_conversation_id=args.linked_conversation_id,
            linked_activation_id=args.linked_activation_id,
            linked_delegated_wake_grant_id=args.linked_delegated_wake_grant_id,
            parent_request_id=args.parent_request_id,
            root_request_id=args.root_request_id,
            thread_id=args.thread_id,
            turn_index=args.turn_index,
            expires_at=_optional_datetime_arg(args.expires_at, "expires-at"),
            requires_user_review=args.requires_user_review,
            metadata=_metadata_from_args(args),
            delivery_mode=_dispatch_delivery_mode_from_args(args),
            dispatcher_id=args.dispatcher_id,
            lease_ttl_seconds=args.lease_ttl_seconds,
            retry_delay_seconds=args.retry_delay_seconds,
            handoff_directory=args.handoff_directory,
            platform_workspace_root=args.platform_workspace_root,
            config_path=args.config_path,
            claude_executable=args.claude_executable,
            claude_default_platform_workspace_add_dir=(
                not args.no_claude_default_platform_workspace_add_dir
            ),
            claude_add_dirs=tuple(args.claude_add_dir),
            claude_allowed_tools=tuple(args.claude_allowed_tool),
            claude_permission_mode=args.claude_permission_mode,
            claude_settings_path=args.claude_settings_path,
            codex_executable=args.codex_executable,
            codex_default_platform_workspace_add_dir=(
                not args.no_codex_default_platform_workspace_add_dir
            ),
            codex_add_dirs=tuple(args.codex_add_dir),
            codex_sandbox_mode=args.codex_sandbox_mode,
            codex_approval_policy=args.codex_approval_policy,
            codex_git_repo_check_policy=codex_repo_check_policy,
            codex_git_repo_check_policy_source=codex_repo_check_policy_source,
            hermes_executable=args.hermes_executable,
            hermes_home=args.hermes_home,
            hermes_source_tag=args.hermes_source_tag,
            hermes_max_turns=args.hermes_max_turns,
            activation_timeout_seconds=args.activation_timeout_seconds,
            skip_busy_target=not args.ignore_busy_target,
            read_live_runtime_status=args.runtime_status_policy,
            dry_run=args.dry_run,
        )
    if args.command == "agent-dispatch-list":
        return application.list_agent_dispatches(
            workspace_id=args.workspace_id,
            source_agent_id=args.source_agent_id,
            target_agent_id=args.target_agent_id,
            status=args.status,
            limit=args.limit,
        )
    if args.command == "agent-dispatch-status":
        result = application.get_agent_dispatch_status(
            workspace_id=args.workspace_id,
            dispatch_id=args.dispatch_id,
            exchange_request_id=args.exchange_request_id,
            read_live_runtime_status=args.runtime_status_policy,
            waiting_response_stale_threshold_seconds=(
                args.waiting_response_stale_threshold_seconds
            ),
        )
        return _agent_exchange_compact_status(result) if args.format == "compact" else result
    if args.command == "agent-dispatch-daemon-status":
        return application.get_agent_dispatch_daemon_status(
            workspace_id=args.workspace_id,
            dispatcher_id=args.dispatcher_id,
        )
    if args.command == "agent-dispatch-daemon-start":
        return _start_agent_dispatch_daemon(application, args)
    if args.command == "agent-dispatch-lease-acquire":
        return application.acquire_agent_dispatch_lease(
            workspace_id=args.workspace_id,
            dispatch_id=args.dispatch_id,
            lease_id=args.lease_id,
            acquired_by=args.acquired_by,
            lease_ttl_seconds=args.lease_ttl_seconds,
            metadata=_json_object(args.metadata_json, "metadata-json"),
        )
    if args.command == "agent-dispatch-lease-release":
        return application.release_agent_dispatch_lease(
            workspace_id=args.workspace_id,
            lease_id=args.lease_id,
            released_by=args.released_by,
            final_dispatch_status=args.final_dispatch_status,
            metadata=_json_object(args.metadata_json, "metadata-json"),
        )
    if args.command == "agent-dispatch-lease-reconcile":
        if args.dry_run == args.execute:
            raise ValueError("choose exactly one of --dry-run or --execute.")
        return application.reconcile_agent_dispatch_leases(
            workspace_id=args.workspace_id,
            dispatch_id=args.dispatch_id,
            lease_id=args.lease_id,
            recovered_by=args.recovered_by,
            recovery_delay_seconds=args.recovery_delay_seconds,
            dry_run=args.dry_run,
        )
    if args.command == "agent-dispatch-worker-run-once":
        if args.dry_run == args.execute:
            raise ValueError("choose exactly one of --dry-run or --execute.")
        codex_repo_check_policy, codex_repo_check_policy_source = (
            _codex_git_repo_check_policy(
                args,
                _local_runtime_profile(application.settings.profile_path),
            )
        )
        return application.run_agent_dispatch_worker_once(
            workspace_id=args.workspace_id,
            dispatch_id=args.dispatch_id,
            target_agent_id=args.target_agent_id,
            dispatcher_id=args.dispatcher_id,
            limit=args.limit,
            lease_ttl_seconds=args.lease_ttl_seconds,
            retry_delay_seconds=args.retry_delay_seconds,
            handoff_directory=args.handoff_directory,
            platform_workspace_root=args.platform_workspace_root,
            config_path=args.config_path,
            claude_executable=args.claude_executable,
            claude_default_platform_workspace_add_dir=(
                not args.no_claude_default_platform_workspace_add_dir
            ),
            claude_add_dirs=tuple(args.claude_add_dir),
            claude_allowed_tools=tuple(args.claude_allowed_tool),
            claude_permission_mode=args.claude_permission_mode,
            claude_settings_path=args.claude_settings_path,
            codex_executable=args.codex_executable,
            codex_default_platform_workspace_add_dir=(
                not args.no_codex_default_platform_workspace_add_dir
            ),
            codex_add_dirs=tuple(args.codex_add_dir),
            codex_sandbox_mode=args.codex_sandbox_mode,
            codex_approval_policy=args.codex_approval_policy,
            codex_git_repo_check_policy=codex_repo_check_policy,
            codex_git_repo_check_policy_source=codex_repo_check_policy_source,
            hermes_executable=args.hermes_executable,
            hermes_home=args.hermes_home,
            hermes_source_tag=args.hermes_source_tag,
            hermes_max_turns=args.hermes_max_turns,
            activation_timeout_seconds=args.activation_timeout_seconds,
            skip_busy_target=not args.ignore_busy_target,
            read_live_runtime_status=args.runtime_status_policy,
            dry_run=args.dry_run,
        )
    if args.command == "agent-exchange-thread-instructions":
        return application.agent_exchange_thread_instructions(args.workspace_id)
    if args.command == "agent-exchange-thread-list":
        return application.list_agent_exchange_threads(
            workspace_id=args.workspace_id,
            requesting_agent_id=args.requesting_agent_id,
            status=args.status,
            visibility=args.visibility,
        )
    if args.command == "agent-exchange-thread-get":
        return application.get_agent_exchange_thread_status(
            workspace_id=args.workspace_id,
            thread_id=args.thread_id,
            requesting_agent_id=args.requesting_agent_id,
        )
    if args.command == "agent-exchange-thread-requests":
        return application.list_agent_exchange_thread_requests(
            workspace_id=args.workspace_id,
            thread_id=args.thread_id,
            requesting_agent_id=args.requesting_agent_id,
        )
    if args.command == "agent-exchange-thread-follow-up-create":
        return application.create_agent_exchange_thread_follow_up(
            workspace_id=args.workspace_id,
            thread_id=args.thread_id,
            exchange_request_id=args.exchange_request_id,
            parent_request_id=args.parent_request_id,
            source_agent_id=args.source_agent_id,
            target_agent_id=args.target_agent_id,
            request_kind=args.request_kind,
            request_summary=args.request_summary,
            detail_refs=_detail_refs_from_args(args),
            linked_task_id=args.linked_task_id,
            linked_conversation_id=args.linked_conversation_id,
            linked_activation_id=args.linked_activation_id,
            linked_delegated_wake_grant_id=args.linked_delegated_wake_grant_id,
            requires_user_review=args.requires_user_review,
            metadata=_json_object(args.metadata_json, "metadata-json"),
        )
    if args.command == "agent-exchange-thread-visibility-update":
        return application.update_agent_exchange_thread_visibility(
            workspace_id=args.workspace_id,
            thread_id=args.thread_id,
            updated_by_agent_id=args.updated_by_agent_id,
            visibility=args.visibility,
            metadata=_json_object(args.metadata_json, "metadata-json"),
        )
    if args.command == "agent-exchange-thread-close":
        return application.close_agent_exchange_thread(
            workspace_id=args.workspace_id,
            thread_id=args.thread_id,
            terminal_reason=args.terminal_reason,
            closed_by_agent_id=args.closed_by_agent_id,
            metadata=_json_object(args.metadata_json, "metadata-json"),
        )
    if args.command == "agent-wake-instructions":
        return application.agent_wake_instructions(
            args.workspace_id,
            agent_id=args.agent_id,
        )
    if args.command in {"agent-exchange-wake-watch", "agent-wake-daemon"}:
        return application.run_agent_wake_once(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            profile=_agent_wake_profile_from_args(args),
            config_path=args.config,
            dry_run=args.dry_run,
        )
    if args.command == "agent-wake-delivery-list":
        return application.list_agent_wake_deliveries(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            exchange_request_id=args.exchange_request_id,
            wake_ticket_id=args.wake_ticket_id,
            status=args.status,
            limit=args.limit,
        )
    if args.command == "agent-wake-status":
        return application.get_agent_wake_status(
            workspace_id=args.workspace_id,
            exchange_request_id=args.exchange_request_id,
        )
    if args.command == "agent-wake-ticket-get":
        return application.get_agent_wake_ticket(
            workspace_id=args.workspace_id,
            exchange_request_id=args.exchange_request_id,
            wake_ticket_id=args.wake_ticket_id,
        )
    if args.command == "agent-session-discover":
        return application.discover_agent_sessions(
            provider=args.provider,
            limit=args.limit,
            cwd=args.cwd,
            claude_home=args.claude_home,
            codex_home=args.codex_home,
            hermes_home=args.hermes_home,
            hermes_executable=args.hermes_executable,
            hermes_source=args.hermes_source,
            hermes_timeout_seconds=args.hermes_timeout_seconds,
            current_session_id=args.current_session_id,
            include_turn_snippets=args.include_turn_snippets,
            include_full_session_history=args.include_full_session_history,
            snippet_turn_index=args.snippet_turn_index,
            snippet_max_chars=args.snippet_max_chars,
            provider_account_label=args.provider_account_label,
            vendor_account_label=args.vendor_account_label,
            relay_account_label=args.relay_account_label,
        )
    if args.command == "agent-session-handle-register-discovered":
        return application.register_discovered_agent_session_handle(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            provider=args.provider,
            session_id=args.session_id,
            handle_id=args.handle_id,
            created_by=args.created_by,
            reason=args.reason,
            metadata=_json_object(args.metadata_json, "metadata-json"),
            limit=args.limit,
            cwd=args.cwd,
            claude_home=args.claude_home,
            codex_home=args.codex_home,
            hermes_home=args.hermes_home,
            hermes_executable=args.hermes_executable,
            hermes_source=args.hermes_source,
            hermes_timeout_seconds=args.hermes_timeout_seconds,
            current_session_id=args.current_session_id,
            include_turn_snippets=args.include_turn_snippets,
            snippet_turn_index=args.snippet_turn_index,
            snippet_max_chars=args.snippet_max_chars,
        )
    if args.command == "agent-endpoint-login-discovered":
        return application.login_discovered_agent_endpoint(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            provider=args.provider,
            session_id=args.session_id,
            handle_id=args.handle_id,
            endpoint_id=args.endpoint_id,
            alias=args.alias,
            direction=args.direction,
            default_reply_policy=args.default_reply_policy,
            contact_policy=args.contact_policy,
            created_by=args.created_by,
            reason=args.reason,
            metadata=_json_object(args.metadata_json, "metadata-json"),
            limit=args.limit,
            cwd=args.cwd,
            claude_home=args.claude_home,
            codex_home=args.codex_home,
            hermes_home=args.hermes_home,
            hermes_executable=args.hermes_executable,
            hermes_source=args.hermes_source,
            hermes_timeout_seconds=args.hermes_timeout_seconds,
            current_session_id=args.current_session_id,
            include_turn_snippets=args.include_turn_snippets,
            snippet_turn_index=args.snippet_turn_index,
            snippet_max_chars=args.snippet_max_chars,
            **_endpoint_contact_kwargs_from_args(args),
        )
    if args.command == "agent-onboarding-status":
        return application.get_agent_onboarding_status(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            endpoint_alias=args.endpoint_alias,
            provider=args.provider,
            read_live_runtime_status=args.runtime_status_policy,
        )
    if args.command == "provider-session-workspace-join":
        registry_resolution = _provider_session_registry_resolution_from_settings(
            application.settings
        )
        registry = ProviderSessionRegistry(registry_resolution.registry_path)
        try:
            preflight = registry.preflight_workspace_join(
                profile_id=args.profile_id,
                workspace_id=args.workspace_id,
                agent_id=args.agent_id,
                endpoint_alias=args.endpoint_alias,
            )
        except ValueError as exc:
            raise _provider_session_registry_lookup_error(
                exc,
                registry_resolution,
                profile_id=args.profile_id,
            ) from exc
        if not preflight["ok"]:
            return _with_provider_session_registry_resolution({
                "schema": "provider_session_workspace_join.v1",
                "ok": False,
                "completed": False,
                "failedStage": "workspaceMembership",
                "workspaceId": args.workspace_id,
                "profileId": args.profile_id,
                "error": {
                    "type": "WorkspaceMembershipConflict",
                    "message": "provider session profile is already joined to this workspace with different binding.",
                },
                "conflict": {
                    "providerSessionMembership": preflight.get("existingMembership"),
                    "mismatches": preflight.get("mismatches"),
                },
            }, registry_resolution)
        join_result = application.join_provider_session_workspace(
            workspace_id=args.workspace_id,
            provider_session_profile=preflight["providerSessionProfile"],
            agent_id=args.agent_id,
            agent_name=args.agent_name,
            description=args.description,
            endpoint_alias=args.endpoint_alias,
            direction=args.direction,
            default_reply_policy=args.default_reply_policy,
            contact_policy=args.contact_policy,
            handle_id=args.handle_id,
            endpoint_id=args.endpoint_id,
            created_by=args.created_by,
            reason=args.reason,
            metadata=_json_object(args.metadata_json, "metadata-json"),
            reuse_existing=not args.no_reuse_existing,
        )
        if not join_result.get("ok", True):
            return _with_provider_session_registry_resolution(
                join_result,
                registry_resolution,
            )
        endpoint = join_result["agentEndpoint"]
        membership = registry.upsert_membership(
            profile=preflight["providerSessionProfile"],
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            provider_handle_id=str(join_result["providerHandle"]["handleId"]),
            endpoint_alias=str(endpoint["alias"]),
            endpoint_id=str(endpoint["endpointId"]),
            joined_by=args.created_by,
            reason=args.reason,
            endpoint_readiness=join_result["endpointReadiness"],
        )
        return _with_provider_session_registry_resolution({
            **join_result,
            "providerSessionMembership": membership["providerSessionMembership"],
            "membershipStage": {
                "stage": "workspaceMembership",
                "status": "created" if membership["created"] else "reused",
                "providerSessionMembership": membership["providerSessionMembership"],
            },
        }, registry_resolution)
    if args.command == "agent-provider-onboard":
        return application.onboard_agent_provider(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            agent_name=args.agent_name,
            description=args.description,
            provider=args.provider,
            session_id=_provider_onboard_session_id_from_args(args),
            handle_id=args.handle_id,
            endpoint_id=args.endpoint_id,
            endpoint_alias=args.endpoint_alias,
            direction=args.direction,
            default_reply_policy=args.default_reply_policy,
            contact_policy=args.contact_policy,
            created_by=args.created_by,
            reason=args.reason,
            metadata=_json_object(args.metadata_json, "metadata-json"),
            reuse_existing=not args.no_reuse_existing,
            dry_run=args.dry_run,
            limit=args.limit,
            cwd=args.cwd,
            claude_home=args.claude_home,
            codex_home=args.codex_home,
            hermes_home=args.hermes_home,
            hermes_executable=args.hermes_executable,
            hermes_source=args.hermes_source,
            hermes_timeout_seconds=args.hermes_timeout_seconds,
            current_session_id=args.current_session_id,
            include_turn_snippets=args.include_turn_snippets,
            snippet_turn_index=args.snippet_turn_index,
            snippet_max_chars=args.snippet_max_chars,
            **_endpoint_contact_kwargs_from_args(args),
        )
    if args.command == "agent-endpoint-login":
        return application.login_agent_endpoint(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            endpoint_id=args.endpoint_id,
            alias=args.alias,
            provider=args.provider,
            provider_handle_id=args.provider_handle_id,
            direction=args.direction,
            default_reply_policy=args.default_reply_policy,
            contact_policy=args.contact_policy,
            created_by=args.created_by,
            reason=args.reason,
            metadata=_json_object(args.metadata_json, "metadata-json"),
            **_endpoint_contact_kwargs_from_args(args),
        )
    if args.command == "agent-endpoint-list":
        return application.list_agent_endpoints(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            provider=args.provider,
            include_inactive=args.include_inactive,
        )
    if args.command == "agent-endpoint-get":
        return application.get_agent_endpoint(
            workspace_id=args.workspace_id,
            endpoint_id=args.endpoint_id,
            alias=args.alias,
        )
    if args.command == "agent-endpoint-identity":
        return _agent_endpoint_compact_identity(
            application.get_agent_endpoint(
                workspace_id=args.workspace_id,
                alias=args.alias,
            )
        )
    if args.command == "agent-endpoint-status":
        return application.get_agent_endpoint_status(
            workspace_id=args.workspace_id,
            endpoint_id=args.endpoint_id,
            alias=args.alias,
            limit=args.limit,
            read_live_runtime_status=args.runtime_status_policy,
        )
    if args.command == "agent-provider-runtime-status":
        return application.get_agent_provider_runtime_status(
            workspace_id=args.workspace_id,
            provider=args.provider,
            provider_handle_id=args.provider_handle_id,
            endpoint_id=args.endpoint_id,
            alias=args.alias,
            read_live_runtime_status=args.runtime_status_policy,
        )
    if args.command == "agent-endpoint-deactivate":
        return application.deactivate_agent_endpoint(
            workspace_id=args.workspace_id,
            endpoint_id=args.endpoint_id,
            alias=args.alias,
            deactivated_by=args.deactivated_by,
            reason=args.reason,
        )
    if args.command == "provider-session-workspace-leave":
        registry_resolution = _provider_session_registry_resolution_from_settings(
            application.settings
        )
        registry = ProviderSessionRegistry(registry_resolution.registry_path)
        memberships = registry.list_memberships(
            profile_id=args.profile_id,
            workspace_id=args.workspace_id,
        )["memberships"]
        membership = memberships[0] if memberships else None
        endpoint_result = None
        handle_result = None
        if membership is not None and not args.keep_endpoint:
            try:
                endpoint_result = application.deactivate_agent_endpoint(
                    workspace_id=args.workspace_id,
                    alias=str(membership["endpointAlias"]),
                    deactivated_by=args.left_by,
                    reason=args.reason,
                )
            except ValueError as exc:
                if "not active" not in str(exc):
                    raise
                endpoint_result = {"alreadyInactive": True, "message": str(exc)}
        if membership is not None and args.deactivate_provider_handle:
            provider = str(membership["provider"])
            handle_id = str(membership["providerHandleId"])
            if provider == "claude":
                handle_result = application.deactivate_claude_session_handle(
                    workspace_id=args.workspace_id,
                    handle_id=handle_id,
                    deactivated_by=args.left_by,
                    reason=args.reason,
                )
            elif provider == "codex":
                handle_result = application.deactivate_codex_session_handle(
                    workspace_id=args.workspace_id,
                    handle_id=handle_id,
                    deactivated_by=args.left_by,
                    reason=args.reason,
                )
            elif provider == "hermes":
                handle_result = application.deactivate_hermes_session_handle(
                    workspace_id=args.workspace_id,
                    handle_id=handle_id,
                    deactivated_by=args.left_by,
                    reason=args.reason,
                )
        leave = registry.leave_membership(
            profile_id=args.profile_id,
            workspace_id=args.workspace_id,
            left_by=args.left_by,
            reason=args.reason,
            endpoint_deactivated=endpoint_result is not None,
            provider_handle_deactivated=handle_result is not None,
        )
        return _with_provider_session_registry_resolution({
            **leave,
            "workspaceId": args.workspace_id,
            "endpointResult": endpoint_result,
            "providerHandleResult": handle_result,
            "boundaries": {
                "otherWorkspaceMembershipsAffected": False,
                "providerSessionProfileDeleted": False,
                "providerCredentialsChanged": False,
            },
        }, registry_resolution)
    if args.command == "claude-session-handle-register":
        return application.register_claude_session_handle(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            handle_id=args.handle_id,
            claude_session_uuid=args.claude_session_uuid,
            cwd=args.cwd,
            source_path=args.source_path,
            created_by=args.created_by,
            reason=args.reason,
            metadata=_json_object(args.metadata_json, "metadata-json"),
        )
    if args.command == "claude-session-handle-list":
        return application.list_claude_session_handles(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            include_inactive=args.include_inactive,
        )
    if args.command == "claude-session-handle-get":
        return application.get_claude_session_handle(
            workspace_id=args.workspace_id,
            handle_id=args.handle_id,
        )
    if args.command == "claude-session-handle-deactivate":
        return application.deactivate_claude_session_handle(
            workspace_id=args.workspace_id,
            handle_id=args.handle_id,
            deactivated_by=args.deactivated_by,
            reason=args.reason,
        )
    if args.command == "claude-registered-session-activate":
        if args.dry_run == args.execute:
            raise ValueError("choose exactly one of --dry-run or --execute.")
        return application.activate_claude_registered_session(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            handle_id=args.handle_id,
            exchange_request_id=args.exchange_request_id,
            handoff_directory=args.handoff_directory,
            claude_executable=args.claude_executable,
            platform_workspace_root=args.platform_workspace_root,
            default_platform_workspace_add_dir=(
                not args.no_default_platform_workspace_add_dir
            ),
            add_dirs=tuple(args.add_dir),
            allowed_tools=tuple(args.allowed_tool),
            permission_mode=args.permission_mode,
            settings_path=args.settings_path,
            dry_run=args.dry_run,
            timeout_seconds=args.timeout_seconds,
        )
    if args.command == "codex-session-handle-register":
        return application.register_codex_session_handle(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            handle_id=args.handle_id,
            codex_session_id=args.codex_session_id,
            cwd=args.cwd,
            source_path=args.source_path,
            created_by=args.created_by,
            reason=args.reason,
            metadata=_json_object(args.metadata_json, "metadata-json"),
        )
    if args.command == "codex-session-handle-list":
        return application.list_codex_session_handles(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            include_inactive=args.include_inactive,
        )
    if args.command == "codex-session-handle-get":
        return application.get_codex_session_handle(
            workspace_id=args.workspace_id,
            handle_id=args.handle_id,
        )
    if args.command == "codex-session-handle-deactivate":
        return application.deactivate_codex_session_handle(
            workspace_id=args.workspace_id,
            handle_id=args.handle_id,
            deactivated_by=args.deactivated_by,
            reason=args.reason,
        )
    if args.command == "codex-registered-session-activate":
        if args.dry_run == args.execute:
            raise ValueError("choose exactly one of --dry-run or --execute.")
        codex_repo_check_policy, codex_repo_check_policy_source = (
            _codex_git_repo_check_policy(
                args,
                _local_runtime_profile(application.settings.profile_path),
            )
        )
        return application.activate_codex_registered_session(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            handle_id=args.handle_id,
            exchange_request_id=args.exchange_request_id,
            handoff_directory=args.handoff_directory,
            codex_executable=args.codex_executable,
            platform_workspace_root=args.platform_workspace_root,
            default_platform_workspace_add_dir=(
                not args.no_default_platform_workspace_add_dir
            ),
            add_dirs=tuple(args.add_dir),
            sandbox_mode=args.sandbox_mode,
            approval_policy=args.approval_policy,
            git_repo_check_policy=codex_repo_check_policy,
            git_repo_check_policy_source=codex_repo_check_policy_source,
            dry_run=args.dry_run,
            timeout_seconds=args.timeout_seconds,
        )
    if args.command == "hermes-session-handle-register":
        return application.register_hermes_session_handle(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            handle_id=args.handle_id,
            hermes_session_id=args.hermes_session_id,
            cwd=args.cwd,
            source_path=args.source_path,
            created_by=args.created_by,
            reason=args.reason,
            metadata=_metadata_with_hermes_session_identity(
                _json_object(args.metadata_json, "metadata-json"),
                provider="hermes",
                session_id=args.hermes_session_id,
                hermes_home=args.hermes_home,
                hermes_session_source=args.hermes_session_source,
                identity_source="explicit_handle_registration",
            ),
        )
    if args.command == "hermes-session-handle-list":
        return application.list_hermes_session_handles(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            include_inactive=args.include_inactive,
        )
    if args.command == "hermes-session-handle-get":
        return application.get_hermes_session_handle(
            workspace_id=args.workspace_id,
            handle_id=args.handle_id,
        )
    if args.command == "hermes-session-handle-deactivate":
        return application.deactivate_hermes_session_handle(
            workspace_id=args.workspace_id,
            handle_id=args.handle_id,
            deactivated_by=args.deactivated_by,
            reason=args.reason,
        )
    if args.command == "hermes-registered-session-activate":
        if args.dry_run == args.execute:
            raise ValueError("choose exactly one of --dry-run or --execute.")
        return application.activate_hermes_registered_session(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            handle_id=args.handle_id,
            exchange_request_id=args.exchange_request_id,
            handoff_directory=args.handoff_directory,
            hermes_executable=args.hermes_executable,
            hermes_home=args.hermes_home,
            platform_workspace_root=args.platform_workspace_root,
            source_tag=args.source_tag,
            max_turns=args.max_turns,
            dry_run=args.dry_run,
            timeout_seconds=args.timeout_seconds,
        )
    if args.command == "agent-activation-instructions":
        return application.agent_activation_instructions(args.workspace_id)
    if args.command == "agent-activation-wake":
        return application.wake_agent_activation(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            activation_id=args.activation_id,
            created_by=args.created_by,
            reason=args.reason,
            mode=args.mode,
            connection_surface=args.connection_surface,
            task_id=args.task_id,
            conversation_id=args.conversation_id,
            budget=_agent_activation_budget_from_args(args),
            allowed_contribution_kinds=tuple(
                _optional_json_string_list(
                    args.allowed_contribution_kinds_json,
                    "allowed-contribution-kinds-json",
                )
            ),
            metadata=_json_object(args.metadata_json, "metadata-json"),
        )
    if args.command == "agent-activation-status":
        if args.list:
            return application.list_agent_activations(args.workspace_id)
        return application.get_agent_activation_status(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            activation_id=args.activation_id,
        )
    if args.command == "agent-activation-revoke":
        return application.revoke_agent_activation(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            activation_id=args.activation_id,
            revoked_by=args.revoked_by,
            reason=args.reason,
        )
    if args.command == "agent-delegated-wake-grant-instructions":
        return application.delegated_wake_instructions(args.workspace_id)
    if args.command == "agent-delegated-wake-grant-create":
        return application.create_delegated_wake_grant(
            workspace_id=args.workspace_id,
            delegated_wake_grant_id=args.delegated_wake_grant_id,
            source_agent_id=args.source_agent_id,
            target_agent_id=args.target_agent_id,
            created_by=args.created_by,
            reason=args.reason,
            mode=args.mode,
            task_id=args.task_id,
            conversation_id=args.conversation_id,
            target_activation_mode=args.target_activation_mode,
            target_activation_budget=_delegated_wake_target_budget_from_args(args),
            allowed_contribution_kinds=tuple(
                _optional_json_string_list(
                    args.allowed_contribution_kinds_json,
                    "allowed-contribution-kinds-json",
                )
            ),
            expires_at=args.expires_at,
            metadata=_json_object(args.metadata_json, "metadata-json"),
        )
    if args.command == "agent-delegated-wake-grant-status":
        if args.list:
            return application.list_delegated_wake_grants(args.workspace_id)
        return application.get_delegated_wake_grant_status(
            workspace_id=args.workspace_id,
            delegated_wake_grant_id=args.delegated_wake_grant_id,
            source_agent_id=args.source_agent_id,
        )
    if args.command == "agent-delegated-wake-grant-consume":
        return application.consume_delegated_wake_grant(
            workspace_id=args.workspace_id,
            delegated_wake_grant_id=args.delegated_wake_grant_id,
            consuming_agent_id=args.consuming_agent_id,
        )
    if args.command == "agent-delegated-wake-grant-revoke":
        return application.revoke_delegated_wake_grant(
            workspace_id=args.workspace_id,
            delegated_wake_grant_id=args.delegated_wake_grant_id,
            revoked_by=args.revoked_by,
            reason=args.reason,
        )
    if args.command == "project-directory-coordination-instructions":
        return application.project_directory_coordination_instructions(
            args.workspace_id
        )
    if args.command == "project-directory-coordination-declare":
        return application.declare_project_directory_coordination(
            workspace_id=args.workspace_id,
            directory_coordination_id=args.directory_coordination_id,
            declared_agent_id=args.declared_agent_id,
            project_root=args.project_root,
            git_repository_id=args.git_repository_id,
            linked_task_id=args.linked_task_id,
            linked_conversation_id=args.linked_conversation_id,
            declared_path_scopes=tuple(
                _optional_json_string_list(
                    args.declared_path_scopes_json,
                    "declared-path-scopes-json",
                )
                or ["."]
            ),
            directory_access_intent=args.directory_access_intent,
            last_known_git_head=args.last_known_git_head,
            last_known_branch=args.last_known_branch,
            dirty_state=args.dirty_state,
            uncommitted_change_summary=args.uncommitted_change_summary,
            test_summary=args.test_summary,
            recommended_commit_policy=args.recommended_commit_policy,
            handoff_note=args.handoff_note,
            requires_user_review=args.requires_user_review,
            metadata=_json_object(args.metadata_json, "metadata-json"),
        )
    if args.command == "project-directory-coordination-status":
        if args.list:
            return application.list_project_directory_coordination(args.workspace_id)
        if args.directory_coordination_id is None:
            raise ValueError("directory-coordination-id is required unless --list is used.")
        return application.get_project_directory_coordination_status(
            workspace_id=args.workspace_id,
            directory_coordination_id=args.directory_coordination_id,
        )
    if args.command == "project-directory-coordination-update":
        return application.update_project_directory_coordination(
            workspace_id=args.workspace_id,
            directory_coordination_id=args.directory_coordination_id,
            directory_access_intent=args.directory_access_intent,
            declared_path_scopes=(
                tuple(
                    _optional_json_string_list(
                        args.declared_path_scopes_json,
                        "declared-path-scopes-json",
                    )
                )
                if args.declared_path_scopes_json is not None
                else None
            ),
            last_known_git_head=args.last_known_git_head,
            last_known_branch=args.last_known_branch,
            dirty_state=args.dirty_state,
            uncommitted_change_summary=args.uncommitted_change_summary,
            test_summary=args.test_summary,
            recommended_commit_policy=args.recommended_commit_policy,
            handoff_note=args.handoff_note,
            requires_user_review=(
                True if args.requires_user_review else None
            ),
            metadata=_json_object(args.metadata_json, "metadata-json"),
        )
    if args.command == "project-directory-coordination-complete":
        return application.complete_project_directory_coordination(
            workspace_id=args.workspace_id,
            directory_coordination_id=args.directory_coordination_id,
            last_known_git_head=args.last_known_git_head,
            last_known_branch=args.last_known_branch,
            dirty_state=args.dirty_state,
            uncommitted_change_summary=args.uncommitted_change_summary,
            test_summary=args.test_summary,
            recommended_commit_policy=args.recommended_commit_policy,
            handoff_note=args.handoff_note,
            requires_user_review=(
                True if args.requires_user_review else None
            ),
            metadata=_json_object(args.metadata_json, "metadata-json"),
        )
    if args.command == "conversation-create":
        return application.create_conversation(
            workspace_id=args.workspace_id,
            conversation_id=args.conversation_id,
            agent_id=args.agent_id,
            title=args.title,
            metadata=_json_object(args.metadata_json, "metadata-json"),
        )
    if args.command == "conversation-list":
        return application.list_conversations(args.workspace_id)
    if args.command == "conversation-get":
        return application.get_conversation(
            workspace_id=args.workspace_id,
            conversation_id=args.conversation_id,
        )
    if args.command == "conversation-archive":
        return application.archive_conversation(
            workspace_id=args.workspace_id,
            conversation_id=args.conversation_id,
        )
    if args.command == "conversation-message-append":
        return application.append_conversation_message(
            workspace_id=args.workspace_id,
            conversation_id=args.conversation_id,
            message_id=args.message_id,
            role=args.role,
            content=args.content,
            agent_id=args.agent_id,
            invocation_id=args.invocation_id,
            context_update_id=args.context_update_id,
            run_session_id=args.run_session_id,
            metadata=_metadata_from_args(args),
            exchange_attribution=_exchange_attribution_from_args(args),
        )
    if args.command == "conversation-messages":
        return application.list_conversation_messages(
            workspace_id=args.workspace_id,
            conversation_id=args.conversation_id,
            limit=args.limit,
            offset=args.offset,
        )
    if args.command == "invoke":
        return application.invoke_deterministic(
            workspace_id=args.workspace_id,
            agent_id=args.agent_id,
            instruction=args.instruction,
            invocation_id=args.invocation_id,
            requested_at=args.requested_at,
            session_id=args.session_id,
            idempotency_key=args.idempotency_key,
            correlation_id=args.correlation_id,
            conversation_id=args.conversation_id,
        )
    if args.command == "invoke-json":
        return application.invoke_payload(
            _json_object_with_kv(
                args.payload_json,
                args.payload,
                "payload-json",
                "payload",
            )
            or {}
        )
    if args.command == "context-get":
        return application.get_context(args.workspace_id)
    if args.command == "context-updates":
        return application.list_context_updates(
            workspace_id=args.workspace_id,
            limit=args.limit,
            offset=args.offset,
            update_kind=args.update_kind,
        )
    if args.command == "context-update-get":
        return application.get_context_update(
            workspace_id=args.workspace_id,
            update_id=args.update_id,
        )
    if args.command == "context-append":
        return application.append_context_update(
            workspace_id=args.workspace_id,
            summary=args.summary,
            update_kind=args.update_kind,
            update_id=args.update_id,
            materialized_state_patch=_json_object(args.patch_json, "patch-json"),
            payload=_json_object_with_kv(
                args.payload_json,
                args.payload,
                "payload-json",
                "payload",
            ),
            session_id=args.session_id,
            exchange_attribution=_exchange_attribution_from_args(args),
        )
    if args.command == "records-invocations":
        return application.list_invocation_records(args.workspace_id)
    if args.command == "records-file-operations":
        return application.list_file_operation_records(args.workspace_id)
    if args.command == "session-timeline":
        return application.get_run_session_timeline(
            workspace_id=args.workspace_id,
            session_id=args.session_id,
        )
    if args.command == "smoke":
        _ensure_smoke_runtime_paths(application.settings)
        return application.run_smoke(
            workspace_id=args.workspace_id,
            display_name=args.display_name,
            root_path=args.root_path,
            instruction=args.instruction,
            invocation_id=args.invocation_id,
            session_id=args.session_id,
        )
    raise ValueError(f"unsupported command: {args.command}")


def _ensure_smoke_runtime_paths(settings: LocalPlatformSettings) -> None:
    database = settings.database
    if database != ":memory:":
        Path(database).expanduser().resolve(strict=False).parent.mkdir(
            parents=True,
            exist_ok=True,
        )
    Path(settings.workspace_root).expanduser().resolve(strict=False).mkdir(
        parents=True,
        exist_ok=True,
    )
    Path(settings.plugins_directory).expanduser().resolve(strict=False).mkdir(
        parents=True,
        exist_ok=True,
    )


def _dispatch_provider_session_registry_command(
    args: argparse.Namespace,
    profile: Mapping[str, object],
) -> Mapping[str, object]:
    registry_resolution = _provider_session_registry_resolution(
        args.provider_session_registry,
        profile,
    )
    registry = ProviderSessionRegistry(registry_resolution.registry_path)
    try:
        if args.command == "provider-session-profile-register":
            result = registry.register_profile(
                profile_id=args.profile_id,
                provider=args.provider,
                provider_session_id=args.session_id,
                profile_alias=args.profile_alias,
                cwd=args.cwd,
                source_path=args.source_path,
                created_by=args.created_by,
                reason=args.reason,
                metadata=_metadata_with_hermes_session_identity(
                    _json_object(args.metadata_json, "metadata-json"),
                    provider=args.provider,
                    session_id=args.session_id,
                    hermes_home=args.hermes_home,
                    hermes_session_source=args.hermes_session_source,
                    identity_source="explicit_profile_registration",
                ),
            )
        elif args.command == "provider-session-profile-list":
            result = registry.list_profiles(
                provider=args.provider,
                include_inactive=args.include_inactive,
            )
        elif args.command == "provider-session-profile-get":
            result = registry.get_profile(
                profile_id=args.profile_id,
                profile_alias=args.profile_alias,
                include_inactive_memberships=args.include_inactive_memberships,
            )
        elif args.command == "provider-session-profile-deactivate":
            result = registry.deactivate_profile(
                profile_id=args.profile_id,
                deactivated_by=args.deactivated_by,
                reason=args.reason,
                confirm=args.confirm_deactivate_profile,
            )
        elif args.command == "provider-session-membership-list":
            result = registry.list_memberships(
                profile_id=args.profile_id,
                workspace_id=args.workspace_id,
                include_inactive=args.include_inactive,
            )
        else:
            raise ValueError(
                f"unsupported provider session registry command: {args.command}"
            )
    except ValueError as exc:
        raise _provider_session_registry_lookup_error(
            exc,
            registry_resolution,
            profile_id=getattr(args, "profile_id", None),
            profile_alias=getattr(args, "profile_alias", None),
        ) from exc
    return _with_provider_session_registry_resolution(result, registry_resolution)


def _detail_refs_from_args(args: argparse.Namespace) -> tuple[str, ...]:
    refs: list[str] = []
    for value in _optional_json_string_list(args.detail_refs_json, "detail-refs-json"):
        if value not in refs:
            refs.append(value)
    for value in getattr(args, "detail_ref", ()):
        cleaned = _non_empty_text(value, "detail-ref")
        if cleaned not in refs:
            refs.append(cleaned)
    return tuple(refs)


def _add_exchange_attribution_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--exchange-attribution-request-id")
    parser.add_argument("--exchange-attribution-thread-id")
    parser.add_argument("--exchange-attribution-dispatch-id")
    parser.add_argument("--exchange-attribution-source-type")
    parser.add_argument("--exchange-attribution-author-type")
    parser.add_argument("--exchange-attribution-contribution-kind")
    parser.add_argument("--exchange-attribution-author-agent-id")
    parser.add_argument("--exchange-attribution-source-confidence")
    parser.add_argument("--exchange-attribution-source")


def _dispatch_delivery_mode_from_args(args: argparse.Namespace) -> str:
    delivery_mode = getattr(args, "delivery_mode", None)
    wait_mode = getattr(args, "wait", None)
    queued = bool(getattr(args, "queued", False))
    if wait_mode == "once" and queued:
        raise ValueError("--wait once cannot be combined with --queued.")
    if wait_mode == "once":
        if delivery_mode is not None and delivery_mode != "worker_execute":
            raise ValueError(
                "--wait once requires --delivery-mode worker_execute when both "
                "are provided."
            )
        return "worker_execute"
    if queued:
        if delivery_mode is not None and delivery_mode != "queued":
            raise ValueError(
                "--queued requires --delivery-mode queued when both are provided."
            )
        return "queued"
    return delivery_mode or "queued"


def _metadata_from_args(args: argparse.Namespace) -> dict[str, object] | None:
    return _json_object_with_kv(
        getattr(args, "metadata_json", None),
        getattr(args, "metadata", ()),
        "metadata-json",
        "metadata",
    )


def _exchange_attribution_from_args(
    args: argparse.Namespace,
) -> dict[str, object] | None:
    attribution = _json_object_with_kv(
        getattr(args, "exchange_attribution_json", None),
        (),
        "exchange-attribution-json",
        "exchange-attribution",
    ) or {}
    for key, attribute in (
        ("sourceType", "exchange_attribution_source_type"),
        ("authorType", "exchange_attribution_author_type"),
        ("contributionKind", "exchange_attribution_contribution_kind"),
        ("authorAgentId", "exchange_attribution_author_agent_id"),
        ("sourceConfidence", "exchange_attribution_source_confidence"),
        ("sourceChannel", "exchange_attribution_source"),
    ):
        value = getattr(args, attribute, None)
        if value is not None:
            attribution[key] = _non_empty_text(value, attribute.replace("_", "-"))
    metadata = attribution.get("metadata")
    if metadata is not None and not isinstance(metadata, Mapping):
        raise ValueError("exchange-attribution.metadata must be a JSON object.")
    metadata_payload = dict(metadata or {})
    for key, attribute in (
        ("exchangeRequestId", "exchange_attribution_request_id"),
        ("threadId", "exchange_attribution_thread_id"),
        ("dispatchId", "exchange_attribution_dispatch_id"),
    ):
        value = getattr(args, attribute, None)
        if value is not None:
            metadata_payload[key] = _non_empty_text(value, attribute.replace("_", "-"))
    if metadata_payload:
        attribution["metadata"] = metadata_payload
    return attribution or None


def _endpoint_contact_kwargs_from_args(
    args: argparse.Namespace,
) -> dict[str, tuple[str, ...]]:
    return {
        "allow_source_endpoint_aliases": tuple(args.allow_source_alias),
        "allow_source_agent_ids": tuple(args.allow_source_agent_id),
        "allow_source_handle_ids": tuple(args.allow_source_handle_id),
        "block_source_endpoint_aliases": tuple(args.block_source_alias),
        "block_source_agent_ids": tuple(args.block_source_agent_id),
        "block_source_handle_ids": tuple(args.block_source_handle_id),
    }


def _provider_onboard_session_id_from_args(
    args: argparse.Namespace,
) -> str | None:
    provider_specific = {
        "claude": args.claude_session_uuid,
        "codex": args.codex_session_id,
        "hermes": args.hermes_session_id,
    }[args.provider]
    supplied = [
        value.strip()
        for value in (args.session_id, provider_specific)
        if isinstance(value, str) and value.strip()
    ]
    if not supplied:
        return None
    if len(set(supplied)) > 1:
        raise ValueError(
            "--session-id and provider-specific session id must match when both "
            "are supplied."
        )
    return supplied[0]


def _response_metadata_from_args(args: argparse.Namespace) -> dict[str, object] | None:
    metadata = _metadata_from_args(args) or {}
    if args.response_source is not None:
        metadata["responseSource"] = _non_empty_text(
            args.response_source,
            "response-source",
        )
    if args.actual_writer_agent_id is not None:
        metadata["actualWriterAgentId"] = _non_empty_text(
            args.actual_writer_agent_id,
            "actual-writer-agent-id",
        )
        metadata["claimedRespondingAgentId"] = args.responding_agent_id
    return metadata or None


def _non_empty_text(value: str, logical_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{logical_name} must be a non-empty string.")
    if "\x00" in value:
        raise ValueError(f"{logical_name} must not contain null bytes.")
    return value.strip()


def _metadata_with_hermes_session_identity(
    metadata: Mapping[str, object] | None,
    *,
    provider: str,
    session_id: str,
    hermes_home: str | None,
    hermes_session_source: str | None,
    identity_source: str,
) -> dict[str, object] | None:
    payload = dict(metadata or {})
    requested_identity = hermes_home is not None or hermes_session_source is not None
    normalized_provider = provider.strip().lower().replace("_", "-")
    is_hermes = normalized_provider in {"hermes", "hermes-cli", "hermes-desktop"}
    if requested_identity and not is_hermes:
        raise ValueError(
            "--hermes-home and --hermes-session-source require a Hermes provider."
        )
    if not is_hermes or not requested_identity:
        return payload or None

    existing = payload.get("hermesSessionIdentity")
    identity = dict(existing) if isinstance(existing, Mapping) else {}
    resolved_home = None
    if hermes_home is not None:
        home_path = Path(_non_empty_text(hermes_home, "hermes-home")).expanduser()
        home_path = home_path.resolve(strict=False)
        if not home_path.is_dir():
            raise ValueError("hermes-home must be an existing directory.")
        resolved_home = str(home_path)
    session_source = (
        _non_empty_text(hermes_session_source, "hermes-session-source")
        if hermes_session_source is not None
        else None
    )
    identity.update(
        {
            key: value
            for key, value in {
                "schema": "hermes_session_identity.v1",
                "providerSessionId": _non_empty_text(session_id, "session-id"),
                "discoverySource": identity_source,
                "runtimeHome": resolved_home,
                "runtimeHomeSource": "explicit" if resolved_home is not None else None,
                "sessionSource": session_source,
                "fullSessionHistoryRead": False,
            }.items()
            if value is not None
        }
    )
    payload["hermesSessionIdentity"] = identity
    return payload


def _json_object(value: str | None, logical_name: str) -> dict[str, object] | None:
    if value is None:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{logical_name} must be a JSON object.")
    return parsed


def _json_object_with_kv(
    json_value: str | None,
    pairs: Sequence[str] | None,
    json_logical_name: str,
    pair_logical_name: str,
) -> dict[str, object] | None:
    payload = _json_object(json_value, json_logical_name) or {}
    for raw_pair in pairs or ():
        key, value = _key_value_pair(raw_pair, pair_logical_name)
        payload[key] = value
    return payload or None


def _key_value_pair(raw_pair: str, logical_name: str) -> tuple[str, object]:
    if "=" not in raw_pair:
        raise ValueError(f"{logical_name} must use key=value syntax.")
    key, raw_value = raw_pair.split("=", 1)
    key = _non_empty_text(key, f"{logical_name}.key")
    if "\x00" in raw_value:
        raise ValueError(f"{logical_name}.value must not contain null bytes.")
    try:
        value: object = json.loads(raw_value)
    except json.JSONDecodeError:
        value = raw_value
    return key, value


def _json_object_list(value: str | None, logical_name: str) -> list[dict[str, object]]:
    if value is None:
        return []
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not all(
        isinstance(item, dict) for item in parsed
    ):
        raise ValueError(f"{logical_name} must be a JSON array of objects.")
    return parsed


def _json_string_list(value: str | None, logical_name: str) -> list[str]:
    if value is None:
        return ["workspace.read"]
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not all(
        isinstance(item, str) and item.strip() for item in parsed
    ):
        raise ValueError(f"{logical_name} must be a JSON array of strings.")
    return [item.strip() for item in parsed]


def _optional_json_string_list(value: str | None, logical_name: str) -> list[str]:
    if value is None:
        return []
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not all(
        isinstance(item, str) and item.strip() for item in parsed
    ):
        raise ValueError(f"{logical_name} must be a JSON array of strings.")
    return [item.strip() for item in parsed]


def _optional_cli_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError("boolean CLI values must be true or false.")


def _optional_datetime_arg(value: str | None, logical_name: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{logical_name} must be an ISO datetime string.") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _agent_activation_budget_from_args(args: argparse.Namespace) -> dict[str, object] | None:
    budget = _json_object(args.budget_json, "budget-json") or {}
    for key, value in (
        ("ttlSeconds", args.ttl_seconds),
        ("maxOperations", args.max_operations),
        ("maxWrites", args.max_writes),
        ("maxAgentToAgentTurns", args.max_agent_to_agent_turns),
        ("maxContextReads", args.max_context_reads),
        ("maxEstimatedTokens", args.max_estimated_tokens),
    ):
        if value is not None:
            budget[key] = value
    return budget or None


def _delegated_wake_target_budget_from_args(
    args: argparse.Namespace,
) -> dict[str, object] | None:
    budget = _json_object(
        args.target_activation_budget_json,
        "target-activation-budget-json",
    ) or {}
    for key, value in (
        ("ttlSeconds", args.target_ttl_seconds),
        ("maxOperations", args.target_max_operations),
        ("maxWrites", args.target_max_writes),
        ("maxAgentToAgentTurns", args.target_max_agent_to_agent_turns),
        ("maxContextReads", args.target_max_context_reads),
    ):
        if value is not None:
            budget[key] = value
    return budget or None


def _agent_wake_profile_from_args(args: argparse.Namespace) -> dict[str, object]:
    profile: dict[str, object] = {}
    if args.config is not None:
        loaded = _json_object_file(args.config, "config")
        raw_profile = loaded.get("agentWakeProfile", loaded)
        if not isinstance(raw_profile, dict):
            raise ValueError("config agentWakeProfile must be a JSON object.")
        profile.update(raw_profile)
        profile["configPath"] = args.config
    profile["workspaceId"] = args.workspace_id
    profile["agentId"] = args.agent_id
    for key, value in (
        ("wakeMode", args.wake_mode),
        ("pollIntervalMs", args.poll_interval_ms),
        ("maxWakeAttemptsPerRequest", args.max_wake_attempts_per_request),
        ("cooldownMs", args.cooldown_ms),
        ("handoffDirectory", args.handoff_directory),
        ("childProcessPolicy", args.child_process_policy),
    ):
        if value is not None:
            profile[key] = value
    if args.enabled is not None:
        profile["enabled"] = _optional_cli_bool(args.enabled)
    if args.command_argv_json is not None:
        profile["commandArgv"] = _optional_json_string_list(
            args.command_argv_json,
            "command-argv-json",
        )
    return profile


_AGENT_HELP_TOPICS: dict[str, Mapping[str, object]] = {
    "onboarding": {
        "summary": (
            "Profile-first path: resolve a local runtime profile, create or reuse "
            "a workspace agent, bind a provider session handle, login an endpoint "
            "alias, then check alias dispatch readiness."
        ),
        "flow": (
            "local-runtime-profile-init",
            "agent-provider-onboard",
            "agent-onboarding-status",
            "agent-dispatch-send",
        ),
        "commands": (
            {
                "command": "local-runtime-profile-init",
                "purpose": "Create an isolated workspace database/root/plugins path and reusable --profile file.",
            },
            {
                "command": "agent-provider-onboard",
                "purpose": "Idempotently create/reuse agent, provider handle, and endpoint alias.",
            },
            {
                "command": "agent-onboarding-status",
                "purpose": "Read workspace agents, handles, endpoint aliases, readiness, and next actions.",
            },
            {
                "command": "agent-help --topic status",
                "purpose": "See the short status/debug command set.",
            },
        ),
    },
    "session": {
        "summary": (
            "Provider sessions are local Beacon bindings to existing Claude, "
            "Codex, or Hermes sessions. Discovery and reusable local provider "
            "session profiles are metadata-only by default."
        ),
        "flow": (
            "provider-session-profile-register",
            "provider-session-workspace-join",
            "provider-session-membership-list",
            "agent-session-discover",
            "agent-session-handle-register-discovered",
            "claude/codex/hermes-session-handle-list",
            "agent-provider-onboard",
        ),
        "commands": (
            {
                "command": "provider-session-profile-register",
                "purpose": "Create/reuse a local provider session metadata profile that is not bound to one workspace.",
            },
            {
                "command": "provider-session-workspace-join",
                "purpose": "Explicitly bind a local provider session profile into one workspace as agent, handle, and endpoint alias.",
            },
            {
                "command": "provider-session-membership-list",
                "purpose": "List the workspaces joined by a local provider session profile.",
            },
            {
                "command": "provider-session-workspace-leave",
                "purpose": "Leave one workspace membership without deleting the local provider session profile or other workspaces.",
            },
            {
                "command": "agent-session-discover",
                "purpose": "Find registration-ready provider session metadata without reading full transcripts.",
            },
            {
                "command": "agent-session-handle-register-discovered",
                "purpose": "Register a discovered provider session handle.",
            },
            {
                "command": "codex-session-handle-list",
                "purpose": "List Codex handles directly; Claude/Hermes have matching provider-specific list commands.",
            },
            {
                "command": "agent-provider-onboard",
                "purpose": "Preferred combined path for new agents.",
            },
        ),
    },
    "endpoint": {
        "summary": (
            "Endpoint login creates a Beacon-local alias for a registered provider "
            "session handle. It is not provider account authentication."
        ),
        "flow": (
            "agent-endpoint-login",
            "agent-endpoint-identity --alias <alias>",
            "agent-endpoint-list",
            "agent-endpoint-status",
            "agent-onboarding-status --endpoint-alias <alias>",
        ),
        "commands": (
            {
                "command": "agent-endpoint-login",
                "purpose": "Bind alias, agent id, provider, handle id, direction, reply policy, and contact policy.",
            },
            {
                "command": "agent-endpoint-identity --alias <alias>",
                "purpose": "Read one explicitly named alias as a compact routing identity; this is not caller authentication.",
            },
            {
                "command": "agent-endpoint-list",
                "purpose": "List endpoint aliases by workspace, agent, or provider.",
            },
            {
                "command": "agent-endpoint-status",
                "purpose": "Read endpoint inbox/outbox, reply reachability, runtime status, and daemon status.",
            },
            {
                "command": "agent-onboarding-status --endpoint-alias <alias>",
                "purpose": "Check whether an alias is ready as a dispatch target.",
            },
        ),
    },
    "dispatch": {
        "summary": (
            "Alias dispatch sends through Beacon queue state. Daemon polling and "
            "worker_execute affect delivery timing, not endpoint login semantics."
        ),
        "flow": (
            "agent-dispatch-send --as <source> --to <target> --queued",
            "agent-dispatch-daemon-start",
            "agent-dispatch-worker-run-once",
            "agent-dispatch-lease-reconcile --dry-run",
            "agent-dispatch-status",
        ),
        "commands": (
            {
                "command": "agent-dispatch-send",
                "purpose": "Declare --as source and --to target, preview the route, or create request/dispatch state; --as is not authentication.",
            },
            {
                "command": "agent-dispatch-daemon-start",
                "purpose": "Start local polling with auto configured-probe reads and bounded busy/blocked backoff.",
            },
            {
                "command": "agent-dispatch-worker-run-once",
                "purpose": "Run one bounded worker pass; use --execute only when you want delivery attempted now.",
            },
            {
                "command": "agent-dispatch-status",
                "purpose": "Inspect dispatch, retry, lease, wake, and provider runtime status.",
            },
            {
                "command": "agent-dispatch-lease-reconcile",
                "purpose": "Preview or repair expired/orphan workspace dispatch leases without reactivating terminal requests.",
            },
        ),
    },
    "status": {
        "summary": (
            "Use the grouped status commands when deciding whether an alias can be "
            "found and delivered to without reading the full argparse command wall."
        ),
        "flow": (
            "agent-onboarding-status",
            "agent-endpoint-status",
            "agent-dispatch-daemon-status",
            "agent-provider-runtime-status",
            "agent-dispatch-status --format compact",
            "agent-dispatch-lease-reconcile --dry-run",
        ),
        "commands": (
            {
                "command": "agent-onboarding-status",
                "purpose": "One-command inventory for workspace, agents, handles, endpoints, readiness, and next actions.",
            },
            {
                "command": "agent-endpoint-status",
                "purpose": "Detailed per-alias queue and runtime status.",
            },
            {
                "command": "agent-dispatch-daemon-status",
                "purpose": "Read persisted daemon liveness and last error/exit hints.",
            },
            {
                "command": "agent-provider-runtime-status",
                "purpose": "Read metadata state and auto-run only a configured safe local JSON probe; policy can be disabled or enabled.",
            },
            {
                "command": "agent-dispatch-status",
                "purpose": "Read one dispatch; compact includes busy backoff and advisory waiting-response aging without the full timeline.",
            },
            {
                "command": "agent-dispatch-lease-reconcile --dry-run",
                "purpose": "Preview active leases that are recoverable because their request is terminal or their TTL expired.",
            },
        ),
    },
}


def _agent_help(topic: str) -> Mapping[str, object]:
    data = _AGENT_HELP_TOPICS[topic]
    return {
        "schema": "agent_help.v1",
        "topic": topic,
        "summary": data["summary"],
        "flow": list(data["flow"]),
        "commands": [dict(item) for item in data["commands"]],
        "boundaries": {
            "profileFirst": True,
            "providerOnboardCommand": "agent-provider-onboard",
            "credentialStored": False,
            "providerSessionProfileIsAccountLogin": False,
            "fullProviderTranscriptRead": False,
            "internalMigrationHistoryIncluded": False,
            "callerIdentityAuthenticated": False,
            "automaticCurrentSessionDetection": False,
        },
    }


def _text_output_requested(args: argparse.Namespace, result: object) -> bool:
    return (
        isinstance(result, Mapping)
        and args.command in {"agent-help", "agent-onboarding-status"}
        and getattr(args, "format", "json") == "pretty"
    )


def _agent_endpoint_compact_identity(
    endpoint_result: Mapping[str, object],
) -> Mapping[str, object]:
    endpoint = _mapping_value(endpoint_result.get("agentEndpoint"))
    metadata = _mapping_value(endpoint.get("metadata"))
    membership = _mapping_value(metadata.get("providerSessionWorkspaceJoin"))
    direction = str(endpoint.get("direction") or "unknown")
    state = str(endpoint.get("state") or "unknown")
    return {
        "schema": "agent_endpoint_identity_compact.v1",
        "workspaceId": endpoint.get("workspaceId"),
        "alias": endpoint.get("alias"),
        "agentId": endpoint.get("agentId"),
        "provider": endpoint.get("provider"),
        "providerHandleId": endpoint.get("providerHandleId"),
        "direction": direction,
        "state": state,
        "active": state == "active",
        "canSend": direction in {"send_only", "send_receive"},
        "canReceive": direction in {"receive_only", "send_receive"},
        "providerSessionProfile": (
            {
                "profileId": membership.get("profileId"),
                "profileAlias": membership.get("profileAlias"),
                "membershipId": membership.get("membershipId"),
            }
            if membership
            else None
        ),
        "identityBoundary": {
            "schema": "agent_endpoint_identity_boundary.v1",
            "aliasExplicitlyRequested": True,
            "automaticallyDetectedCurrentSession": False,
            "callerAuthenticated": False,
            "credentialVerified": False,
            "sourceOverridePrevented": False,
            "meaning": (
                "This identifies the explicitly requested Beacon endpoint alias. "
                "It does not identify or authenticate the OS/CLI process running the command."
            ),
        },
    }


def _agent_exchange_compact_status(
    status: Mapping[str, object],
) -> Mapping[str, object]:
    request = _mapping_value(status.get("agentExchangeRequest"))
    dispatch = _mapping_value(status.get("agentDispatch"))
    wake = _mapping_value(status.get("wakeStatus"))
    if not wake:
        wake = _mapping_value(request.get("wakeDeliverySummary"))
    response = _mapping_value(status.get("responseSourceStatus"))
    if not response:
        response = _mapping_value(request.get("responseSourceStatus"))
    dispatch_metadata = _mapping_value(dispatch.get("metadata"))
    send_metadata = _mapping_value(dispatch_metadata.get("agentDispatchSend"))
    route = _mapping_value(send_metadata.get("endpointAliasResolution"))
    source_endpoint = _mapping_value(route.get("sourceEndpoint"))
    target_endpoint = _mapping_value(route.get("targetEndpoint"))
    latest_activation = _latest_provider_activation(wake, dispatch)
    provider_command_started = bool(
        wake.get("providerCommandStarted")
        or latest_activation.get("providerCommandStarted")
    )
    provider_failure_category = (
        latest_activation.get("failureCategory")
        or dispatch_metadata.get("failureCategory")
    )
    provider_failure_reason = (
        latest_activation.get("failureReason")
        or dispatch_metadata.get("failureReason")
    )
    provider_failed = bool(
        provider_failure_category
        or provider_failure_reason
        or latest_activation.get("status") == "failed"
    )
    provider_command_status = (
        "failed"
        if provider_failed
        else (
            str(latest_activation.get("status"))
            if latest_activation.get("status") is not None
            else ("started" if provider_command_started else "not_started")
        )
    )
    wake_delivered = bool(wake.get("ticketDeliveryOccurred"))
    target_response_completed = bool(
        wake.get("targetResponseCompleted")
        or latest_activation.get("targetResponseCompleted")
        or response.get("responded")
    )
    standard_respond_written = bool(response.get("standardResponded"))
    request_status = str(request.get("status") or "missing")
    dispatch_status = (
        str(dispatch.get("status")) if dispatch.get("status") is not None else None
    )
    response_source = response.get("responseSource")
    waiting_response = _mapping_value(status.get("waitingResponseStatus"))
    busy_backoff = _mapping_value(status.get("busyBackoffStatus"))
    recommended_action = _compact_status_recommended_action(
        request_status=request_status,
        dispatch_status=dispatch_status,
        wake_delivered=wake_delivered,
        provider_command_started=provider_command_started,
        provider_failed=provider_failed,
        target_response_completed=target_response_completed,
    )
    if waiting_response.get("recommendedAction") is not None:
        recommended_action = waiting_response.get("recommendedAction")
    return {
        "schema": "agent_exchange_compact_status.v1",
        "workspaceId": request.get("workspaceId") or dispatch.get("workspaceId"),
        "requestId": request.get("exchangeRequestId") or dispatch.get("exchangeRequestId"),
        "dispatchId": dispatch.get("dispatchId"),
        "source": {
            "alias": source_endpoint.get("alias"),
            "agentId": request.get("sourceAgentId") or dispatch.get("sourceAgentId"),
            "providerHandleId": dispatch.get("sourceHandleId"),
            "provider": source_endpoint.get("provider"),
        },
        "target": {
            "alias": target_endpoint.get("alias"),
            "agentId": request.get("targetAgentId") or dispatch.get("targetAgentId"),
            "providerHandleId": dispatch.get("targetHandleId"),
            "provider": target_endpoint.get("provider") or dispatch.get("targetProvider"),
        },
        "requestStatus": request_status,
        "dispatchStatus": dispatch_status,
        "wakeDelivered": wake_delivered,
        "providerCommandStarted": provider_command_started,
        "providerCommandStatus": provider_command_status,
        "providerFailure": (
            {
                "category": provider_failure_category,
                "reason": provider_failure_reason,
            }
            if provider_failed
            else None
        ),
        "targetResponseCompleted": target_response_completed,
        "standardRespondWritten": standard_respond_written,
        "responseSource": response_source,
        "busyBackoff": {
            "busySkipCount": busy_backoff.get(
                "busySkipCount",
                dispatch.get("busySkipCount", 0),
            ),
            "lastBusySkipAt": busy_backoff.get(
                "lastBusySkipAt",
                dispatch.get("lastBusySkipAt"),
            ),
            "busyRetryDelaySeconds": busy_backoff.get(
                "busyRetryDelaySeconds",
                dispatch.get("busyRetryDelaySeconds"),
            ),
            "nextAttemptAfter": busy_backoff.get(
                "nextAttemptAfter",
                dispatch.get("nextAttemptAfter"),
            ),
            "active": busy_backoff.get(
                "active",
                dispatch.get("busyBackoffActive", False),
            ),
        },
        "waitingResponseAgeSeconds": waiting_response.get(
            "waitingResponseAgeSeconds"
        ),
        "waitingResponseStale": waiting_response.get(
            "waitingResponseStale",
            False,
        ),
        "staleThresholdSeconds": waiting_response.get(
            "staleThresholdSeconds"
        ),
        "waitingResponseReason": waiting_response.get("reasonCode"),
        "recommendedAction": recommended_action,
        "statusLayers": {
            "request": {
                "created": request_status != "missing",
                "status": request_status,
                "meaning": "Request creation records durable intent only.",
            },
            "delivery": {
                "wakeTicketDelivered": wake_delivered,
                "meaning": "Wake-ticket delivery does not prove provider activation or response.",
            },
            "activation": {
                "providerCommandStarted": provider_command_started,
                "status": provider_command_status,
                "failed": provider_failed,
                "meaning": "Provider command state is separate from target response state.",
            },
            "response": {
                "targetResponseCompleted": target_response_completed,
                "standardRespondWritten": standard_respond_written,
                "responseSource": response_source,
                "meaning": (
                    "Target completion and standard_respond are explicit response signals, "
                    "not synonyms for request creation or wake delivery."
                ),
            },
            "waiting": {
                "waitingResponse": waiting_response.get(
                    "waitingResponse",
                    dispatch_status == "waiting_response",
                ),
                "ageSeconds": waiting_response.get(
                    "waitingResponseAgeSeconds"
                ),
                "stale": waiting_response.get("waitingResponseStale", False),
                "recommendedAction": waiting_response.get(
                    "recommendedAction"
                ),
                "automaticRetryScheduled": waiting_response.get(
                    "automaticRetryScheduled",
                    False,
                ),
                "meaning": (
                    "Waiting-response aging is advisory and never reactivates the provider automatically."
                ),
            },
        },
        "timelineIncluded": False,
        "wakeTicketIncluded": False,
        "privateReasoningRead": False,
    }


def _latest_provider_activation(
    wake: Mapping[str, object],
    dispatch: Mapping[str, object],
) -> Mapping[str, object]:
    provider = str(dispatch.get("targetProvider") or "").lower()
    preferred_key = {
        "claude": "latestClaudeRegisteredSessionActivation",
        "codex": "latestCodexRegisteredSessionActivation",
        "hermes": "latestHermesRegisteredSessionActivation",
    }.get(provider)
    if preferred_key is not None:
        preferred = _mapping_value(wake.get(preferred_key))
        if preferred:
            return preferred
    for key in (
        "latestClaudeRegisteredSessionActivation",
        "latestCodexRegisteredSessionActivation",
        "latestHermesRegisteredSessionActivation",
    ):
        candidate = _mapping_value(wake.get(key))
        if candidate:
            return candidate
    return {}


def _compact_status_recommended_action(
    *,
    request_status: str,
    dispatch_status: str | None,
    wake_delivered: bool,
    provider_command_started: bool,
    provider_failed: bool,
    target_response_completed: bool,
) -> str:
    if target_response_completed:
        return "read_response"
    if request_status == "terminal":
        return "inspect_terminal_request"
    if provider_failed:
        return "inspect_provider_failure"
    if dispatch_status == "retry_scheduled":
        return "wait_for_retry_or_run_worker"
    if not wake_delivered:
        return "run_worker_or_daemon"
    if provider_command_started:
        return "wait_for_target_response"
    return "inspect_delivery_and_activation"


def _mapping_value(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text_output(args: argparse.Namespace, result: object) -> str:
    payload = dict(result) if isinstance(result, Mapping) else {}
    if args.command == "agent-help":
        return _agent_help_text(payload)
    if args.command == "agent-onboarding-status":
        return _agent_onboarding_status_text(payload)
    return str(result)


def _agent_help_text(payload: Mapping[str, object]) -> str:
    lines = [
        f"Beacon agent help: {payload.get('topic')}",
        str(payload.get("summary", "")),
        "",
        "Flow:",
    ]
    lines.extend(f"- {item}" for item in payload.get("flow", ()))
    lines.append("")
    lines.append("Commands:")
    for item in payload.get("commands", ()):
        if not isinstance(item, Mapping):
            continue
        lines.append(f"- {item.get('command')}: {item.get('purpose')}")
    lines.append("")
    lines.append(
        "Boundaries: Beacon does not store provider credentials or read full provider transcripts for these helpers."
    )
    return "\n".join(lines)


def _agent_onboarding_status_text(payload: Mapping[str, object]) -> str:
    workspace = payload.get("workspace")
    runtime = payload.get("runtime")
    readiness = payload.get("dispatchReadiness")
    handles = payload.get("providerSessionHandles")
    endpoints = payload.get("endpointAliases")
    provider_profiles = payload.get("providerSessionProfiles")
    next_actions = payload.get("nextActions")
    lines = ["Beacon onboarding status"]
    if isinstance(workspace, Mapping):
        exists = "exists" if workspace.get("exists") else "missing"
        lines.append(f"workspace: {workspace.get('workspaceId')} ({exists})")
    if isinstance(runtime, Mapping):
        profile_path = runtime.get("profilePath") or "not provided"
        lines.append(f"profile: {profile_path}")
    if isinstance(readiness, Mapping):
        lines.append(f"ready: {str(bool(readiness.get('ready'))).lower()}")
        lines.append(f"nextAction: {payload.get('nextAction')}")
        missing = payload.get("missing") or ()
        if missing:
            lines.append("missing: " + ", ".join(str(item) for item in missing))
    if isinstance(handles, Mapping):
        lines.append(
            f"handles: {handles.get('count', 0)} total, {handles.get('activeCount', 0)} active"
        )
        for item in handles.get("handles", ())[:8]:
            if not isinstance(item, Mapping):
                continue
            session = item.get("session")
            session_id = session.get("id") if isinstance(session, Mapping) else None
            lines.append(
                "- handle "
                f"{item.get('provider')}:{item.get('handleId')} "
                f"agent={item.get('agentId')} active={str(bool(item.get('active'))).lower()} "
                f"session={session_id}"
            )
    if isinstance(endpoints, Mapping):
        lines.append(f"endpoints: {endpoints.get('count', 0)}")
        for item in endpoints.get("endpoints", ())[:8]:
            if not isinstance(item, Mapping):
                continue
            reasons = item.get("notReadyReasons") or ()
            reason_text = (
                f" reasons={','.join(str(reason) for reason in reasons)}"
                if reasons
                else ""
            )
            lines.append(
                "- endpoint "
                f"{item.get('alias')} provider={item.get('provider')} "
                f"direction={item.get('direction')} ready={str(bool(item.get('readyForDispatch'))).lower()}"
                f"{reason_text}"
            )
    if isinstance(provider_profiles, Mapping):
        lines.append(
            "providerSessionProfiles: "
            f"{provider_profiles.get('count', 0)} memberships, "
            f"{provider_profiles.get('activeMembershipCount', 0)} active, "
            f"autoWorkerActivation={str(bool(provider_profiles.get('automaticWorkerActivationAllowed'))).lower()}"
        )
        for item in provider_profiles.get("memberships", ())[:8]:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "- provider profile "
                f"{item.get('profileAlias') or item.get('profileId')} "
                f"workspace={item.get('workspaceId')} "
                f"endpoint={item.get('endpointAlias')} state={item.get('state')}"
            )
    if isinstance(next_actions, (list, tuple)) and next_actions:
        lines.append("commands:")
        for action in next_actions[:5]:
            if not isinstance(action, Mapping):
                continue
            command = action.get("command")
            if command:
                lines.append(f"- {action.get('kind')}: {command}")
    return "\n".join(lines)


def _json_object_file(path: str, logical_name: str) -> dict[str, object]:
    with open(path, "r", encoding="utf-8") as handle:
        parsed = json.load(handle)
    if not isinstance(parsed, dict):
        raise ValueError(f"{logical_name} must contain a JSON object.")
    return parsed


def _write_json(value: object, *, pretty: bool, stream) -> None:
    kwargs = {"ensure_ascii": False}
    if pretty:
        kwargs.update({"indent": 2, "sort_keys": True})
    stream.write(json.dumps(value, **kwargs))
    stream.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
