"""Activation process adapter. No message bodies or environment snapshots in argv."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys

from agent_os.domain.entities.communication import CommunicationError

# Reuse the existing provider argument vocabulary, never arbitrary business executable fields.
PROVIDER_OPTIONS = frozenset({
    "database_path", "workspace_root", "plugins_directory", "config_path", "handoff_directory",
    "platform_workspace_root", "claude_executable", "claude_default_platform_workspace_add_dir",
    "claude_add_dirs", "claude_allowed_tools", "claude_permission_mode", "claude_settings_path",
    "claude_activation_backend", "claude_reply_writeback_mode", "codex_executable",
    "codex_default_platform_workspace_add_dir", "codex_add_dirs", "codex_sandbox_mode",
    "codex_approval_policy", "codex_git_repo_check_policy", "codex_git_repo_check_policy_source",
    "codex_activation_backend", "codex_app_server_approval_decision", "codex_reply_writeback_mode",
    "codex_busy_delivery_policy", "codex_busy_delivery_policy_explicit", "immediate_busy_policy",
    "hermes_executable", "hermes_home", "hermes_activation_backend", "hermes_reply_writeback_mode",
    "hermes_gateway_python", "hermes_source_tag", "hermes_max_turns",
    "compact_messages",
})


def activation_payload(settings, options, claim, consumer, nonce, *, preflight=True, runtime_policy="auto"):
    unknown = set(options) - PROVIDER_OPTIONS
    if unknown:
        raise CommunicationError("unsupported activation options: " + ",".join(sorted(unknown)))
    if type(options.get("compact_messages", False)) is not bool:
        raise CommunicationError("compact_messages must be a trusted boolean option")
    return {"settings": {"database": settings.database, "workspace_root": settings.workspace_root,
                         "plugins_directory": settings.plugins_directory, "profile_path": settings.profile_path,
                         "initialize_schema": False}, "options": dict(options), "claim": claim,
            "consumer": consumer, "nonce": nonce, "preflight": preflight, "runtime_policy": runtime_policy}


class SubprocessActivation:
    def __init__(self, settings, options, *, preflight=True, runtime_policy="auto", provider_for=None):
        self.settings, self.options = settings, dict(options)
        self.preflight, self.runtime_policy = preflight, runtime_policy
        self.provider_for = provider_for

    def argv(self, payload):
        return [sys.executable, "-B", "-m", "agent_os.communication_activation", "--launch-json",
                json.dumps(payload, ensure_ascii=False)]

    def start(self, claim, consumer, nonce):
        payload = activation_payload(self.settings, self.options, claim, consumer, nonce,
                                     preflight=self.preflight, runtime_policy=self.runtime_policy)
        env = os.environ.copy()
        source = str(Path(__file__).resolve().parents[3])
        env["PYTHONPATH"] = source + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["PYTHONIOENCODING"] = "utf-8"
        tree_owned = bool(self.provider_for is not None and self.provider_for(claim) != "deepseek_harness")
        process = subprocess.Popen(self.argv(payload), shell=False, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            start_new_session=os.name != "nt")
        # The owned Popen handle is the authority for exact process operations.
        process.beacon_nonce = nonce
        process.beacon_tree_owned = tree_owned
        return process

    def poll(self, child):
        return child.poll()

    def stop(self, child):
        if child.poll() is not None:
            return
        # Stop only this owned child handle. Provider process stop is still
        # unknown unless its existing adapter supplies correlated native evidence.
        if os.name == "nt":
            if child.beacon_tree_owned:
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], shell=False,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
            elif child.poll() is None:
                child.terminate()
        else:
            os.kill(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=2)

    def close(self, child):
        if child.poll() is None:
            self.stop(child)
        child.wait(timeout=2)
