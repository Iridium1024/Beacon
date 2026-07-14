from __future__ import annotations

from dataclasses import dataclass, field
import sqlite3
from typing import Mapping

from agent_os.application.services.platform_invocation_gateway_handler import (
    PLATFORM_SINGLE_TURN_INVOCATION_KIND,
)
from agent_os.application.services.platform_invocation_gateway_transport import (
    PlatformInvocationGatewayTransportAdapter,
)
from agent_os.application.services.platform_invocation_runtime_handler import (
    handle_sqlite_platform_invocation_payload,
)
from agent_os.domain.ports.protocol import ProtocolEnvelope


PLATFORM_SINGLE_TURN_INVOCATION_COMPLETED_KIND = (
    "platform.invocation.single_turn.completed"
)


@dataclass(slots=True)
class SqlitePlatformInvocationGatewayRuntimeBridge:
    """Opt-in Gateway adapter that dispatches a platform invocation to SQLite runtime."""

    connection: sqlite3.Connection
    record_agent_invocations: bool = True
    transport: PlatformInvocationGatewayTransportAdapter = field(
        default_factory=PlatformInvocationGatewayTransportAdapter
    )

    def handle_gateway_envelope(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        request = self.transport.parse_gateway_envelope(envelope)
        if request.kind != PLATFORM_SINGLE_TURN_INVOCATION_KIND:
            raise ValueError("unsupported platform invocation envelope kind.")

        payload = handle_sqlite_platform_invocation_payload(
            self.connection,
            request.payload,
            record_agent_invocations=self.record_agent_invocations,
            file_operation_use_case_factory=(
                _gateway_file_operation_use_case_factory(self.connection)
            ),
        )
        return self.transport.serialize_gateway_envelope(
            ProtocolEnvelope(
                protocol_version=request.protocol_version,
                request_id=request.request_id,
                kind=PLATFORM_SINGLE_TURN_INVOCATION_COMPLETED_KIND,
                payload=payload,
                metadata={
                    **dict(request.metadata),
                    "handler": "platform_invocation_gateway_runtime_bridge",
                    "platform_runtime_wired": "true",
                },
            )
        )


def _gateway_file_operation_use_case_factory(connection: sqlite3.Connection):
    def factory(workspace_id):
        from agent_os.infrastructure.composition.local_platform import (
            build_local_workspace_file_operation_use_case,
        )

        return build_local_workspace_file_operation_use_case(
            connection,
            workspace_id=workspace_id,
        )

    return factory
