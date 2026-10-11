"""Test-only noisy handler; no production flag or startup hook."""
import sys
import json
import os
from pathlib import Path
from agent_os import communication_mcp

original = communication_mcp.create_server


def noisy(application):
    query = application.self_info
    def wrapped():
        print("synthetic handler noise 中文", flush=True)
        return query()
    application.self_info = wrapped
    return original(application)


if __name__ == "__main__":
    if os.environ.get("BEACON_TEST_MCP_PIDFILE"):
        Path(os.environ["BEACON_TEST_MCP_PIDFILE"]).write_text(json.dumps({"pid":os.getpid()}),encoding="utf-8")
    communication_mcp.create_server = noisy
    raise SystemExit(communication_mcp.main())
