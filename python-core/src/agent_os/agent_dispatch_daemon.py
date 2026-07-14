from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Mapping, Sequence

from agent_os.application.services.local_platform_application import (
    LocalPlatformApplication,
)
from agent_os.application.services.agent_provider_runtime_status import (
    normalize_provider_runtime_status_read_policy,
)
from agent_os.infrastructure.config import LocalPlatformSettings
from agent_os.local_runtime import (
    _codex_git_repo_check_policy,
    _local_runtime_profile,
    _profile_path_from_argv,
    _runtime_setting,
    _workspace_id_default,
)
from agent_os.stdio import configure_utf8_stdio


def main(argv: Sequence[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = _build_parser()
    raw_argv = tuple(sys.argv[1:] if argv is None else argv)
    application: LocalPlatformApplication | None = None
    args: argparse.Namespace | None = None
    workspace_id: str | None = None
    profile_path: str | None = None
    try:
        profile_path = _resolved_profile_path(_profile_path_from_argv(raw_argv))
        profile = _local_runtime_profile(profile_path)
        args = parser.parse_args(raw_argv)
        if profile_path is None:
            profile_path = _resolved_profile_path(args.profile)
        workspace_id = args.workspace_id or _workspace_id_default(profile)
        if workspace_id is None:
            raise ValueError(
                "workspaceId is required; pass --workspace-id, set it in the "
                "local runtime profile, or configure AGENT_OS_WORKSPACE_ID."
            )
        application = LocalPlatformApplication(
            _settings_from_args(args, profile, profile_path=profile_path),
        )
        _validate_daemon_args(args)
        return _run_daemon(
            application,
            args=args,
            workspace_id=workspace_id,
            profile_path=profile_path,
        )
    except KeyboardInterrupt:
        if application is not None and args is not None and workspace_id is not None:
            _safe_record_exit(
                application,
                args=args,
                workspace_id=workspace_id,
                profile_path=profile_path,
                reason="interrupted",
            )
        _write_line("agent dispatch daemon graceful shutdown: interrupted")
        return 0
    except (TypeError, ValueError, OSError, RuntimeError) as exc:
        if application is not None and args is not None and workspace_id is not None:
            _safe_record_failure(
                application,
                args=args,
                workspace_id=workspace_id,
                profile_path=profile_path,
                exc=exc,
            )
        _write_json(
            {
                "ok": False,
                "error": {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                },
            },
            pretty=True,
            stream=sys.stderr,
        )
        return 1


def _run_daemon(
    application: LocalPlatformApplication,
    *,
    args: argparse.Namespace,
    workspace_id: str,
    profile_path: str | None,
) -> int:
    poll_interval_ms = args.poll_interval_ms
    heartbeat_interval_ms = args.heartbeat_interval_ms or poll_interval_ms
    codex_repo_check_policy, codex_repo_check_policy_source = (
        _codex_git_repo_check_policy(args, _local_runtime_profile(profile_path))
    )
    started_at = _utc_now()
    process_hint = _process_hint(profile_path=profile_path)
    application.record_agent_dispatch_daemon_liveness(
        workspace_id=workspace_id,
        dispatcher_id=args.dispatcher_id,
        state="starting",
        profile_path=profile_path,
        pid=os.getpid(),
        process_hint=process_hint,
        started_at=started_at,
        last_heartbeat_at=started_at,
    )
    application.record_agent_dispatch_daemon_liveness(
        workspace_id=workspace_id,
        dispatcher_id=args.dispatcher_id,
        state="running",
        profile_path=profile_path,
        pid=os.getpid(),
        process_hint=process_hint,
        started_at=started_at,
        last_heartbeat_at=started_at,
    )
    _write_line(
        "agent dispatch daemon started: "
        f"workspace={workspace_id} dispatcher={args.dispatcher_id} "
        f"dryRun={args.dry_run}"
    )
    last_heartbeat = time.monotonic()
    while True:
        result = application.run_agent_dispatch_worker_once(
            workspace_id=workspace_id,
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
        poll_at = _utc_now()
        lease_reconciliation = result.get("leaseReconciliation")
        application.record_agent_dispatch_daemon_liveness(
            workspace_id=workspace_id,
            dispatcher_id=args.dispatcher_id,
            state="running",
            profile_path=profile_path,
            pid=os.getpid(),
            process_hint=process_hint,
            last_heartbeat_at=poll_at,
            last_poll_at=poll_at,
            metadata={
                "lastWorkerRunId": result.get("workerRunId"),
                "candidateCount": result.get("candidateCount"),
                "selectedCount": result.get("selectedCount"),
                "activationSelectedCount": result.get("activationSelectedCount"),
                "processedCount": result.get("processedCount"),
                "skippedCount": result.get("skippedCount"),
                "runtimeStatusPolicy": result.get("runtimeStatusPolicy"),
                "leaseReconciliation": (
                    {
                        "schema": "agent_dispatch_lease_reconciliation_summary.v1",
                        "scannedActiveLeaseCount": lease_reconciliation.get(
                            "scannedActiveLeaseCount"
                        ),
                        "recoveryCandidateCount": lease_reconciliation.get(
                            "recoveryCandidateCount"
                        ),
                        "recoveredCount": lease_reconciliation.get("recoveredCount"),
                        "preservedCount": lease_reconciliation.get("preservedCount"),
                    }
                    if isinstance(lease_reconciliation, Mapping)
                    else None
                ),
            },
        )
        _write_line(
            "agent dispatch daemon poll: "
            f"workspace={result['workspaceId']} "
            f"dispatcher={result['dispatcherId']} "
            f"candidates={result['candidateCount']} "
            f"selected={result['selectedCount']} "
            f"processed={result['processedCount']} "
            f"skipped={result['skippedCount']}"
        )
        _write_json(result, pretty=args.pretty)
        if args.once:
            _record_exit(
                application,
                args=args,
                workspace_id=workspace_id,
                profile_path=profile_path,
                reason="once_completed",
            )
            _write_line("agent dispatch daemon graceful shutdown: once=true")
            return 0
        now = time.monotonic()
        elapsed_ms = (now - last_heartbeat) * 1000
        if elapsed_ms >= heartbeat_interval_ms:
            heartbeat_at = _utc_now()
            application.record_agent_dispatch_daemon_liveness(
                workspace_id=workspace_id,
                dispatcher_id=args.dispatcher_id,
                state="running",
                profile_path=profile_path,
                pid=os.getpid(),
                process_hint=process_hint,
                last_heartbeat_at=heartbeat_at,
            )
            _write_line(
                "agent dispatch daemon running: "
                f"workspace={workspace_id} "
                f"dispatcher={args.dispatcher_id}"
            )
            last_heartbeat = now
        time.sleep(poll_interval_ms / 1000)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agent_os.agent_dispatch_daemon",
        description="Run the local Agent OS dispatch dispatcher daemon.",
        allow_abbrev=False,
    )
    parser.add_argument("--profile")
    parser.add_argument("--database")
    parser.add_argument("--workspace-root")
    parser.add_argument("--plugins-directory")
    parser.add_argument("--no-init-schema", action="store_true")
    parser.add_argument("--workspace-id")
    parser.add_argument("--dispatch-id")
    parser.add_argument("--target-agent-id")
    parser.add_argument("--dispatcher-id", default="agent-dispatch-daemon")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--lease-ttl-seconds", type=int, default=300)
    parser.add_argument("--retry-delay-seconds", type=int, default=300)
    parser.add_argument("--handoff-directory")
    parser.add_argument("--platform-workspace-root")
    parser.add_argument("--config-path")
    parser.add_argument(
        "--claude-executable",
        "--claude-path",
        dest="claude_executable",
        default="claude",
    )
    parser.add_argument(
        "--no-claude-default-platform-workspace-add-dir",
        action="store_true",
    )
    parser.add_argument("--claude-add-dir", action="append", default=[])
    parser.add_argument("--claude-allowed-tool", action="append", default=[])
    parser.add_argument("--claude-permission-mode")
    parser.add_argument("--claude-settings-path")
    parser.add_argument(
        "--codex-executable",
        "--codex-path",
        dest="codex_executable",
        default="codex",
    )
    parser.add_argument(
        "--no-codex-default-platform-workspace-add-dir",
        action="store_true",
    )
    parser.add_argument("--codex-add-dir", action="append", default=[])
    parser.add_argument("--codex-sandbox-mode")
    parser.add_argument("--codex-approval-policy")
    parser.add_argument(
        "--codex-git-repo-check-policy",
        choices=("skip", "strict"),
    )
    parser.add_argument(
        "--hermes-executable",
        "--hermes-path",
        dest="hermes_executable",
        default="hermes",
    )
    parser.add_argument("--hermes-home")
    parser.add_argument("--hermes-source-tag", default="agent-os")
    parser.add_argument("--hermes-max-turns", type=int)
    parser.add_argument("--activation-timeout-seconds", type=int, default=120)
    parser.add_argument("--ignore-busy-target", action="store_true")
    runtime_status_group = parser.add_mutually_exclusive_group()
    runtime_status_group.add_argument(
        "--runtime-status-policy",
        choices=("auto", "enabled", "disabled"),
        default=argparse.SUPPRESS,
    )
    runtime_status_group.add_argument(
        "--read-live-runtime-status",
        dest="runtime_status_policy",
        action="store_const",
        const="enabled",
        default=argparse.SUPPRESS,
        help="Backward-compatible alias for --runtime-status-policy enabled.",
    )
    parser.set_defaults(runtime_status_policy="auto")
    parser.add_argument("--poll-interval-ms", type=int, default=5000)
    parser.add_argument("--heartbeat-interval-ms", type=int)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser


def _settings_from_args(
    args: argparse.Namespace,
    profile: Mapping[str, object],
    *,
    profile_path: str | None,
) -> LocalPlatformSettings:
    return LocalPlatformSettings(
        database=_runtime_setting(
            "database",
            args.database,
            profile,
            env_keys=("AGENT_OS_DATABASE", "AGENT_OS_DB_PATH"),
            profile_keys=("database", "databasePath", "dbPath"),
        ),
        workspace_root=_runtime_setting(
            "workspace_root",
            args.workspace_root,
            profile,
            env_keys=("AGENT_OS_WORKSPACE_ROOT",),
            profile_keys=("workspaceRoot", "workspace_root"),
        ),
        plugins_directory=_runtime_setting(
            "plugins_directory",
            args.plugins_directory,
            profile,
            env_keys=("AGENT_OS_PLUGINS_DIRECTORY", "AGENT_OS_PLUGINS_DIR"),
            profile_keys=("pluginsDirectory", "plugins_directory", "pluginsDir"),
        ),
        profile_path=profile_path,
        initialize_schema=not args.no_init_schema,
    )


def _validate_daemon_args(args: argparse.Namespace) -> None:
    normalize_provider_runtime_status_read_policy(args.runtime_status_policy)
    if args.poll_interval_ms <= 0:
        raise ValueError("pollIntervalMs must be greater than zero.")
    if args.heartbeat_interval_ms is not None and args.heartbeat_interval_ms <= 0:
        raise ValueError("heartbeatIntervalMs must be greater than zero.")


def _resolved_profile_path(profile_path: str | None) -> str | None:
    path = profile_path or os.environ.get("AGENT_OS_LOCAL_RUNTIME_PROFILE")
    if path is None or not path.strip():
        return None
    return str(Path(path).expanduser().resolve(strict=False))


def _process_hint(*, profile_path: str | None) -> Mapping[str, object]:
    return {
        "kind": "python-module",
        "module": "agent_os.agent_dispatch_daemon",
        "profilePath": profile_path,
        "argvStyle": "subprocess-argv",
    }


def _record_exit(
    application: LocalPlatformApplication,
    *,
    args: argparse.Namespace,
    workspace_id: str,
    profile_path: str | None,
    reason: str,
) -> None:
    now = _utc_now()
    application.record_agent_dispatch_daemon_liveness(
        workspace_id=workspace_id,
        dispatcher_id=args.dispatcher_id,
        state="exited",
        profile_path=profile_path,
        pid=os.getpid(),
        process_hint=_process_hint(profile_path=profile_path),
        last_heartbeat_at=now,
        last_exit_at=now,
        last_exit_reason=reason,
    )


def _safe_record_exit(
    application: LocalPlatformApplication,
    *,
    args: argparse.Namespace,
    workspace_id: str,
    profile_path: str | None,
    reason: str,
) -> None:
    try:
        _record_exit(
            application,
            args=args,
            workspace_id=workspace_id,
            profile_path=profile_path,
            reason=reason,
        )
    except (TypeError, ValueError, OSError, RuntimeError):
        return


def _record_failure(
    application: LocalPlatformApplication,
    *,
    args: argparse.Namespace,
    workspace_id: str,
    profile_path: str | None,
    exc: BaseException,
) -> None:
    now = _utc_now()
    summary = f"{exc.__class__.__name__}: {exc}"
    application.record_agent_dispatch_daemon_liveness(
        workspace_id=workspace_id,
        dispatcher_id=args.dispatcher_id,
        state="failed",
        profile_path=profile_path,
        pid=os.getpid(),
        process_hint=_process_hint(profile_path=profile_path),
        last_error_at=now,
        last_exit_at=now,
        last_exit_reason="error",
        error_summary=summary,
    )


def _safe_record_failure(
    application: LocalPlatformApplication,
    *,
    args: argparse.Namespace,
    workspace_id: str,
    profile_path: str | None,
    exc: BaseException,
) -> None:
    try:
        _record_failure(
            application,
            args=args,
            workspace_id=workspace_id,
            profile_path=profile_path,
            exc=exc,
        )
    except (TypeError, ValueError, OSError, RuntimeError):
        return


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _write_line(value: str) -> None:
    sys.stdout.write(value)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _write_json(
    value: Mapping[str, object] | object,
    *,
    pretty: bool,
    stream=sys.stdout,
) -> None:
    kwargs = {"ensure_ascii": False}
    if pretty:
        kwargs.update({"indent": 2, "sort_keys": True})
    stream.write(json.dumps(value, **kwargs))
    stream.write("\n")
    stream.flush()


if __name__ == "__main__":
    raise SystemExit(main())
