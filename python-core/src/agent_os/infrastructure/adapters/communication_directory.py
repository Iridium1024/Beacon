"""Read-only bridge to existing registrations, endpoints and thread visibility.

No discovery, provider activation, private transcript access or registration writes.
This is deliberately opt-in, outside the production composition root.
"""
from __future__ import annotations

from agent_os.domain.entities.communication import AccessDenied, Caller, RecipientBinding
from agent_os.domain.ports.communication import CommunicationDirectoryReader
from agent_os.application.services.communication_policy import (
    _dispatch_contact_policy_decision, _dispatch_reply_reachability,
)


class PlatformCommunicationDirectory:
    def __init__(self, connection=None, *, platform=None, reader: CommunicationDirectoryReader | None = None):
        if reader is None:
            if platform is None:
                raise ValueError("inject a directory reader or use build_communication_directory")
            from agent_os.infrastructure.adapters.communication_reader import LegacyCommunicationReader
            reader = LegacyCommunicationReader(platform)
        self.reader = reader

    def require_member(self, caller: Caller) -> None:
        if not self.reader.member_active(caller):
            raise AccessDenied("workspace or agent is inactive")

    def resolve(self, workspace_id: str, alias: str) -> RecipientBinding:
        result = self.reader.endpoint(workspace_id, alias)
        endpoint, handle = result["agentEndpoint"], result["providerHandle"]
        if endpoint["state"] != "active" or endpoint["direction"] not in {"receive_only", "send_receive"}:
            raise AccessDenied("endpoint is not an active receiver")
        if not handle or handle["state"] != "active" or handle["agentId"] != endpoint["agentId"]:
            raise AccessDenied("endpoint handle is inactive or mismatched")
        self.require_member(Caller(workspace_id, endpoint["agentId"]))
        provider = endpoint["provider"]
        native_key = {"codex": "codexSessionId", "claude": "claudeSessionUuid",
                      "hermes": "hermesSessionId", "deepseek_harness": "deepseekHarnessSessionId"}[provider]
        metadata = handle.get("metadata", {})
        binding = metadata.get("runtimeBinding", {})
        return RecipientBinding(
            agent_id=endpoint["agentId"], alias=alias, provider=provider,
            native_session_id=handle[native_key], handle_id=handle["handleId"],
            generation=binding.get("generationId"),
            automatic_activation_allowed=not bool(metadata.get("providerSessionWorkspaceJoin")),
        )

    def authorize_send(self, caller: Caller, target_alias: str) -> None:
        self.require_member(caller)
        policy = self.reader.request_policy(caller.workspace_id)
        if policy["authorizationMode"] != "direct_allowed":
            raise AccessDenied("workspace forbids direct messaging; delegated grant integration belongs to C1-B")
        target = self.reader.endpoint(caller.workspace_id, target_alias)["agentEndpoint"]
        endpoints = self.reader.endpoints(caller.workspace_id)
        sources = [e for e in endpoints if e["agentId"] == caller.agent_id and e["direction"] in {"send_only", "send_receive"}]
        # Never guess between multiple aliases with different contact profiles.
        exact = [e for e in sources if e["alias"] == caller.agent_id]
        source = exact[0] if exact else sources[0] if len(sources) == 1 else None
        try:
            _dispatch_contact_policy_decision(source_endpoint=source, target_endpoint=target, reply_policy="message_only")
        except ValueError as exc:
            raise AccessDenied(str(exc)) from exc

    def authorize_send_context(self, caller: Caller, target_alias: str, *,
                               source_alias: str | None, reply_policy: str,
                               source_handle_id: str | None,
                               target_handle_id: str | None,
                               linked_delegated_wake_grant_id: str | None = None) -> None:
        """Validate the exact endpoint route resolved by the old CLI layer.

        Unlike authorize_send, this path never guesses among source aliases.
        The route is checked again at claim so later endpoint/policy changes
        cannot silently activate a stale binding.
        """
        self.require_member(caller)
        if reply_policy not in {"message_only", "source_handle_optional", "source_handle_required"}:
            raise AccessDenied("invalid reply policy")
        target_result = self.reader.endpoint(caller.workspace_id, target_alias)
        target = target_result["agentEndpoint"]
        target_binding = self.resolve(caller.workspace_id, target_alias)
        try:
            self.reader.authorize_route(caller, target_binding.agent_id, linked_delegated_wake_grant_id)
        except ValueError as exc:
            raise AccessDenied(str(exc)) from exc
        if target_handle_id is not None and target_binding.handle_id != target_handle_id:
            raise AccessDenied("target handle differs from the resolved endpoint")
        source = None
        if source_alias is not None:
            source_result = self.reader.endpoint(caller.workspace_id, source_alias)
            source = source_result["agentEndpoint"]
            handle = source_result.get("providerHandle")
            if (source["state"] != "active" or source["agentId"] != caller.agent_id
                    or source["direction"] not in {"send_only", "send_receive"}
                    or not handle or handle["state"] != "active"
                    or handle["agentId"] != caller.agent_id):
                raise AccessDenied("source endpoint is not an active sender owned by caller")
            if source_handle_id is not None and source["providerHandleId"] != source_handle_id:
                raise AccessDenied("source handle differs from the resolved endpoint")
            source_handle_id = source["providerHandleId"]
        elif source_handle_id is not None:
            raise AccessDenied("source handle requires an explicit source endpoint alias")
        try:
            _dispatch_contact_policy_decision(source_endpoint=source, target_endpoint=target,
                                              reply_policy=reply_policy)
        except ValueError as exc:
            raise AccessDenied(str(exc)) from exc
        reachability = _dispatch_reply_reachability(
            source_endpoint=source, target_endpoint=target,
            source_handle_id=source_handle_id, reply_policy=reply_policy)
        if not reachability["replyReachable"]:
            raise AccessDenied("reply policy requires a reachable source handle")

    def resolve_exact_legacy_target(self, workspace_id: str, agent_id: str, handle_id: str) -> RecipientBinding:
        """A historical queued item may resume only with one current exact endpoint."""
        endpoints = self.reader.endpoints(workspace_id)
        matches = [e for e in endpoints if e["agentId"] == agent_id
                   and e["providerHandleId"] == handle_id
                   and e["direction"] in {"receive_only", "send_receive"}]
        if len(matches) != 1:
            raise AccessDenied("historical target handle has no unique active endpoint")
        binding = self.resolve(workspace_id, matches[0]["alias"])
        if binding.agent_id != agent_id or binding.handle_id != handle_id:
            raise AccessDenied("historical target binding changed")
        return binding

    def existing_thread(self, caller: Caller, thread_id: str) -> dict | None:
        for thread in self.reader.threads(caller):
            if thread["exchangeThreadId"] == thread_id:
                if thread["threadStatus"] != "active":
                    raise AccessDenied("legacy thread is not active")
                return {"workspace_id": caller.workspace_id, "id": thread_id,
                        "visibility": thread["visibility"], "participants": thread["participantAgentIds"],
                        "legacy": True}
        return None
