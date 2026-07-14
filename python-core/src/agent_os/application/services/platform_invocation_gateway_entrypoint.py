from __future__ import annotations

from typing import Mapping, Protocol

from agent_os.application.services.platform_invocation_gateway_transport import (
    PlatformInvocationGatewayTransportAdapter,
)


class PlatformInvocationGatewayEnvelopeAdapter(Protocol):
    """Callable boundary expected by future Gateway bridge code."""

    def handle_gateway_envelope(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        ...


def handle_platform_invocation_gateway_envelope(
    envelope: Mapping[str, object],
    adapter: PlatformInvocationGatewayEnvelopeAdapter | None = None,
) -> Mapping[str, object]:
    transport = adapter or PlatformInvocationGatewayTransportAdapter()
    return transport.handle_gateway_envelope(envelope)
