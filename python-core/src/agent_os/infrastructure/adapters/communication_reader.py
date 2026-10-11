"""Narrow read/authorization adapter for the existing platform policy owner.

The private legacy authorization call is confined here until that policy is
extracted; neither the directory nor the scheduler constructs a platform service.
"""
import json

from agent_os.domain.value_objects.identifiers import AgentId, WorkspaceId


class LegacyCommunicationReader:
    def __init__(self, platform):
        self.platform = platform

    def member_active(self, caller):
        workspace = self.platform.workspace_reader.get_workspace_state(WorkspaceId(caller.workspace_id))
        member = self.platform.agent_registration_reader.get_agent_registration_state(AgentId(caller.agent_id))
        return bool(workspace and workspace.workspace.status.value == "active" and member
                    and member.registration.workspace_id.value == caller.workspace_id
                    and member.registration.status.value == "active")

    def endpoint(self, workspace_id, alias):
        return self.platform.get_agent_endpoint(workspace_id, alias=alias)

    def endpoints(self, workspace_id):
        return self.platform.list_agent_endpoints(workspace_id, include_inactive=False)["agentEndpoints"]

    def request_policy(self, workspace_id):
        return self.platform.get_agent_exchange_request_policy(workspace_id)["agentExchangeRequestPolicy"]

    def authorize_route(self, caller, target, grant):
        self.platform._validate_agent_exchange_request_authorization(
            policy=self.platform._latest_agent_exchange_request_policy(WorkspaceId(caller.workspace_id)),
            workspace_id=WorkspaceId(caller.workspace_id), source_agent_id=AgentId(caller.agent_id),
            target_agent_id=AgentId(target), linked_delegated_wake_grant_id=grant)

    def threads(self, caller):
        return self.platform.list_agent_exchange_threads(caller.workspace_id,
            requesting_agent_id=caller.agent_id)["agentExchangeThreads"]

    def registration_history(self, workspace_id, *, after=0):
        """Trusted, bounded-field registration facts; never session transcripts.

        Keep old handle incarnations rather than the legacy latest-by-handle
        view: a deactivated handle ID may later be registered differently.
        """
        providers = {"codex_registered_session_handle": ("codex", "codexSessionId"),
                     "claude_registered_session_handle": ("claude", "claudeSessionUuid"),
                     "hermes_registered_session_handle": ("hermes", "hermesSessionId"),
                     "deepseek_harness_registered_session_handle": ("deepseek_harness", "deepseekHarnessSessionId")}
        rows = []
        connection = self.platform.event_log_reader.connection
        facts = connection.execute(
            "SELECT sequence,aggregate_type,occurred_at,payload_json FROM platform_events "
            "WHERE workspace_id=? AND sequence>? AND aggregate_type IN (?,?,?,?) ORDER BY sequence",
            (workspace_id, after, *providers))
        for sequence, aggregate_type, occurred_at, encoded in facts:
            payload = json.loads(encoded)
            handle = payload.get("handle")
            if not isinstance(handle, dict):
                continue
            provider, native_field = providers[aggregate_type]
            metadata = handle.get("metadata") or {}
            identity = metadata.get(provider + "SessionIdentity") or {}
            runtime = metadata.get("runtimeBinding") or {}
            scope = runtime.get("sessionRoot") if provider == "deepseek_harness" else identity.get("runtimeHome")
            rows.append({"workspace_id": workspace_id, "sequence": sequence,
                         "action": payload.get("action"),
                         "agent_id": handle.get("agentId"), "provider": provider,
                         "native_session_id": handle.get(native_field), "native_scope": scope,
                         "handle_id": handle.get("handleId"), "generation": runtime.get("generationId"),
                         "state": handle.get("state"), "occurred_at": occurred_at})
        return rows

    def workspace_inventory(self):
        """Internal administration inventory; not an Agent-visible listing."""
        rows = []
        for state in self.platform.workspace_reader.list_workspace_states():
            workspace_id = state.workspace.workspace_id.value
            creation = self.platform.event_log_reader.connection.execute(
                "SELECT MIN(sequence) FROM platform_events WHERE workspace_id=? "
                "AND aggregate_type='workspace' AND json_extract(payload_json,'$.action')='created'",
                (workspace_id,)).fetchone()[0]
            rows.append({"workspace_id": workspace_id, "status": state.workspace.status.value,
                         "sequence": creation})
        return sorted(rows, key=lambda row: (row["sequence"] is None, row["sequence"] or 0, row["workspace_id"]))
