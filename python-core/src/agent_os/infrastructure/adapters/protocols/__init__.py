"""Protocol adapter boundaries."""

from agent_os.infrastructure.adapters.protocols.heartbeat_terminal_protocol_envelope import (
    HEARTBEAT_TERMINAL_PROTOCOL_KIND,
    HEARTBEAT_TERMINAL_PROTOCOL_VERSION,
    build_heartbeat_terminal_protocol_envelope,
)

__all__ = [
    "HEARTBEAT_TERMINAL_PROTOCOL_KIND",
    "HEARTBEAT_TERMINAL_PROTOCOL_VERSION",
    "build_heartbeat_terminal_protocol_envelope",
]
