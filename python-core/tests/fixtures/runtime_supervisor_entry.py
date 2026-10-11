"""Real child supervisor with a child-only SDK fixture adapter."""
import argparse
import json
import os
import sys
from uuid import uuid4

from agent_os.application.services.communication_runtime import CommunicationSupervisor, RuntimeConfig
from agent_os.infrastructure.adapters.communication_process import SubprocessActivation
from agent_os.infrastructure.composition.communication_runtime import prepared_runtime
from agent_os.infrastructure.config import LocalPlatformSettings


class FixtureProcess(SubprocessActivation):
    def argv(self, payload):
        return [sys.executable, "-B", "-m", "fixtures.runtime_activation_entry", "--launch-json", json.dumps(payload)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", required=True)
    args = parser.parse_args()
    settings = LocalPlatformSettings(**json.loads(args.settings))
    with prepared_runtime(settings, "w") as (_, service):
        process = FixtureProcess(settings, {"database_path": settings.database,
            "workspace_root": settings.workspace_root, "plugins_directory": settings.plugins_directory,
            "config_path": settings.profile_path}, preflight=False)
        CommunicationSupervisor(service, service.coordination, process,
            config=RuntimeConfig(poll_interval=.05, heartbeat_interval=.1, consumer_lease=5,
                                 attempt_lease=3, provider_timeout=15, shutdown_timeout=2)).run(
            "w", pid=os.getpid(), start_id=str(uuid4()))
