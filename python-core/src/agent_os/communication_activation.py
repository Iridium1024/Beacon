"""Internal child entry; each activation constructs its own connection and scope."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json

from agent_os.application.services.communication_provider_adapter import CoreProviderAdapter
from agent_os.application.services.communication_worker import CoreCommunicationWorker
from agent_os.domain.entities.communication import Claim, CommunicationError, StaleAttempt
from agent_os.infrastructure.adapters.communication_process import PROVIDER_OPTIONS
from agent_os.infrastructure.composition.local_platform import build_local_platform_runtime
from agent_os.infrastructure.config import LocalPlatformSettings


def run_activation(payload, *, configure=None):
    settings = LocalPlatformSettings(**payload["settings"])
    if settings.initialize_schema or set(payload["options"]) - PROVIDER_OPTIONS:
        raise CommunicationError("activation must use prepared schema and allowlisted provider options")
    components = build_local_platform_runtime(settings)
    components.connection.execute("PRAGMA busy_timeout=100")
    claim = Claim(**payload["claim"])
    service = None
    try:
        service = components.communication(claim.workspace_id)
        if service is None:
            raise CommunicationError("independent activation requires a core workspace")
        runtime = service.coordination
        activation = runtime.staged(claim.workspace_id, claim.attempt_id)
        if not activation or activation["nonce"] != payload["nonce"] or activation["claim"] != payload["claim"] or activation["consumer"] != payload["consumer"]:
            raise StaleAttempt("launch does not match its registered activation")
        service.activation_context(claim)
        platform = components.operations()
        if configure is not None:
            configure(platform)
        # This entry is launched by the independent consumer. A caller payload
        # cannot reclassify it as an inline activation.
        adapter = CoreProviderAdapter(service, platform, payload["options"], actual_via="queued")
        worker = CoreCommunicationWorker(service, adapter,
            preflight=(lambda message, binding: adapter.preflight(message, binding,
                       read_live_runtime_status=payload["runtime_policy"])) if payload["preflight"] else None,
            evidence_sink=lambda attempt, evidence: runtime.stage_evidence(attempt.workspace_id,
                attempt.attempt_id, payload["nonce"], asdict(evidence), service._now()))
        return worker.execute_claim(claim)
    except BaseException:
        if service is not None:
            try:
                if service.attempt_status(claim)["phase"] == "claimed":
                    service.release(claim)
            except StaleAttempt:
                pass
        raise
    finally:
        components.close()


def main(*, configure=None):
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--launch-json", required=True)
    args = parser.parse_args()
    try:
        result = run_activation(json.loads(args.launch_json), configure=configure)
        # No body, capture text, nonce or full exception is printed to daemon logs.
        print(json.dumps({"messageId": result["messageId"], "outcome": result["outcome"]}))
        return 0
    except (CommunicationError, ValueError, OSError, RuntimeError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
