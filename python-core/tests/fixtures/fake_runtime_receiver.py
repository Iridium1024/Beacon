"""ACK gate final receiver for isolated subprocess lifecycle tests."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback


def receive(prompt, trace_path, gate_path):
    marker = "Optional detail ticket: " if "Optional detail ticket: " in prompt else "Read the wake ticket JSON at: "
    ticket_path = next(line[len(marker):] for line in prompt.splitlines() if line.startswith(marker))
    ticket = json.loads(Path(ticket_path).read_text(encoding="utf-8"))
    actions = ticket.get("actions", ticket.get("recommendedAction"))
    env = {**os.environ, **actions["runtimeEnvironment"], "PYTHONIOENCODING": "utf-8"}
    def call(argv):
        proc = subprocess.run(argv, shell=False, env=env, capture_output=True,
                              encoding="utf-8", timeout=15)
        if proc.returncode:
            raise RuntimeError(proc.stderr)
        return json.loads(proc.stdout)
    def note(state):
        trace=Path(trace_path)
        temp=trace.with_suffix('.tmp')
        temp.write_text(json.dumps({"pid":os.getpid(),"state":state,
            "requestId":ticket["exchangeRequestId"]}),encoding='utf-8')
        temp.replace(trace)
    call(actions["ackArgv"])
    note('acked')
    end = time.monotonic() + 20
    while not Path(gate_path).exists():
        if time.monotonic() >= end:
            raise TimeoutError("synthetic receiver gate was never released")
        time.sleep(.02)
    reply = list(actions["respondArgvTemplate"])
    reply[-1] = "synthetic gated final"
    call(reply)
    note('final')


def main(trace_path, gate_path):
    if "--version" in sys.argv:
        print("codex-cli fake")
        return
    prompt = sys.stdin.read()
    try:
        receive(prompt, trace_path, gate_path)
    except Exception:
        Path(str(trace_path) + '.error').write_text(traceback.format_exc(), encoding='utf-8')
        raise
    argv = sys.argv[1:]
    native = next(value for value in argv if len(value) == 36 and value.count('-') == 4)
    print(json.dumps({"type": "thread.started", "thread_id": native}))
    print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "synthetic gated final"}}))
    for flag in ("--output-last-message", "-o"):
        if flag in argv:
            Path(argv[argv.index(flag) + 1]).write_text("synthetic gated final", encoding="utf-8")
