"""Execute one existing backend under a core-owned communication attempt.

This adapter freezes the backend and capture policy recorded at send time.
Old provider runners retain their native checks and diagnostic events, while
the core worker alone commits message delivery and any captured final.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

from agent_os.application.services.agent_dispatch import AgentDispatchRecord
from agent_os.application.services.communication_provider_scope import (
    CoreProviderScope, core_provider_scope,
)
from agent_os.domain.entities.communication import (
    Claim, CommunicationError, ProviderEvidence, delivery_identity,
)
from agent_os.domain.value_objects.identifiers import WorkspaceId


_ACTIVATION_KEYS = {
    "claude": "claudeRegisteredSessionActivation",
    "codex": "codexRegisteredSessionActivation",
    "hermes": "hermesRegisteredSessionActivation",
    "deepseek_harness": "deepseekHarnessRegisteredSessionActivation",
}

# Existing worker defaults, shared with independently assembled executors.
_OPTION_DEFAULTS = {
    "config_path": None, "handoff_directory": None, "platform_workspace_root": None,
    "claude_executable": "claude", "claude_default_platform_workspace_add_dir": True,
    "claude_add_dirs": (), "claude_allowed_tools": (), "claude_permission_mode": None,
    "claude_settings_path": None, "claude_activation_backend": "cli", "claude_reply_writeback_mode": None,
    "codex_executable": "codex", "codex_default_platform_workspace_add_dir": True,
    "codex_add_dirs": (), "codex_sandbox_mode": None, "codex_approval_policy": None,
    "codex_git_repo_check_policy": "skip", "codex_git_repo_check_policy_source": "default",
    "codex_activation_backend": "exec_resume", "codex_app_server_approval_decision": "decline",
    "codex_reply_writeback_mode": "explicit_only", "hermes_executable": "hermes", "hermes_home": None,
    "hermes_activation_backend": "cli", "hermes_reply_writeback_mode": None,
    "hermes_gateway_python": None, "hermes_source_tag": "agent-os", "hermes_max_turns": None,
}


class CoreProviderAdapter:
    def __init__(self, service, platform, options: Mapping[str, object], *, actual_via: str = "queued"):
        self.service = service
        self.platform = platform
        self.options = {**_OPTION_DEFAULTS, **options}
        self.compact_enabled = self.options.pop("compact_messages", False)
        if type(self.compact_enabled) is not bool:
            raise CommunicationError("compact_messages must be a trusted boolean option")
        if actual_via not in {"inline", "queued"}:
            raise CommunicationError("invalid executor entry path")
        self.actual_via = actual_via
        # These send/preflight controls are not activation-runner keyword arguments.
        for name in ("codex_busy_delivery_policy", "codex_busy_delivery_policy_explicit", "immediate_busy_policy"):
            self.options.pop(name, None)

    def _dispatch(self, message: dict, binding: dict, delivery: dict) -> AgentDispatchRecord:
        routing = delivery.get("routing") or {}
        return AgentDispatchRecord.from_mapping({
            "workspaceId": message["workspace_id"],
            "dispatchId": message.get("legacy_dispatch_id") or delivery.get("legacy_dispatch_id")
                or f"core-{message['id']}",
            "exchangeRequestId": message.get("legacy_request_id") or message["id"],
            "sourceAgentId": message["sender"], "targetAgentId": message["target"],
            "threadId": message["thread_id"],
            "sourceHandleId": routing.get("source_handle_id"),
            "targetHandleId": binding["handle_id"], "targetProvider": binding["provider"],
            "replyPolicy": routing.get("reply_policy") or "message_only",
            "status": "leased", "metadata": {"coreMessageId": message["id"]},
        })

    def preflight(self, message: dict, binding: dict, *,
                  read_live_runtime_status: bool | str = "auto") -> dict:
        delivery = self.service.repo.get("deliveries", message["workspace_id"],
            delivery_identity(message["id"], message["target"]))
        if delivery is None:
            raise CommunicationError("missing core delivery")
        dispatch = self._dispatch(message, binding, delivery)
        return dict(self.platform._agent_dispatch_target_runtime_status(
            WorkspaceId(message["workspace_id"]), dispatch,
            read_live_runtime_status=read_live_runtime_status))

    def __call__(self, message: dict, binding: dict, claim: Claim,
                 provider_timeout_seconds: int) -> ProviderEvidence:
        if message["id"] != claim.message_id or message["target"] != binding["agent_id"]:
            raise CommunicationError("provider attempt message and binding differ")
        provider = binding["provider"]
        if provider not in _ACTIVATION_KEYS:
            raise CommunicationError("unsupported provider")
        backend = message.get("legacy_provider_backend")
        delivery = self.service.repo.get("deliveries", claim.workspace_id,
            delivery_identity(message["id"], message["target"]))
        if delivery is None or (message.get("legacy_capture_policy") is not None
                                and delivery["capture"] != message["legacy_capture_policy"]):
            raise CommunicationError("frozen provider capture policy differs")
        backend = backend or delivery.get("provider_backend")
        dispatch = self._dispatch(message, binding, delivery)
        options = dict(self.options)
        options["activation_timeout_seconds"] = provider_timeout_seconds
        options["occurred_at"] = datetime.now(timezone.utc)
        if provider == "claude":
            backend = backend or options.get("claude_activation_backend", "cli")
            options["claude_activation_backend"] = backend
            options["claude_reply_writeback_mode"] = delivery["capture"]
        elif provider == "codex":
            backend = backend or options.get("codex_activation_backend", "exec_resume")
            options["codex_activation_backend"] = backend
            options["codex_reply_writeback_mode"] = delivery["capture"]
        elif provider == "hermes":
            backend = backend or options.get("hermes_activation_backend", "cli")
            options["hermes_activation_backend"] = backend
            options["hermes_reply_writeback_mode"] = delivery["capture"]
        elif backend not in (None, "sdk_stdio"):
            raise CommunicationError("unsupported frozen DSH backend")
        self.service.record_execution_path(claim, self.actual_via)
        scope = CoreProviderScope(self.service, claim, compact_enabled=self.compact_enabled,
                                  actual_via=self.actual_via)
        with core_provider_scope(scope):
            output = self.platform._activate_agent_dispatch_provider(
                WorkspaceId(claim.workspace_id), dispatch=dispatch,
                provider=provider, **options)
        activation = output.get(_ACTIVATION_KEYS[provider])
        if not isinstance(activation, Mapping):
            raise CommunicationError("provider returned no activation evidence")
        status = str(activation.get("status") or "unknown")
        started = activation.get("providerCommandStarted") is True
        timed_out = activation.get("providerProcessTimedOut") is True
        ambiguous = activation.get("ambiguousDelivery") is True
        # A ticket or runner return value alone cannot prove that the target
        # session executed or stopped. Require the runner's start evidence too.
        stopped = started and status in {"delivered", "failed"} and not timed_out and not ambiguous
        if not stopped:
            outcome = "unknown"
        elif status == "delivered":
            outcome = "finished"
        else:
            outcome = "failed" if started or scope.final else "unknown"
        explicit_final = next((r for r in self.service.repo.receipts(claim.workspace_id, message["id"])
                               if r["kind"] == "final" and not r["late"]), None)
        accepted = scope.final is not None or explicit_final is not None
        if scope.final is not None and outcome == "unknown":
            # A trusted final is meaningful, but uncertain process stop still
            # requires reconciliation before a terminal capture can be written.
            accepted = False
            scope.final = None
        sequence = activation.get("sourceEventSequence")
        evidence_ref = (f"platform-event:{sequence}" if isinstance(sequence, int) and sequence > 0
                        else f"provider-attempt:{activation.get('activationAttemptId') or claim.attempt_id}")
        return ProviderEvidence(provider=provider, native_session_id=binding["native_session_id"],
            generation=binding["generation"], outcome=outcome,
            evidence_ref=evidence_ref, accepted=accepted, stopped=stopped,
            final=scope.final, trusted_final=scope.final is not None,
            requires_user_review=scope.requires_user_review or (scope.final is not None and outcome == "failed"),
            provider_command_started=started)
