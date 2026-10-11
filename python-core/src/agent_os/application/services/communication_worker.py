"""One bounded communication worker invocation with an injected provider port.

The port is called only after claim and start intent have committed. A provider
exception is ambiguous delivery evidence, never proof of safe replay.
"""
from __future__ import annotations

from typing import Callable
from uuid import uuid4

from agent_os.domain.entities.communication import (
    Claim, CommunicationError, ProviderEvidence, StaleAttempt,
)


class CoreCommunicationWorker:
    def __init__(self, service, provider: Callable[[dict, dict, Claim, int], ProviderEvidence],
                 *, preflight: Callable[[dict, dict], dict] | None = None,
                 evidence_sink: Callable[[Claim, ProviderEvidence], None] | None = None):
        self.service = service
        self.provider = provider
        self.preflight = preflight
        self.evidence_sink = evidence_sink

    def run_once(self, workspace_id: str, *, dispatcher_id: str, limit: int = 1,
                 dispatch_id: str | None = None, target_agent_id: str | None = None,
                 lease_ttl_seconds: int | None = 300,
                 provider_timeout_seconds: int = 120,
                 dry_run: bool = False) -> dict:
        if type(provider_timeout_seconds) is not int or not 1 <= provider_timeout_seconds <= 3570:
            raise CommunicationError("provider timeout must be 1..3570 seconds")
        if lease_ttl_seconds is not None and (type(lease_ttl_seconds) is not int
                                              or not 1 <= lease_ttl_seconds <= 3600):
            raise CommunicationError("lease TTL must be 1..3600 seconds")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise CommunicationError("worker limit must be 1..100")
        message_id = None
        if dispatch_id is not None:
            matches = self.service.repo.mappings_for_legacy(workspace_id, "dispatch", dispatch_id)
            if len(matches) != 1:
                raise CommunicationError("dispatch has no unique core message mapping")
            message_id = matches[0]["new_id"]
        candidates = (self.service.due_message(workspace_id, message_id)
                      if message_id is not None else
                      self.service.due(workspace_id, limit=100,
                                       target_agent_id=target_agent_id))
        if target_agent_id is not None:
            candidates = [d for d in candidates if d["target"] == target_agent_id]
        selected = candidates[:limit]
        preview = [{"messageId": d["message_id"], "targetAgentId": d["target"],
                    "provider": (d.get("binding") or {}).get("provider"),
                    "schedule": d["schedule"]} for d in selected]
        result = {"schema": "agent_dispatch_worker_run.core.v1", "engine": "core",
                  "workspaceId": workspace_id, "workerRunId": f"core-worker-{uuid4()}",
                  "dispatcherId": dispatcher_id, "dryRun": dry_run,
                  "workerStarted": not dry_run, "requestedLimit": limit,
                  "candidateCount": len(candidates), "selectedCount": len(selected),
                  "candidates": preview, "agentDispatches": []}
        if dry_run:
            result.update(processedCount=0, skippedCount=0,
                          expiredSlotCandidates=len(self.service.expired_slots(workspace_id, limit=100)))
            return result
        result["leaseReconciliation"] = self.service.recover_expired_slots(
            workspace_id, owner=dispatcher_id, limit=100)
        if result["leaseReconciliation"]["retryable_before_start"]:
            candidates = (self.service.due_message(workspace_id, message_id)
                          if message_id is not None else
                          self.service.due(workspace_id, limit=100,
                                           target_agent_id=target_agent_id))
            if target_agent_id is not None:
                candidates = [d for d in candidates if d["target"] == target_agent_id]
            selected = candidates[:limit]
            result["candidateCount"] = len(candidates)
            result["selectedCount"] = len(selected)
            result["candidates"] = [{"messageId": d["message_id"], "targetAgentId": d["target"],
                                     "provider": (d.get("binding") or {}).get("provider"),
                                     "schedule": d["schedule"]} for d in selected]
        lease_seconds = max(lease_ttl_seconds or 300, provider_timeout_seconds + 30)
        if lease_seconds > 3600:
            raise CommunicationError("effective lease exceeds one hour")
        for delivery in selected:
            identity = delivery["message_id"]
            if self.preflight is not None:
                message = self.service.repo.get("messages", workspace_id, identity)
                try:
                    readiness = self.preflight(message, delivery["binding"])
                except Exception as exc:
                    result["agentDispatches"].append({"messageId": identity,
                        "processed": False, "skipped": True, "outcome": "preflight_unknown",
                        "reason": f"{type(exc).__name__}: {exc}"})
                    continue
                if readiness.get("runtimeState") in {"busy", "blocked"}:
                    result["agentDispatches"].append({"messageId": identity,
                        "processed": False, "skipped": True, "outcome": "target_busy",
                        "providerRuntimeStatus": readiness})
                    continue
            claimed = self.service.claim(workspace_id, identity, owner=dispatcher_id,
                lease_seconds=lease_seconds, provider_timeout_seconds=provider_timeout_seconds)
            if claimed["outcome"] != "claimed":
                result["agentDispatches"].append({"messageId": identity,
                    "processed": False, "skipped": True, "outcome": claimed["outcome"]})
                continue
            claim = Claim(**claimed["claim"])
            result["agentDispatches"].append(self.execute_claim(claim, preflight_checked=True))
        result["processedCount"] = sum(item["processed"] for item in result["agentDispatches"])
        result["skippedCount"] = sum(item["skipped"] for item in result["agentDispatches"])
        return result

    def execute_claim(self, claim: Claim, *, preflight_checked: bool = False) -> dict:
        """Execute one durable claim; shared by inline and independently assembled child."""
        identity = claim.message_id
        workspace_id = claim.workspace_id
        message, attempt, delivery = self.service.activation_context(claim)
        provider_timeout_seconds = attempt["provider_timeout_seconds"]
        if self.preflight is not None and not preflight_checked:
            readiness = self.preflight(message, attempt["binding"])
            if readiness.get("runtimeState") in {"busy", "blocked"}:
                self.service.release(claim)
                return {"messageId": identity, "processed": False, "skipped": True,
                        "outcome": "target_busy"}
        try:
            self.service.mark_started(claim)
        except (CommunicationError, ValueError) as exc:
            try:
                self.service.release(claim)
            except StaleAttempt:
                pass
            return {"messageId": identity, "processed": False, "skipped": True,
                    "outcome": "activation_cancelled", "reason": str(exc)}
        message = self.service.repo.get("messages", workspace_id, identity)
        attempt = self.service.repo.get("attempts", workspace_id, claim.attempt_id)
        binding = attempt["binding"]
        try:
            evidence = self.provider(message, binding, claim, provider_timeout_seconds)
            if not isinstance(evidence, ProviderEvidence):
                raise TypeError("provider port returned no evidence")
        except Exception as exc:
            evidence = ProviderEvidence(provider=binding["provider"],
                native_session_id=binding["native_session_id"],
                generation=binding["generation"], outcome="unknown",
                evidence_ref=f"worker-exception:{uuid4()}")
            provider_error = f"{type(exc).__name__}: {exc}"
        else:
            provider_error = None
        if self.evidence_sink is not None:
            self.evidence_sink(claim, evidence)
        try:
            completed = self.service.complete(claim, evidence)
            item = {"messageId": identity, "processed": True, "skipped": False,
                    "outcome": evidence.outcome,
                    "providerCommandStarted": evidence.provider_command_started,
                    "delivery": completed["delivery"]["delivery"],
                    "execution": completed["delivery"]["execution"]}
        except StaleAttempt:
            item = {"messageId": identity, "processed": False, "skipped": True,
                    "outcome": "ownership_lost_reconcile_required"}
        except CommunicationError as exc:
            item = {"messageId": identity, "processed": False, "skipped": True,
                    "outcome": "evidence_rejected_reconcile_required", "reason": str(exc)}
        if provider_error is not None:
            item["providerError"] = provider_error
        return item
