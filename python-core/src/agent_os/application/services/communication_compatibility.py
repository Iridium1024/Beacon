"""Legacy exchange constraints evaluated inside the core send transaction.

This adapter reads old platform policy and registrations but writes only through
the communication ledger. It intentionally does not call old request writers.
"""
from __future__ import annotations

from agent_os.application.services.agent_exchange_request import (
    AgentExchangeFollowUpPolicy, AgentExchangeRequestKind, AgentExchangeSubRequestPolicy,
)
from agent_os.domain.entities.communication import Conflict, delivery_identity
from agent_os.domain.value_objects.identifiers import WorkspaceId


class LegacyExchangeSendCompatibility:
    def __init__(self, repository, platform):
        self.repo = repository
        self.platform = platform

    def _request(self, workspace_id: str, request_id: str) -> dict:
        matches = self.repo.mappings_for_legacy(workspace_id, "request", request_id)
        if len(matches) != 1:
            raise Conflict("parent request has no unique core mapping")
        message = self.repo.get("messages", workspace_id, matches[0]["new_id"])
        if message is None:
            raise Conflict("parent request mapping has no message")
        return message

    def _depth(self, workspace_id: str, parent: dict) -> int:
        depth = 1
        seen = {parent["id"]}
        current = parent
        while current.get("legacy_parent_request_id"):
            current = self._request(workspace_id, current["legacy_parent_request_id"])
            if current["id"] in seen:
                raise Conflict("request parent chain contains a cycle")
            seen.add(current["id"])
            depth += 1
        return depth

    def __call__(self, caller, binding, thread: dict, body: str, refs: tuple[str, ...],
                 reply_to: str | None, context: dict, now: str) -> dict:
        workspace_id = caller.workspace_id
        request_id, dispatch_id = context["request_id"], context.get("dispatch_id")
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("exchangeRequestId must be non-empty")
        if dispatch_id is not None and (not isinstance(dispatch_id, str) or not dispatch_id.strip()):
            raise ValueError("dispatchId must be non-empty")
        identities = [("request", request_id)]
        if dispatch_id is not None:
            identities.append(("dispatch", dispatch_id))
        for kind, legacy_id in identities:
            if self.repo.mappings_for_legacy(workspace_id, kind, legacy_id):
                raise Conflict(f"{kind} ID already has a core mapping")
        try:
            request_kind = AgentExchangeRequestKind(context["request_kind"]).value
        except (KeyError, ValueError) as exc:
            raise ValueError("invalid requestKind") from exc
        policy = self.platform._latest_agent_exchange_request_policy(WorkspaceId(workspace_id))
        source = self.platform._require_workspace_agent(workspace_id, caller.agent_id)
        target = self.platform._require_workspace_agent(workspace_id, binding.agent_id)
        config = self.platform._effective_agent_exchange_thread_config(
            policy=policy,
            source_agent_runtime_config=source.registration.runtime_config,
            target_agent_runtime_config=target.registration.runtime_config)
        if len(body) > policy.max_request_length:
            raise ValueError("requestSummary exceeds maxRequestLength")
        if int(config["maxTurns"]) == -1:
            raise ValueError("maxTurns=-1 disables request creation")
        if context.get("linked_task_id") is not None:
            self.platform._require_workspace_task(workspace_id, context["linked_task_id"])
        if context.get("linked_conversation_id") is not None:
            self.platform._require_conversation(workspace_id, context["linked_conversation_id"])
        if type(context.get("requires_user_review", False)) is not bool:
            raise ValueError("requiresUserReview must be boolean")
        parent_id = context.get("parent_request_id")
        parent = self._request(workspace_id, parent_id) if parent_id else None
        if parent is not None:
            if reply_to != parent["id"]:
                raise Conflict("parent request and reply_to differ")
            if policy.sub_request_policy is AgentExchangeSubRequestPolicy.DISABLED:
                raise ValueError("sub request creation is disabled")
            if (policy.sub_request_policy is AgentExchangeSubRequestPolicy.ALLOWED_FOR_CONFIGURED_AGENTS
                    and caller.agent_id not in policy.allowed_sub_request_agent_ids):
                raise ValueError("sourceAgentId is not allowed to create sub requests")
            if self._depth(workspace_id, parent) > policy.max_sub_request_depth:
                raise ValueError("sub request depth exceeds maxSubRequestDepth")
            if len(self.repo.child_messages(workspace_id, parent_id)) >= policy.max_child_requests:
                raise ValueError("sub request count exceeds maxChildRequests")
        elif reply_to is not None:
            raise Conflict("reply_to requires a parent request")
        if parent is not None and context.get("thread_id") is None and thread["id"] != parent["thread_id"]:
            raise Conflict("parent request thread differs")
        old_budget = thread.get("legacy_budget") or {}
        if self.repo.get("threads", workspace_id, thread["id"]) is None:
            thread["visibility"] = config["visibility"]
            thread["legacy_budget"] = {
                "maxTurns": config["maxTurns"], "followUpPolicy": config["followUpPolicy"]}
        else:
            if old_budget.get("followUpPolicy") == AgentExchangeFollowUpPolicy.DISABLED.value:
                raise ValueError("follow-up request creation is disabled")
            if policy.follow_up_policy is AgentExchangeFollowUpPolicy.DISABLED:
                raise ValueError("follow-up request creation is disabled")
        messages = self.repo.thread_messages(workspace_id, thread["id"])
        completed = active = 0
        for item in messages:
            if item.get("historical"):
                completed += item.get("legacy_terminal_reason") == "responded"
                active += item.get("legacy_request_status") == "active"
                continue
            receipts = self.repo.receipts(workspace_id, item["id"])
            terminal = next((r for r in receipts if r["kind"] in {"final", "reject"} and not r["late"]), None)
            completed += terminal is not None and terminal["kind"] == "final"
            delivery = self.repo.get("deliveries", workspace_id,
                                     delivery_identity(item["id"], item["target"]))
            active += terminal is None and delivery is not None and not delivery["closed_at"]
        effective = self.platform._effective_max_turns(
            [value for value in (old_budget.get("maxTurns"), config["maxTurns"])
             if isinstance(value, int) and value >= 0])
        if effective > 0 and completed + active >= effective:
            raise ValueError("agent exchange thread exceeds maxTurns")
        turn = context.get("turn_index")
        if turn is None:
            turn = ((parent.get("legacy_turn_index") or 0) + 1 if parent else completed + active)
        if type(turn) is not int or turn < 0:
            raise ValueError("turnIndex must be a non-negative integer")
        root = context.get("root_request_id") or (
            (parent.get("legacy_root_request_id") or parent_id) if parent else request_id)
        return {
            "legacy_request_id": request_id, "legacy_dispatch_id": dispatch_id,
            "legacy_request_kind": request_kind, "legacy_parent_request_id": parent_id,
            "legacy_root_request_id": root, "legacy_turn_index": turn,
            "legacy_max_response_length": policy.max_response_length,
            "legacy_requires_user_review": context.get("requires_user_review", False),
            "legacy_linked_task_id": context.get("linked_task_id"),
            "legacy_linked_conversation_id": context.get("linked_conversation_id"),
            "legacy_linked_activation_id": context.get("linked_activation_id"),
            "legacy_linked_delegated_wake_grant_id": context.get("linked_delegated_wake_grant_id"),
            "legacy_provider_backend": context.get("provider_backend"),
            "legacy_capture_policy": context.get("capture_policy"),
            "legacy_metadata": context.get("metadata") or {},
        }
