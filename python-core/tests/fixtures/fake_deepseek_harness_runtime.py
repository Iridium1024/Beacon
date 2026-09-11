from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Mapping


def _write(value: Mapping[str, object]) -> None:
    sys.stdout.write(json.dumps(dict(value), separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _response(request_id: object, result: Mapping[str, object]) -> None:
    _write({"jsonrpc": "2.0", "id": request_id, "result": dict(result)})


def _notification(method: str, params: Mapping[str, object]) -> None:
    _write({"jsonrpc": "2.0", "method": method, "params": dict(params)})


def _event(session_id: str, event: Mapping[str, object]) -> None:
    _notification("session.event", {"sessionId": session_id, "event": dict(event)})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="normal")
    parser.add_argument("--server-version", default="0.1.1-rc.2")
    parser.add_argument("--communication-trace")
    parser.add_argument("--communication-policy", default="reply")
    parser.add_argument("--peer", action="append", default=[])
    return parser


def main() -> int:
    # Model the SDK's UTF-8 JSONL wire, independent of the Windows console locale.
    sys.stdin.reconfigure(encoding="utf-8", errors="strict")
    sys.stdout.reconfigure(encoding="utf-8", errors="strict")
    args = _parser().parse_args()
    initialized = False
    turn = 0
    while True:
        line = sys.stdin.readline()
        if not line:
            return 9 if initialized else 0
        request = json.loads(line)
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        if method == "initialize":
            if args.scenario == "notification-before-initialize":
                _notification(
                    "session.status",
                    {"sessionId": "early", "status": "idle"},
                )
            _response(
                request_id,
                {
                    "serverInfo": {
                        "name": "deepseek-harness-sdk-runtime",
                        "version": args.server_version,
                    }
                },
            )
            if args.scenario == "notification-after-initialize-response":
                _notification(
                    "session.status",
                    {"sessionId": "initialized-other", "status": "idle"},
                )
            initialized = True
            continue
        if method == "session/prompt":
            turn += 1
            session_id = str(params.get("sessionId"))
            message_id = f"user-{turn}"
            if args.scenario == "prompt-eof-before-response":
                return 23
            _response(request_id, {"messageId": message_id})
            if args.scenario == "receipt-then-eof":
                _event(
                    session_id,
                    {
                        "type": "agent/inbox/spliced",
                        "data": {"inserted": [{"id": message_id, "role": "user"}]},
                    },
                )
                return 24
            if args.scenario == "nonzero-exit":
                return 31
            if args.scenario == "duplicate-response":
                _response(request_id, {"messageId": message_id})
                time.sleep(0.1)
                continue
            if args.scenario == "unknown-response":
                _response(999999, {})
                time.sleep(0.1)
                continue
            if args.scenario == "malformed-json":
                sys.stdout.write("{not-json}\n")
                sys.stdout.flush()
                time.sleep(0.1)
                continue
            if args.scenario == "oversized-json":
                sys.stdout.write(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "method": "session.status",
                            "params": {
                                "sessionId": session_id,
                                "status": "running",
                                "padding": "x" * 8192,
                            },
                        }
                    )
                    + "\n"
                )
                sys.stdout.flush()
                time.sleep(0.1)
                continue
            if args.scenario == "stderr-noise":
                sys.stderr.write("bounded diagnostic noise\n" * 20)
                sys.stderr.flush()
            _event(
                session_id,
                {
                    "type": "agent/inbox/spliced",
                    "data": {"inserted": [{"id": message_id, "role": "user"}]},
                },
            )
            _notification("session.status", {"sessionId": session_id, "status": "running"})
            if args.communication_trace:
                from fake_communication_agent import execute_context
                context = json.loads(params["contentBlocks"][0]["text"].splitlines()[-1])
                try:
                    execute_context(context, trace_path=args.communication_trace,
                                    policy=args.communication_policy, peers=args.peer if turn == 1 else ())
                except Exception:
                    from pathlib import Path
                    import traceback
                    Path(args.communication_trace + ".error").write_text(traceback.format_exc(), encoding="utf-8")
                    raise
            if args.scenario == "slow-operation":
                time.sleep(0.8)
            if args.scenario == "no-final":
                _event(
                    session_id,
                    {"type": "turn/end", "data": {"reason": {"kind": "completed"}}},
                )
                _notification("session.status", {"sessionId": session_id, "status": "idle"})
                continue
            if args.scenario == "descendant-only-final":
                child = f"child-{turn}"
                _notification(
                    "subagent.started",
                    {"parentSessionId": session_id, "childSessionId": child},
                )
                _event(
                    child,
                    {
                        "type": "assistant/message",
                        "data": {
                            "message": {
                                "id": f"child-assistant-{turn}",
                                "content": [{"type": "text", "text": "child final"}],
                            }
                        },
                    },
                )
                _notification("session.status", {"sessionId": session_id, "status": "idle"})
                continue
            if args.scenario == "causal-noise":
                child = f"child-{turn}"
                _notification(
                    "subagent.started",
                    {"parentSessionId": session_id, "childSessionId": child},
                )
                _event(
                    child,
                    {
                        "type": "assistant/message",
                        "data": {
                            "message": {
                                "id": f"child-assistant-{turn}",
                                "content": [{"type": "text", "text": "child final"}],
                            }
                        },
                    },
                )
                _event(
                    "other-session",
                    {
                        "type": "assistant/message",
                        "data": {
                            "message": {
                                "id": "other-assistant",
                                "content": [{"type": "text", "text": "other final"}],
                            }
                        },
                    },
                )
                _event(
                    session_id,
                    {"type": "tool/result", "data": {"text": "tool output"}},
                )
            if args.scenario == "unknown-queued-work":
                _event(
                    session_id,
                    {
                        "type": "agent/inbox/spliced",
                        "data": {"inserted": [{"id": "other-user", "role": "user"}]},
                    },
                )
                continue
            if args.scenario == "idle-before-final":
                _notification("session.status", {"sessionId": session_id, "status": "idle"})
                continue
            _event(
                session_id,
                {
                    "type": "assistant/message",
                    "data": {
                        "message": {
                            "id": f"assistant-{turn}",
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        "turn-1"
                                        if turn == 1
                                        else f"turn-{turn}; observed=turn-{turn - 1}"
                                    ),
                                }
                            ],
                        }
                    },
                },
            )
            if args.scenario == "final-after-turn-end":
                _event(
                    session_id,
                    {"type": "turn/end", "data": {"reason": {"kind": "completed"}}},
                )
                _event(
                    session_id,
                    {
                        "type": "assistant/message",
                        "data": {
                            "message": {
                                "id": f"late-assistant-{turn}",
                                "content": [{"type": "text", "text": "late"}],
                            }
                        },
                    },
                )
                continue
            if args.scenario == "duplicate-final":
                _event(
                    session_id,
                    {
                        "type": "assistant/message",
                        "data": {
                            "message": {
                                "id": f"assistant-{turn}",
                                "content": [{"type": "text", "text": "duplicate"}],
                            }
                        },
                    },
                )
                continue
            _event(
                session_id,
                {
                    "type": "turn/end",
                    "data": {"reason": {"kind": "completed"}},
                },
            )
            _notification("session.status", {"sessionId": session_id, "status": "idle"})
            continue
        if method == "shutdown":
            _response(request_id, {})
            return 0
        _write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"unknown method: {method}"},
            }
        )


if __name__ == "__main__":
    raise SystemExit(main())
