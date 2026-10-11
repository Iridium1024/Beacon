"""Narrow bridge for existing provider runners under a core-owned attempt.

Provider runners retain their native continuity checks and diagnostic events.
Their old request reads are projected from one core message, and their final
capture is deferred to the core worker's single evidence write.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from agent_os.application.services.agent_exchange_request import AgentExchangeRequest
from agent_os.domain.entities.communication import Claim, Conflict, delivery_identity


@dataclass(slots=True)
class CoreProviderScope:
    service: object
    claim: Claim
    compact_enabled: bool = False
    actual_via: str | None = None
    final: str | None = None
    final_source: str | None = None
    requires_user_review: bool = False
    final_metadata: dict = field(default_factory=dict)

    def request(self, workspace_id: str, exchange_request_id: str) -> AgentExchangeRequest | None:
        if workspace_id != self.claim.workspace_id:
            return None
        message = self.service.repo.get("messages", workspace_id, self.claim.message_id)
        if message is None or (message.get("legacy_request_id") or message["id"]) != exchange_request_id:
            return None
        delivery = self.service.repo.get("deliveries", workspace_id,
            delivery_identity(message["id"], message["target"]))
        receipts = self.service.repo.receipts(workspace_id, message["id"])
        final = next((r for r in receipts if r["kind"] == "final" and not r["late"]), None)
        rejected = next((r for r in receipts if r["kind"] == "reject" and not r["late"]), None)
        answer = final["body"] if final is not None else self.final
        responded_by = final["author"] if final is not None else message["target"] if self.final else None
        responded_at = final["created_at"] if final is not None else datetime.now().astimezone().isoformat() if self.final else None
        closed_reason = delivery.get("closed_reason") if delivery else None
        terminal_reason = ("responded" if answer is not None else "blocked" if rejected
                           else closed_reason if delivery and delivery["closed_at"] else None)
        return AgentExchangeRequest.from_mapping({
            "workspaceId": workspace_id, "exchangeRequestId": exchange_request_id,
            "sourceAgentId": message["sender"], "targetAgentId": message["target"],
            "requestKind": message.get("legacy_request_kind") or "sync",
            "requestSummary": message["body"], "detailRefs": message["refs"],
            "parentRequestId": message.get("legacy_parent_request_id"),
            "rootRequestId": message.get("legacy_root_request_id"),
            "threadId": message["thread_id"], "turnIndex": message.get("legacy_turn_index") or 0,
            "linkedTaskId": message.get("legacy_linked_task_id"),
            "linkedConversationId": message.get("legacy_linked_conversation_id"),
            "linkedActivationId": message.get("legacy_linked_activation_id"),
            "linkedDelegatedWakeGrantId": message.get("legacy_linked_delegated_wake_grant_id"),
            "status": "terminal" if terminal_reason else "active",
            "terminalReason": terminal_reason, "responseSummary": answer,
            "respondedByAgentId": responded_by, "respondedAt": responded_at,
            "closedAt": delivery["closed_at"] if delivery and delivery["closed_at"] else None,
            "maxTurns": 0, "maxRequestLength": max(1200, len(message["body"])),
            "maxResponseLength": message.get("legacy_max_response_length") or 2000,
            "expiresAt": message.get("expires_at"),
            "requiresUserReview": bool(message.get("legacy_requires_user_review")),
            "createdAt": message["created_at"], "updatedAt": message["created_at"],
        })

    def record_final(self, *, workspace_id: str, exchange_request_id: str,
                     responding_agent_id: str, response_summary: str,
                     metadata: Mapping[str, object],
                     requires_user_review: bool | None) -> dict:
        request = self.request(workspace_id, exchange_request_id)
        if request is None or request.target_agent_id != responding_agent_id:
            raise Conflict("core provider capture has no matching owned request")
        if self.final is not None:
            raise Conflict("provider captured more than one final")
        if len(response_summary) > request.max_response_length:
            raise Conflict("provider final exceeds request maximum response length")
        self.final = response_summary
        self.final_source = str(metadata["responseSource"])
        self.final_metadata = dict(metadata)
        self.requires_user_review = bool(requires_user_review)
        # Legacy runner metadata requires an integer source sequence. Zero is
        # an explicit deferred marker; the core ledger sequence is written only
        # by complete(), after native evidence returns.
        return {"sourceEventSequence": 0, "coreFinalDeferred": True}


_CURRENT: ContextVar[CoreProviderScope | None] = ContextVar("core_provider_scope", default=None)


def current_core_provider_scope() -> CoreProviderScope | None:
    return _CURRENT.get()


@contextmanager
def core_provider_scope(scope: CoreProviderScope):
    token = _CURRENT.set(scope)
    try:
        yield scope
    finally:
        _CURRENT.reset(token)
