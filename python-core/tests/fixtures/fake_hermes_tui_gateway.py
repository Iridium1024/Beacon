from __future__ import annotations

import json
import os
import sys
import time


SCENARIO = os.environ.get("FAKE_HERMES_SCENARIO", "success")
PERSISTENT = os.environ.get("FAKE_HERMES_PERSISTENT", "persistent-session")
RUNTIME = os.environ.get("FAKE_HERMES_RUNTIME", "runtime-1234")
SOURCE = os.environ.get("FAKE_HERMES_SOURCE", "cli")
CWD = os.environ.get("FAKE_HERMES_CWD", os.getcwd())
LOG_PATH = os.environ.get("FAKE_HERMES_LOG")


def write(value: object) -> None:
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(raw + b"\n")
    sys.stdout.buffer.flush()


def response(request_id: int, result: object) -> None:
    write({"jsonrpc": "2.0", "id": request_id, "result": result})


def response_error(request_id: int, message: str) -> None:
    write(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": 5000, "message": message},
        }
    )


def event(kind: str, *, sid: str | None = None, payload: dict | None = None) -> None:
    params: dict[str, object] = {"type": kind}
    if sid is not None:
        params["session_id"] = sid
    if payload is not None:
        params["payload"] = payload
    write({"jsonrpc": "2.0", "method": "event", "params": params})


def record(frame: dict) -> None:
    if not LOG_PATH:
        return
    with open(LOG_PATH, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(frame, ensure_ascii=False) + "\n")


if SCENARIO == "malformed_ready":
    sys.stdout.buffer.write(b"not-json\n")
    sys.stdout.buffer.flush()
elif SCENARIO == "oversized_ready":
    sys.stdout.buffer.write(b"{" + b"x" * 4096 + b"}\n")
    sys.stdout.buffer.flush()
elif SCENARIO != "missing_ready":
    event("gateway.ready", payload={"skin": "fake"})
    if SCENARIO == "duplicate_ready":
        event("gateway.ready", payload={"skin": "fake-again"})

if SCENARIO == "stderr_invalid":
    sys.stderr.buffer.write(b"\xff\xfe")
    sys.stderr.buffer.flush()
if SCENARIO == "stderr_oversized":
    sys.stderr.buffer.write(b"d" * 4096)
    sys.stderr.buffer.flush()
if SCENARIO in {"eof_after_ready", "nonzero_after_ready"}:
    raise SystemExit(7 if SCENARIO == "nonzero_after_ready" else 0)


for raw in sys.stdin.buffer:
    frame = json.loads(raw.decode("utf-8"))
    record(frame)
    request_id = frame["id"]
    method = frame["method"]
    params = frame.get("params") or {}

    if method == "session.list":
        sessions: list[dict[str, object]] = [
            {"id": PERSISTENT, "source": SOURCE, "title": "fake"}
        ]
        if SCENARIO == "list_missing":
            sessions = []
        elif SCENARIO == "list_duplicate":
            sessions.append(dict(sessions[0]))
        elif SCENARIO == "list_source_mismatch":
            sessions[0]["source"] = "wrong-source"
        response(
            request_id + 100 if SCENARIO == "unknown_response" else request_id,
            {"sessions": sessions},
        )
        if SCENARIO == "duplicate_response":
            response(request_id, {"sessions": sessions})
        continue

    if method == "session.resume":
        target = "wrong-persistent" if SCENARIO == "resume_mismatch" else PERSISTENT
        if SCENARIO == "stale_before_resume":
            event("message.delta", sid=RUNTIME, payload={"text": "stale"})
        response(
            request_id,
            {
                "session_id": RUNTIME,
                "resumed": target,
                "session_key": target,
                "info": {
                    "cwd": "C:/wrong-cwd" if SCENARIO == "cwd_mismatch" else CWD,
                },
                "status": "idle",
            },
        )
        continue

    if method == "prompt.submit":
        if any(
            key
            in {
                "truncate_before_user_ordinal",
                "truncate_before_row_id",
                "confirm_truncate",
                "confirm_empty_truncate",
                "survivor_user_row_ids",
            }
            for key in params
        ):
            response(request_id, {"status": "forbidden-wire"})
            continue
        if SCENARIO == "terminal_out_of_order":
            event("message.complete", sid=RUNTIME, payload={"text": "too early", "status": "complete"})
            response(request_id, {"status": "streaming"})
            continue
        response(request_id, {"status": "streaming"})
        if SCENARIO in {
            "timeout",
            "no_final",
            "interrupt_rpc_error",
            "interrupt_eof",
        }:
            continue
        if SCENARIO == "cross_session":
            event("message.delta", sid="other-runtime", payload={"text": "wrong"})
            continue
        if SCENARIO == "error_event":
            event("error", sid=RUNTIME, payload={"message": "fake provider failure"})
            continue
        if SCENARIO == "malformed_after_submit":
            sys.stdout.buffer.write(b"not-json\n")
            sys.stdout.buffer.flush()
            continue
        if SCENARIO == "interaction_duplicate":
            event("clarify.request", sid=RUNTIME, payload={"request_id": "dup", "question": "q"})
            continue
        if SCENARIO == "interaction_unknown_expiry":
            event("sudo.expire", sid=RUNTIME, payload={"request_id": "unknown"})
            continue
        if SCENARIO == "interactions":
            event("approval.request", sid=RUNTIME, payload={"command": "echo safe"})
            continue
        event("message.delta", sid=RUNTIME, payload={"text": "delta is not final"})
        event("tool.start", sid=RUNTIME, payload={"tool_id": "t1", "name": "read"})
        event("tool.complete", sid=RUNTIME, payload={"tool_id": "t1", "name": "read"})
        event("status.update", sid=RUNTIME, payload={"kind": "status", "text": "done"})
        event("message.complete", sid=RUNTIME, payload={"text": "verified final", "status": "complete"})
        if SCENARIO == "duplicate_final":
            event("message.complete", sid=RUNTIME, payload={"text": "duplicate", "status": "complete"})
        continue

    if method == "approval.respond":
        response(request_id, {"resolved": 1})
        if SCENARIO == "interactions":
            event(
                "clarify.request",
                sid=RUNTIME,
                payload={"request_id": "clarify-1", "question": "continue?"},
            )
        continue

    if method == "clarify.respond":
        response(request_id, {"status": "ok"})
        if SCENARIO == "interaction_duplicate":
            event("clarify.request", sid=RUNTIME, payload={"request_id": "dup", "question": "again"})
        elif SCENARIO == "interactions":
            event("sudo.request", sid=RUNTIME, payload={"request_id": "sudo-1"})
        continue

    if method == "sudo.respond":
        response(request_id, {"status": "ok"})
        if SCENARIO == "interactions":
            event(
                "secret.request",
                sid=RUNTIME,
                payload={"request_id": "secret-1", "env_var": "TOKEN"},
            )
        continue

    if method == "secret.respond":
        response(request_id, {"status": "ok"})
        event("message.complete", sid=RUNTIME, payload={"text": "interaction final", "status": "complete"})
        continue

    if method == "session.interrupt":
        if SCENARIO == "interrupt_rpc_error":
            response_error(request_id, "interrupt rejected")
            continue
        if SCENARIO == "interrupt_eof":
            break
        response(request_id, {"status": "interrupted"})
        if SCENARIO == "timeout":
            break
        continue

    response(
        request_id,
        {"unexpected": method},
    )

if SCENARIO == "nonzero_after_protocol":
    raise SystemExit(9)
