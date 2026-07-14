from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Mapping, Sequence

from agent_os.application.services.local_platform_application import (
    LocalPlatformApplication,
)
from agent_os.infrastructure.config import LocalPlatformSettings
from agent_os.stdio import configure_utf8_stdio


def main(argv: Sequence[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = _build_parser()
    args = parser.parse_args(argv)
    application = LocalPlatformApplication(
        LocalPlatformSettings(
            database=args.database,
            workspace_root=args.workspace_root,
            plugins_directory=args.plugins_directory,
            initialize_schema=not args.no_init_schema,
        )
    )
    profile = _agent_wake_profile_from_args(args)
    poll_interval_ms = int(profile.get("pollIntervalMs") or 5000)
    heartbeat_interval_ms = args.heartbeat_interval_ms or poll_interval_ms
    _write_line(
        "agent wake daemon started: "
        f"workspace={args.workspace_id} agent={args.agent_id} "
        f"mode={profile.get('wakeMode', 'notify_only')} dryRun={args.dry_run}"
    )
    last_heartbeat = time.monotonic()
    try:
        while True:
            result = application.run_agent_wake_once(
                workspace_id=args.workspace_id,
                agent_id=args.agent_id,
                profile=profile,
                config_path=args.config,
                dry_run=args.dry_run,
            )
            run = result["agentWakeRun"]
            _write_line(
                "agent wake daemon poll: "
                f"workspace={run['workspaceId']} agent={run['agentId']} "
                f"mode={run['wakeMode']} pending={run['pendingRequestCount']} "
                f"delivered={run['deliveredCount']} skipped={run['skippedCount']} "
                f"failed={run['failedCount']}"
            )
            _write_json(result, pretty=args.pretty)
            if args.once:
                _write_line("agent wake daemon graceful shutdown: once=true")
                return 0
            now = time.monotonic()
            elapsed_ms = (now - last_heartbeat) * 1000
            if elapsed_ms >= heartbeat_interval_ms:
                _write_line(
                    "agent wake daemon running: "
                    f"workspace={args.workspace_id} agent={args.agent_id} "
                    f"mode={profile.get('wakeMode', 'notify_only')} "
                    f"pending={run['pendingRequestCount']}"
                )
                last_heartbeat = now
            time.sleep(poll_interval_ms / 1000)
    except KeyboardInterrupt:
        _write_line("agent wake daemon graceful shutdown: interrupted")
        return 0
    except (TypeError, ValueError, OSError, RuntimeError) as exc:
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agent_os.agent_wake_daemon",
        description="Run the local Agent OS wake wrapper/daemon prototype.",
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--plugins-directory", required=True)
    parser.add_argument("--no-init-schema", action="store_true")
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
    parser.add_argument("--pretty", action="store_true")
    return parser


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
        profile["enabled"] = args.enabled == "true"
    if args.command_argv_json is not None:
        parsed = json.loads(args.command_argv_json)
        if not isinstance(parsed, list) or not all(
            isinstance(item, str) and item.strip() for item in parsed
        ):
            raise ValueError("command-argv-json must be a JSON array of strings.")
        profile["commandArgv"] = [item.strip() for item in parsed]
    return profile


def _json_object_file(path: str, logical_name: str) -> dict[str, object]:
    with open(path, "r", encoding="utf-8") as handle:
        parsed = json.load(handle)
    if not isinstance(parsed, dict):
        raise ValueError(f"{logical_name} must contain a JSON object.")
    return parsed


def _write_line(value: str) -> None:
    sys.stdout.write(value)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _write_json(
    value: object,
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
