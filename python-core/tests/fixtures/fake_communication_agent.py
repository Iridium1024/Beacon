"""Deterministic CLI-capable fake Agent; only used with isolated test profiles."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def execute_context(context, *, trace_path, policy="reply", peers=()):
    actions = context.get("actions", context.get("recommendedAction"))
    assert actions and context["instructionAuthority"] == "agent_suggestion"
    env = {**os.environ, **actions["runtimeEnvironment"], "PYTHONIOENCODING": "utf-8"}
    # Operator-created fake home: calls deliberately run outside the project.
    cwd = str(Path(trace_path).parent)
    trace = {"workspaceId": context["workspaceId"], "targetAgentId": context["targetAgentId"],
             "sourceAgentId": context["sourceAgentId"], "requestId": context["exchangeRequestId"],
             "context": context, "calls": []}

    def call(argv):
        result = subprocess.run(argv, cwd=cwd, env=env, shell=False, capture_output=True,
                                encoding="utf-8", timeout=20)
        trace["calls"].append({"argv": argv, "exitCode": result.returncode,
                               "stdout": result.stdout, "stderr": result.stderr})
        Path(trace_path).write_text(json.dumps(trace, ensure_ascii=False), encoding="utf-8")
        if result.returncode:
            raise RuntimeError("beacon_cli_unavailable_or_rejected: " + result.stderr)
        return json.loads(result.stdout)

    own = call(actions["selfArgv"])
    members = call(actions["membersArgv"])
    call(actions["inspectArgv"])
    call(actions["inboxArgv"])
    if "threadArgv" in actions:
        call(actions["threadArgv"])
    assert any(a["agentId"] == context["targetAgentId"] for a in own["agents"]["agents"])
    if policy != "silent":
        reply = list(actions["respondArgvTemplate"])
        reply[-1] = "Explicit fake reply from " + context["targetAgentId"]
        call(reply)
    for peer in peers:
        assert any(e["alias"] == peer for e in members["endpointAliases"]["endpoints"])
        send = list(actions["sendArgvTemplate"])
        send[send.index("--to") + 1] = peer
        send[-1] = "New fake directed request to " + peer
        # A bounded worker in the parent test is confirmed to consume this queue.
        send.extend(["--queued"])
        call(send)
    return trace


def main():
    sys.stdin.reconfigure(encoding="utf-8", errors="strict")
    sys.stdout.reconfigure(encoding="utf-8", errors="strict")
    provider, trace_path = sys.argv[1:3]
    argv = sys.argv[3:]
    if "--version" in argv or "--help" in argv:
        print(provider + " fake 1.0")
        return
    message = argv[argv.index("--query") + 1] if provider == "hermes" else sys.stdin.read()
    marker = "Optional detail ticket: " if provider == "codex" else "Read the wake ticket JSON at: "
    if provider == "hermes":
        ticket_path = message.split(marker, 1)[1].split(" Use the platform CLI", 1)[0]
    else:
        ticket_path = next(line[len(marker):] for line in message.splitlines() if line.startswith(marker))
    ticket = json.loads(Path(ticket_path).read_text(encoding="utf-8"))
    execute_context(ticket, trace_path=trace_path)
    session = argv[argv.index("--resume") + 1] if "--resume" in argv else argv[-2]
    if provider == "hermes":
        print("Resuming session " + session)
        print("Fake provider final")
    elif provider == "codex":
        print(json.dumps({"type": "thread.started", "thread_id": session}))
        print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Fake provider final"}}))
    else:
        print(json.dumps({"type": "result", "session_id": session, "result": "Fake provider final"}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        Path(sys.argv[2] + ".error").write_text(traceback.format_exc(), encoding="utf-8")
        raise
