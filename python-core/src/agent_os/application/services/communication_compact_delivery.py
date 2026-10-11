"""Render a compact, executable handoff from an owned core provider scope.

The body is never parsed as an envelope. CLI argv and its one explicit source
path are provided in each handoff; receivers need no earlier context or ticket
read to acknowledge, respond, or check status.
"""
from __future__ import annotations

import json

from agent_os.application.services.agent_communication_context import build_beacon_cli_invocation
from agent_os.application.services.communication_envelope import BOUNDARY, CommunicationEnvelope
from agent_os.domain.entities.communication import Caller, CommunicationError


def render_provider_message(*, scope, request, database_path: str, workspace_root: str,
                            plugins_directory: str, profile_path: str | None) -> str | None:
    """Return None for the unchanged legacy fallback, never guess missing facts."""
    if scope is None or not scope.compact_enabled:
        return None
    if request.workspace_id != scope.claim.workspace_id:
        raise CommunicationError("compact provider scope differs from request workspace")
    summary = CommunicationEnvelope(scope.service).summary(
        Caller(request.workspace_id, request.target_agent_id), scope.claim.message_id,
        actual_via=scope.actual_via, include_body=True)
    if not summary.get("enabled"):
        return None
    if summary["toAgent"] != request.target_agent_id:
        raise CommunicationError("compact provider recipient differs from request target")
    common, environment = build_beacon_cli_invocation(
        database_path=database_path, workspace_root=workspace_root,
        plugins_directory=plugins_directory, profile_path=profile_path)
    compact = lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    scope_args = ["--workspace-id", request.workspace_id,
                  "--agent-id", request.target_agent_id, "--message-ref", summary["messageRef"]]
    lines = [BOUNDARY, summary["header"]]
    if summary.get("fromAlias") and summary.get("toAlias"):
        lines.append("From " + summary["fromAlias"] + " to " + summary["toAlias"] + ".")
    lines.extend(["Body:", summary["body"], "End body."])
    if request.detail_refs:
        lines.append("Refs: " + compact(list(request.detail_refs)))
    if summary["capture"] == "provider_final_capture":
        lines.append("Your final is captured. ACK ends ACK waiting only; never final waiting.")
    else:
        lines.append("Reply optional and explicit; your final is not captured. ACK never ends final waiting.")
    lines.extend([
        "CLI: execute argv+ [action]+scope+extra; no ticket read needed.",
        "argv=" + compact(common) + " env=" + compact(environment),
        "scope=" + compact(scope_args),
        'Format help: argv+["agent-compact-explain","--version","B1"] (no scope).',
        "ACK: action=agent-message-ack extra=" + compact(["--idempotency-key", "ack:" + summary["messageRef"]]),
        "reply: action=agent-message-reply extra=" + compact(
            ["--message", "<chosen reply>", "--idempotency-key", "<stable reply key>"]),
        "status: action=agent-message-status extra=[]; a new directed send is needed to wake the source.",
    ])
    return "\n".join(lines) + "\n"
