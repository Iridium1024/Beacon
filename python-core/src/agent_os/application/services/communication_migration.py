"""Explicit, fail-closed workspace cutover from legacy exchange history.

This imports historical facts without replaying sends or touching a provider.
Operators must stop old writers/workers before calling migrate: an older binary
cannot be fenced by a schema marker that it does not know how to read.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from uuid import NAMESPACE_URL, uuid5

from agent_os.domain.entities.communication import (
    AccessDenied, Caller, CommunicationError, Conflict, RecipientBinding,
    canonical, delivery_identity, stamp, text,
)
from agent_os.infrastructure.persistence.communication_store import SqliteCommunicationRepository


def _stable_id(kind: str, workspace: str, old_id: str, sequence: int) -> str:
    return f"{kind}-{uuid5(NAMESPACE_URL, canonical([workspace, kind, old_id, sequence]))}"


def _time(value: str | None, *, fallback: str) -> str:
    if not value:
        return fallback
    return stamp(datetime.fromisoformat(value))


class CommunicationMigration:
    def __init__(self, connection: sqlite3.Connection, *, directory=None,
                 repository: SqliteCommunicationRepository | None = None):
        self.connection = connection
        self.repo = repository or SqliteCommunicationRepository(connection)
        self.directory = directory

    def _history(self, workspace_id: str) -> dict:
        workspace = self.connection.execute(
            "SELECT status FROM platform_workspace_state WHERE workspace_id=?", (workspace_id,)
        ).fetchone()
        if workspace is None or workspace[0] != "active":
            raise AccessDenied("migration requires an existing active workspace")
        high = self.connection.execute(
            "SELECT COALESCE(MAX(sequence),0) FROM platform_events WHERE workspace_id=?", (workspace_id,)
        ).fetchone()[0]
        communication_high = self.connection.execute(
            "SELECT COALESCE(MAX(sequence),0) FROM platform_events WHERE workspace_id=? "
            "AND aggregate_type IN ('agent_exchange_request','agent_exchange_thread','agent_dispatch')",
            (workspace_id,),
        ).fetchone()[0]
        requests, latest, threads, dispatches, dispatch_creation = [], {}, {}, {}, {}
        rows = self.connection.execute(
            "SELECT sequence,aggregate_type,aggregate_id,payload_json FROM platform_events "
            "WHERE workspace_id=? AND aggregate_type IN "
            "('agent_exchange_request','agent_exchange_thread','agent_dispatch') ORDER BY sequence",
            (workspace_id,),
        )
        for sequence, entity, identity, encoded in rows:
            payload = json.loads(encoded)
            if entity == "agent_exchange_request":
                request = payload.get("request")
                if not isinstance(request, dict):
                    raise CommunicationError(f"request event {sequence} lacks a snapshot")
                if payload.get("action") == "created":
                    generation = {"legacy_id": identity, "legacy_sequence": sequence, "request": request}
                    requests.append(generation)
                    latest[identity] = generation
                elif identity in latest:
                    latest[identity]["request"] = request
                else:
                    raise CommunicationError(f"request update {sequence} has no creation")
            elif entity == "agent_exchange_thread":
                snapshot = payload.get("thread")
                if isinstance(snapshot, dict):
                    threads[identity] = snapshot
            else:
                snapshot = payload.get("dispatch")
                if not isinstance(snapshot, dict):
                    raise CommunicationError(f"dispatch event {sequence} lacks a snapshot")
                if identity not in dispatch_creation:
                    dispatch_creation[identity] = sequence
                dispatches[identity] = snapshot
        by_request = defaultdict(list)
        for identity, dispatch in dispatches.items():
            by_request[dispatch["exchangeRequestId"]].append((identity, dispatch_creation[identity], dispatch))
        repeated = {key: count for key, count in Counter(r["legacy_id"] for r in requests).items() if count > 1}
        multiple_dispatches = {key: len(value) for key, value in by_request.items() if len(value) > 1}
        blockers = []
        if repeated:
            blockers.append({"reason": "reused_request_id", "ids": repeated})
        if multiple_dispatches:
            blockers.append({"reason": "multiple_dispatches_for_request", "ids": multiple_dispatches})
        leased = sorted(identity for identity, dispatch in dispatches.items()
                        if dispatch.get("status") == "leased" or dispatch.get("leaseId"))
        if leased:
            blockers.append({"reason": "unreconciled_dispatch_lease", "ids": leased})
        if self.repo.mode(workspace_id) == "legacy" and self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='communication_messages'"
        ).fetchone() and self.connection.execute(
            "SELECT 1 FROM communication_messages WHERE workspace_id=? LIMIT 1", (workspace_id,)
        ).fetchone():
            blockers.append({"reason": "unmarked_new_core_writes_already_exist"})
        return {"workspace_id": workspace_id, "legacy_high_water": high,
                "legacy_communication_high_water": communication_high,
                "requests": requests, "threads": threads, "dispatches_by_request": by_request,
                "blockers": blockers}

    def preview(self, workspace_id: str) -> dict:
        text(workspace_id, "workspace_id")
        history = self._history(workspace_id)
        blockers = list(history["blockers"])
        if self.repo.mode(workspace_id) == "core":
            marker = self.repo.get("modes", workspace_id, workspace_id)
            marker_high = marker.get("legacy_communication_high_water", marker["legacy_high_water"])
            if history["legacy_communication_high_water"] > marker_high:
                blockers.append({"reason": "legacy_write_after_cutover",
                                 "marker_high_water": marker_high,
                                 "current_high_water": history["legacy_communication_high_water"]})
        return {"workspace_id": workspace_id, "engine": self.repo.mode(workspace_id),
                "legacy_high_water": history["legacy_high_water"],
                "legacy_communication_high_water": history["legacy_communication_high_water"],
                "request_count": len(history["requests"]), "thread_count": len(history["threads"]),
                "dispatch_statuses": dict(Counter(
                    item[2].get("status", "unknown") for group in history["dispatches_by_request"].values()
                    for item in group)),
                "blockers": blockers, "mutated": False,
                "requires_stopped_legacy_writers": True}

    def backup(self, destination: str) -> dict:
        """Take an explicit SQLite-consistent backup before a cutover attempt."""
        if self.connection.in_transaction:
            raise CommunicationError("backup requires a connection outside a transaction")
        target = Path(destination).expanduser().resolve()
        source = self.connection.execute("PRAGMA database_list").fetchone()[2]
        if source and target == Path(source).resolve():
            raise CommunicationError("backup path must differ from the source database")
        if target.exists():
            raise CommunicationError("backup path already exists")
        if not target.parent.is_dir():
            raise CommunicationError("backup parent directory does not exist")
        target.touch(exist_ok=False)
        try:
            with closing(sqlite3.connect(target)) as backup_connection:
                self.connection.backup(backup_connection)
            digest = sha256()
            with target.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            return {"path": str(target), "sha256": digest.hexdigest(),
                    "bytes": target.stat().st_size}
        except BaseException:
            target.unlink(missing_ok=True)
            raise

    def _queued_binding(self, workspace: str, request: dict, dispatch: dict) -> tuple[dict | None, str, dict | None]:
        if (dispatch.get("status") != "queued" or dispatch.get("attemptCount") != 0
                or dispatch.get("leaseId") or dispatch.get("providerActivationExecuted")
                or dispatch.get("dispatcherRequired") is False):
            return None, "unknown", None
        metadata = dispatch.get("metadata") or {}
        mode = metadata.get("replyWritebackMode")
        if mode not in {"explicit_only", "provider_final_capture"} or self.directory is None:
            return None, "unknown", None
        try:
            binding = self.directory.resolve_exact_legacy_target(
                workspace, request["targetAgentId"], dispatch["targetHandleId"]
            )
            resolution = (metadata.get("agentDispatchSend") or {}).get("endpointAliasResolution") or {}
            source_endpoint = resolution.get("sourceEndpoint") or {}
            source_alias = source_endpoint.get("alias")
            reply_policy = dispatch.get("replyPolicy", "source_handle_optional")
            source_handle_id = dispatch.get("sourceHandleId")
            if source_alias is None and (source_handle_id is not None or reply_policy != "message_only"):
                return None, "unknown", None
            routing = {"source_alias": source_alias, "reply_policy": reply_policy,
                       "source_handle_id": source_handle_id,
                       "target_handle_id": dispatch["targetHandleId"]}
            self.directory.authorize_send_context(
                Caller(workspace, request["sourceAgentId"]), binding.alias, **routing)
            if not binding.automatic_activation_allowed:
                return None, "unknown", None
        except (AccessDenied, ValueError, KeyError, TypeError):
            return None, "unknown", None
        return binding.to_dict(), "pending", routing

    def migrate(self, workspace_id: str, *, operator: str, stopped_writers_confirmed: bool) -> dict:
        text(workspace_id, "workspace_id")
        text(operator, "operator")
        if stopped_writers_confirmed is not True:
            raise CommunicationError("operator must confirm a stopped-writer window")
        # Schema creation is a separate explicit phase; only the marker and all
        # imported facts below decide workspace engine ownership atomically.
        self.repo.initialize()
        with self.repo.transaction():
            current = self.repo.mode(workspace_id)
            if current == "core":
                marker = self.repo.get("modes", workspace_id, workspace_id)
                high = self.connection.execute(
                    "SELECT COALESCE(MAX(sequence),0) FROM platform_events WHERE workspace_id=? "
                    "AND aggregate_type IN ('agent_exchange_request','agent_exchange_thread','agent_dispatch')",
                    (workspace_id,)).fetchone()[0]
                if high > marker.get("legacy_communication_high_water", marker["legacy_high_water"]):
                    raise Conflict("legacy platform writes occurred after communication cutover")
                return {"workspace_id": workspace_id, "engine": "core", "created": False,
                        "imported_requests": marker["imported_requests"]}
            if current != "legacy":
                raise CommunicationError("unknown communication engine marker")
            history = self._history(workspace_id)
            if history["blockers"]:
                raise Conflict("migration preview has unresolved ambiguity: " + canonical(history["blockers"]))
            now = stamp(datetime.now(timezone.utc))
            threads = {}
            changes: dict[str, list[dict]] = {"threads": [], "messages": [], "deliveries": [],
                                             "receipts": [], "mappings": [], "modes": []}
            notices: list[dict] = []
            for entry in history["requests"]:
                request = entry["request"]
                old_id, original_sequence = entry["legacy_id"], entry["legacy_sequence"]
                sender, target = request["sourceAgentId"], request["targetAgentId"]
                thread_id = request.get("threadId") or old_id
                legacy_thread = history["threads"].get(thread_id, {})
                if thread_id not in threads:
                    threads[thread_id] = {"workspace_id": workspace_id, "id": thread_id,
                        "visibility": legacy_thread.get("visibility", "workspace_readable"),
                        "participants": list(legacy_thread.get("participantAgentIds") or ()),
                        "status": "closed" if legacy_thread.get("threadStatus") == "terminal" else "active",
                        "legacy": False, "historical": True,
                        "legacy_budget": {key: legacy_thread.get(key) for key in
                                          ("maxTurns", "completedTurnCount", "activeRequestCount", "followUpPolicy")}}
                threads[thread_id]["participants"] = sorted(set(threads[thread_id]["participants"]) | {sender, target})
                message_id = _stable_id("message", workspace_id, old_id, original_sequence)
                dispatches = history["dispatches_by_request"].get(old_id, ())
                binding, schedule, routing = (
                    self._queued_binding(workspace_id, request, dispatches[0][2])
                    if dispatches and request.get("status") == "active" else (None, "none", None))
                if request.get("status") == "active" and schedule == "none":
                    schedule = "unknown"
                created = _time(request.get("createdAt"), fallback=now)
                expires = (_time(request["expiresAt"], fallback=now) if request.get("expiresAt") else None)
                message = {"workspace_id": workspace_id, "id": message_id, "sender": sender,
                    "target": target, "thread_id": thread_id, "body": request["requestSummary"],
                    "refs": list(request.get("detailRefs") or ()), "created_at": created,
                    "expires_at": expires, "reply_to": None, "expectation": "none", "origin": "agent",
                    "historical": True, "legacy_request_id": old_id,
                    "legacy_request_status": request.get("status"),
                    "legacy_request_kind": request.get("requestKind"),
                    "legacy_terminal_reason": request.get("terminalReason"),
                    "legacy_request_sequence": original_sequence,
                    "legacy_parent_request_id": request.get("parentRequestId"),
                    "legacy_root_request_id": request.get("rootRequestId"),
                    "legacy_turn_index": request.get("turnIndex"),
                    "legacy_max_response_length": request.get("maxResponseLength"),
                    "legacy_requires_user_review": bool(request.get("requiresUserReview"))}
                closed_at = (_time(request["closedAt"], fallback=now) if request.get("closedAt") else None)
                if expires is not None and expires <= now and schedule == "pending":
                    schedule = "expired"
                delivery = {"workspace_id": workspace_id, "id": delivery_identity(message_id, target),
                    "message_id": message_id, "target": target, "binding": binding,
                    "session_key": ("historical:" + message_id if binding is None else
                                    RecipientBinding(**binding).session_key),
                    "schedule": schedule, "wake": "when_available" if schedule == "pending" else "none",
                    "delivery": "unknown", "execution": "unknown", "capture": "explicit_only",
                    "attempt_count": 0, "max_attempts": 3, "closed_at": closed_at,
                    "historical": True, "routing": routing}
                if dispatches:
                    old_dispatch = dispatches[0][2]
                    delivery["legacy_dispatch_status"] = old_dispatch.get("status")
                    delivery["legacy_provider_activation_executed"] = bool(
                        old_dispatch.get("providerActivationExecuted"))
                    delivery["legacy_provider_runtime_state"] = old_dispatch.get("providerRuntimeState", "unknown")
                    delivery["legacy_attempt_count"] = old_dispatch.get("attemptCount", 0)
                if binding is not None:
                    delivery.update(delivery="stored", execution="not_started",
                                    capture=dispatches[0][2]["metadata"]["replyWritebackMode"])
                    if dispatches[0][2].get("nextAttemptAfter"):
                        delivery["eligible_after"] = _time(
                            dispatches[0][2]["nextAttemptAfter"], fallback=now)
                if request.get("terminalReason") == "responded" and request.get("responseSummary"):
                    delivery["schedule"] = "done"
                    receipt = {"workspace_id": workspace_id,
                        "id": _stable_id("receipt", workspace_id, old_id, original_sequence),
                        "message_id": message_id, "target": target,
                        "author": request.get("respondedByAgentId") or target,
                        "kind": "final", "body": request["responseSummary"],
                        "created_at": _time(request.get("respondedAt"), fallback=now),
                        "source": "legacy_import", "attempt_id": None, "late": False,
                        "requires_user_review": bool(request.get("requiresUserReview"))}
                    changes["receipts"].append(receipt)
                    notices.append({"viewer": sender, "message_id": message_id,
                                    "kind": "final", "receipt_id": receipt["id"]})
                changes["messages"].append(message)
                changes["deliveries"].append(delivery)
                notices.append({"viewer": target, "message_id": message_id, "kind": "message"})
                changes["mappings"].append({"workspace_id": workspace_id,
                    "id": _stable_id("mapping", workspace_id, old_id, original_sequence),
                    "kind": "request", "legacy_id": old_id, "legacy_sequence": original_sequence,
                    "new_id": message_id})
                if dispatches:
                    dispatch_id, dispatch_sequence, _ = dispatches[0]
                    changes["mappings"].append({"workspace_id": workspace_id,
                        "id": _stable_id("mapping", workspace_id, dispatch_id, dispatch_sequence),
                        "kind": "dispatch", "legacy_id": dispatch_id,
                        "legacy_sequence": dispatch_sequence, "new_id": message_id})
            # A thread can outlive all retained requests (or be created by an
            # older writer). Its visibility and closed state are still history.
            for thread_id, legacy_thread in history["threads"].items():
                if thread_id not in threads:
                    threads[thread_id] = {"workspace_id": workspace_id, "id": thread_id,
                        "visibility": legacy_thread.get("visibility", "workspace_readable"),
                        "participants": list(legacy_thread.get("participantAgentIds") or ()),
                        "status": "closed" if legacy_thread.get("threadStatus") == "terminal" else "active",
                        "legacy": False, "historical": True,
                        "legacy_budget": {key: legacy_thread.get(key) for key in
                                          ("maxTurns", "completedTurnCount", "activeRequestCount", "followUpPolicy")}}
            changes["threads"] = list(threads.values())
            marker = {"workspace_id": workspace_id, "id": workspace_id, "mode": "core",
                      "schema_version": 2, "legacy_high_water": history["legacy_high_water"],
                      "legacy_communication_high_water": history["legacy_communication_high_water"],
                      "imported_requests": len(history["requests"]), "migrated_at": now}
            changes["modes"].append(marker)
            self.repo.append(workspace_id, operator, "workspace_cutover", now, changes, tuple(notices))
            return {"workspace_id": workspace_id, "engine": "core", "created": True,
                    "imported_requests": len(history["requests"]),
                    "legacy_high_water": history["legacy_high_water"]}

    def legacy_message_id(self, workspace_id: str, *, kind: str, legacy_id: str) -> str:
        matches = self.repo.mappings_for_legacy(workspace_id, kind, legacy_id)
        if len(matches) != 1:
            raise Conflict("legacy identity has no unique new message mapping")
        return matches[0]["new_id"]

    def downgrade_advice(self, workspace_id: str) -> dict:
        """Read-only guard; never silently switches a cut-over workspace back."""
        marker = self.repo.get("modes", workspace_id, workspace_id) if self.repo.mode(workspace_id) == "core" else None
        if marker is None:
            return {"workspace_id": workspace_id, "mode": "legacy", "automatic_downgrade": False}
        marker_sequence = self.repo.sequence("modes", workspace_id, workspace_id)
        return {"workspace_id": workspace_id, "mode": "core", "automatic_downgrade": False,
                "new_semantic_writes": self.repo.workspace_high_water(workspace_id) > marker_sequence,
                "recovery": "stop writers; retain/export communication_events after the backup before any manual restore"}
