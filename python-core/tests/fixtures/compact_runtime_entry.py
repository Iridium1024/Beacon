"""Test-only sibling supervisor and child receiver for compact lifecycle proof."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from agent_os.application.services.communication_runtime import CommunicationSupervisor, RuntimeConfig
from agent_os.communication_activation import main as activation
from agent_os.infrastructure.adapters.communication_process import SubprocessActivation
from agent_os.infrastructure.composition.communication_runtime import prepared_runtime
from agent_os.infrastructure.config import LocalPlatformSettings
from test_claude_registered_session_activation import _sdk_runtime, _sdk_result


def configure(platform):
    platform.claude_agent_sdk_runtime_loader = lambda: _sdk_runtime(compatible=True)
    def runner(*args, **kwargs):
        prompt = kwargs["prompt"]
        Path(os.environ["BEACON_TEST_PROMPT"]).write_text(prompt, encoding="utf-8")
        runtime = next(line for line in prompt.splitlines() if line.startswith("argv="))
        argv_text, env_text = runtime[5:].split(" env=", 1)
        common, supplied = json.loads(argv_text), json.loads(env_text)
        scope = json.loads(next(line[6:] for line in prompt.splitlines() if line.startswith("scope=")))
        environment = {**os.environ, **supplied, "PYTHONIOENCODING": "utf-8"}
        def call(action, extra):
            result = subprocess.run([*common, action, *scope, *extra], env=environment,
                capture_output=True, text=True, encoding="utf-8", timeout=15)
            if result.returncode:
                raise RuntimeError(result.stderr)
            return json.loads(result.stdout)
        def note(state):
            trace = Path(os.environ["BEACON_TEST_TRACE"])
            temporary = trace.with_suffix(".tmp")
            temporary.write_text(json.dumps({"pid": os.getpid(), "state": state}), encoding="utf-8")
            temporary.replace(trace)
        call("agent-message-ack", ["--idempotency-key", "compact-life-ack"])
        note("acked")
        deadline = time.monotonic() + 20
        while not Path(os.environ["BEACON_TEST_GATE"]).exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("compact synthetic gate not released")
            time.sleep(.02)
        call("agent-message-reply", ["--message", "synthetic compact gated final🙂",
            "--idempotency-key", "compact-life-final"])
        note("final")
        return _sdk_result(final_response="SDK execution output only")
    platform.claude_agent_sdk_runner = runner


class FixtureProcess(SubprocessActivation):
    def argv(self, payload):
        return [sys.executable, "-B", "-m", "fixtures.compact_runtime_entry", "--launch-json", json.dumps(payload)]


def main():
    if "--launch-json" in sys.argv:
        return activation(configure=configure)
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", required=True)
    settings = LocalPlatformSettings(**json.loads(parser.parse_args().settings))
    with prepared_runtime(settings, "w") as (_, service):
        process = FixtureProcess(settings, {"database_path": settings.database,
            "workspace_root": settings.workspace_root, "plugins_directory": settings.plugins_directory,
            "config_path": settings.profile_path, "compact_messages": True}, preflight=False)
        CommunicationSupervisor(service, service.coordination, process,
            config=RuntimeConfig(poll_interval=.05, heartbeat_interval=.1, consumer_lease=5,
                attempt_lease=3, provider_timeout=15, shutdown_timeout=2)).run(
                    "w", pid=os.getpid(), start_id=str(uuid4()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
