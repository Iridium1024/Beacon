"""Connection, process and CLI-independent runtime assembly boundary."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import os
from uuid import uuid4

from agent_os.application.services.communication_runtime import CommunicationSupervisor, RuntimeConfig
from agent_os.application.services.communication_wait import CommunicationWait
from agent_os.domain.entities.communication import Caller, Claim, CommunicationError, ProviderEvidence
from agent_os.infrastructure.adapters.communication_process import SubprocessActivation
from agent_os.infrastructure.composition.local_platform import build_local_platform_runtime


@contextmanager
def prepared_runtime(settings, workspace_id):
    if settings.database != ":memory:" and not Path(settings.database).is_file():
        raise CommunicationError("prepared platform database does not exist")
    components = build_local_platform_runtime(replace(settings, initialize_schema=False))
    try:
        # Provider I/O never holds a transaction. A contended coordination
        # write must fail closed promptly, rather than block heartbeats for 5s.
        components.connection.execute("PRAGMA busy_timeout=100")
        service = components.communication(workspace_id)
        if service is None:
            raise CommunicationError("runtime/wait requires an explicitly migrated core workspace")
        yield components, service
    finally:
        components.close()


def initialize_runtime(settings, workspace_id):
    with prepared_runtime(settings, workspace_id) as (_, service):
        return service.coordination.initialize()


def runtime_status(settings, workspace_id):
    if settings.database != ":memory:" and not Path(settings.database).is_file():
        return {"state": "not_enabled", "sampledAt": datetime.now(timezone.utc).isoformat(), "leaseUntil": None}
    with prepared_runtime(settings, workspace_id) as (_, service):
        return service.coordination.consumer_status(workspace_id, service._now())


def stop_runtime(settings, workspace_id):
    with prepared_runtime(settings, workspace_id) as (_, service):
        return service.coordination.request_stop(workspace_id, service._now())


def reconcile_runtime(settings, workspace_id, attempt_id):
    with prepared_runtime(settings, workspace_id) as (_, service):
        staged = service.coordination.staged(workspace_id, attempt_id)
        if not staged or not staged["evidence"]:
            raise CommunicationError("no internally captured evidence; explicit native verification is required")
        claim = Claim(**staged["claim"])
        evidence = ProviderEvidence(**staged["evidence"])
        service.recover_expired_slots(workspace_id, owner="runtime-reconcile", limit=100)
        service.reconcile(claim, evidence)
        return {"attemptId": attempt_id, "messageId": claim.message_id, "state": "reconciled"}


def wait_message(settings, workspace_id, agent_id, message_id, **options):
    with prepared_runtime(settings, workspace_id) as (_, service):
        # Resolve old request IDs via the repository mapping port, not table access.
        if service.repo.get("messages", workspace_id, message_id) is None:
            matches = service.repo.mappings_for_legacy(workspace_id, "request", message_id)
            if len(matches) != 1:
                raise CommunicationError("no unique core message for this request")
            message_id = matches[0]["new_id"]
        return CommunicationWait(service, service.coordination).wait(Caller(workspace_id, agent_id), message_id, **options)


def observation_operation(settings, workspace_id, agent_id, observation_id=None, *, message_id=None, cancel=False):
    with prepared_runtime(settings, workspace_id) as (_, service):
        caller = Caller(workspace_id, agent_id)
        if message_id is not None and not cancel:
            return {"waits": service.own_waits(caller,message_id)}
        if cancel:
            service.cancel_observation(caller, observation_id, key=str(uuid4()))
        status = service.observation_status(caller, observation_id)
        obs = status["observation"]
        return {"observationId": observation_id, "messageId": obs["message_id"], "state": status["state"],
                "condition": obs["condition"], "deadline": obs["deadline"], "receiptId": status["receipt_id"]}


def run_supervisor(settings, workspace_id, *, config: RuntimeConfig, options, preflight=True,
                   runtime_policy="auto", target_agent_id=None):
    if target_agent_id is not None:
        raise CommunicationError("continuous consumer must cover the workspace; select a target with --once")
    with prepared_runtime(settings, workspace_id) as (_, service):
        if not service.coordination.enabled():
            raise CommunicationError("run communication-runtime-init before starting the core daemon")
        processes = SubprocessActivation(settings, options, preflight=preflight, runtime_policy=runtime_policy,
            provider_for=lambda claim: service.activation_context(Claim(**claim))[1]["binding"]["provider"])
        supervisor = CommunicationSupervisor(service, service.coordination, processes, config=config)
        return supervisor.run(workspace_id, pid=os.getpid(), start_id=str(uuid4()), target_agent_id=target_agent_id)
