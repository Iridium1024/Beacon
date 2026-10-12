"""Opt-in communication use cases. No provider I/O or background execution.

Agent operations and executor evidence are separate entry surfaces. Their local
identity declarations are not authentication; a future adapter must bind callers.
"""
from __future__ import annotations

import base64
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from typing import Callable
from collections.abc import Mapping
from uuid import uuid4

from agent_os.domain.entities.communication import (
    AccessDenied, Caller, Claim, CommunicationError, Conflict, Message,
    ProviderEvidence, ReceiptKind, RecipientBinding, ReplyExpectation,
    StaleAttempt, ThreadVisibility, canonical, delivery_identity, stamp, text,
)
from agent_os.domain.ports.communication import CommunicationDirectory, CommunicationRepository
from agent_os.domain.ports.communication_runtime import RuntimeCoordination


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


class CommunicationService:
    def __init__(self, repository: CommunicationRepository, directory: CommunicationDirectory,
                 *, clock: Callable[[], datetime] | None = None,
                 send_compatibility: Callable | None = None,
                 coordination: RuntimeCoordination | None = None):
        self.repo = repository
        self.directory = directory
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.send_compatibility = send_compatibility
        self.coordination = coordination

    def _now(self) -> str:
        return stamp(self.clock())

    def _operation(self, caller: Caller, operation: str, key: str, payload: dict, work: Callable,
                   *, validate: Callable | None = None) -> dict:
        text(key, "idempotency key")
        normalized = canonical(payload)
        with self.repo.transaction():
            self.directory.require_member(caller)
            if validate is not None:
                validate()
            prior = self.repo.idempotency(caller.workspace_id, caller.agent_id, operation, key)
            if prior:
                if prior["payload"] != normalized:
                    raise Conflict("idempotency key used with a different payload")
                # An old operation key must not bypass a later visibility change.
                if operation == "send":
                    self._message(caller, prior["result"]["id"])
                elif "message_id" in payload:
                    self._message(caller, payload["message_id"])
                elif operation == "cancel_observation":
                    self._observation(caller, payload["id"])
                return prior["result"]
            now = self._now()
            result, changes, notices = work(now)
            changes["idempotency"] = [{"actor": caller.agent_id, "operation": operation,
                                       "key": key, "payload": normalized, "result": result}]
            self.repo.append(caller.workspace_id, caller.agent_id, operation, now, changes, notices)
            if self.coordination is not None and operation == "send":
                self.coordination.notice(caller.workspace_id, changes.get("deliveries", []), now)
            return result

    def _thread(self, caller: Caller, thread_id: str) -> dict:
        thread = self.repo.get("threads", caller.workspace_id, thread_id)
        if thread is None:
            thread = self.directory.existing_thread(caller, thread_id)
        elif thread.get("legacy"):
            # Legacy visibility changes are still authoritative until C1-B migration.
            current = self.directory.existing_thread(caller, thread_id)
            if current is None:
                raise AccessDenied("thread is not visible")
            thread = {**thread, "visibility": current["visibility"], "participants": current["participants"]}
        if thread is None or (thread["visibility"] == "participants_only" and caller.agent_id not in thread["participants"]):
            raise AccessDenied("thread is not visible")
        return thread

    def _message(self, caller: Caller, message_id: str) -> dict:
        self.directory.require_member(caller)
        message = self.repo.get("messages", caller.workspace_id, message_id)
        if message is None:
            raise AccessDenied("message is not in this workspace")
        self._thread(caller, message["thread_id"])
        return message

    def _delivery(self, message: dict) -> dict:
        delivery = self.repo.get("deliveries", message["workspace_id"], delivery_identity(message["id"], message["target"]))
        if delivery is None:
            raise CommunicationError("missing delivery projection")
        return delivery

    def change_thread_visibility(self, caller: Caller, thread_id: str,
                                 visibility: str) -> dict:
        ThreadVisibility(visibility)
        with self.repo.transaction():
            thread = self._thread(caller, thread_id)
            if caller.agent_id not in thread["participants"]:
                raise AccessDenied("only thread participants may update visibility")
            updated = {**thread, "visibility": visibility}
            self.repo.append(caller.workspace_id, caller.agent_id, "thread_visibility",
                self._now(), {"threads": [updated]})
            return updated

    def arm_direct_activation(self, workspace_id: str, message_id: str, *,
                              target_agent_id: str, handle_id: str, provider: str,
                              backend: str, capture: str, dispatch_id: str,
                              dry_run: bool = False) -> dict:
        """Convert a request-only message into one core-owned execution intent."""
        if capture not in {"explicit_only", "provider_final_capture"}:
            raise CommunicationError("invalid direct activation capture policy")
        text(dispatch_id, "dispatch id")
        with self.repo.transaction(write=not dry_run):
            now = self._now()
            message = self.repo.get("messages", workspace_id, message_id)
            if message is None:
                raise AccessDenied("request is not in this workspace")
            delivery = self._delivery(message)
            if delivery.get("binding") is None:
                raise Conflict("historical request has no active delivery binding")
            binding = RecipientBinding(**delivery["binding"])
            if (binding.agent_id != target_agent_id or binding.handle_id != handle_id
                    or binding.provider != provider):
                raise Conflict("direct activation target does not match frozen binding")
            if (self._expired(message, now) or delivery["closed_at"] or
                    any(r["kind"] in {"final", "reject"} for r in self.repo.receipts(workspace_id, message_id))):
                raise Conflict("request is already terminal or expired")
            thread = self._thread(Caller(workspace_id, message["sender"]), message["thread_id"])
            if thread.get("status") == "closed":
                raise Conflict("thread is closed")
            self._activation_binding(message, delivery)
            existing = delivery.get("legacy_dispatch_id") or message.get("legacy_dispatch_id")
            if existing is not None:
                if (existing != dispatch_id or delivery["schedule"] != "pending"
                        or (delivery.get("provider_backend") or message.get("legacy_provider_backend")) != backend
                        or delivery["capture"] != capture):
                    raise Conflict("direct activation differs from existing dispatch")
                return {"message_id": message_id, "dispatch_id": existing, "created": False}
            if delivery["schedule"] != "none" or delivery["execution"] != "not_started":
                raise Conflict("request delivery cannot be safely armed")
            if self.repo.mappings_for_legacy(workspace_id, "dispatch", dispatch_id):
                raise Conflict("dispatch ID already has a core mapping")
            if dry_run:
                return {"message_id": message_id, "dispatch_id": dispatch_id,
                        "created": False, "would_create": True}
            delivery.update(schedule="pending", wake="when_available", capture=capture,
                            provider_backend=backend, legacy_dispatch_id=dispatch_id)
            mapping = {"workspace_id": workspace_id, "id": _id("mapping"), "kind": "dispatch",
                       "legacy_id": dispatch_id, "legacy_sequence": 0, "new_id": message_id}
            self.repo.append(workspace_id, target_agent_id, "direct_activation_armed", now,
                             {"deliveries": [delivery], "mappings": [mapping]})
            return {"message_id": message_id, "dispatch_id": dispatch_id, "created": True}

    def close_thread(self, caller: Caller, thread_id: str, *, reason: str = "closed") -> dict:
        if reason not in {"closed", "revoked", "expired", "blocked"}:
            raise CommunicationError("invalid thread close reason")
        with self.repo.transaction():
            thread = self._thread(caller, thread_id)
            if caller.agent_id not in thread["participants"]:
                raise AccessDenied("only thread participants may close a thread")
            if thread.get("status") == "closed":
                raise Conflict("thread is already terminal")
            updated = {**thread, "status": "closed", "terminal_reason": reason,
                       "closed_at": self._now()}
            self.repo.append(caller.workspace_id, caller.agent_id, "thread_closed",
                updated["closed_at"], {"threads": [updated]})
            return updated

    @staticmethod
    def _expired(message: dict, now: str) -> bool:
        return message["expires_at"] is not None and message["expires_at"] <= now

    def _retry_schedule(self, message: dict, delivery: dict, now: str) -> str:
        """Known non-delivery permits retry only while the message remains eligible."""
        if delivery["closed_at"]:
            return "cancelled"
        if self._expired(message, now):
            return "expired"
        if any(r["kind"] in {"final", "reject"} for r in self.repo.receipts(message["workspace_id"], message["id"])):
            return "done"
        return "pending"

    def _activation_binding(self, message: dict, delivery: dict) -> RecipientBinding:
        caller = Caller(message["workspace_id"], message["sender"])
        self._message(caller, message["id"])
        binding = RecipientBinding(**delivery["binding"])
        routing = delivery.get("routing")
        if routing is not None:
            self.directory.authorize_send_context(caller, binding.alias, **routing)
        else:
            self.directory.authorize_send(caller, binding.alias)
        self.directory.require_member(Caller(caller.workspace_id, binding.agent_id))
        if self.directory.resolve(caller.workspace_id, binding.alias) != binding:
            raise Conflict("recipient binding changed; explicit reconciliation required")
        if not binding.automatic_activation_allowed:
            raise AccessDenied("shared provider session remains manual-only")
        return binding

    def send(self, caller: Caller, *, target_alias: str, body: str, key: str,
             refs: tuple[str, ...] = (), thread_id: str | None = None,
             reply_to: str | None = None, visibility: str = "workspace_readable",
             expectation: str = "none", expires_at: datetime | None = None,
             wake: str = "when_available", capture: str = "explicit_only",
             max_attempts: int = 3, origin: str = "agent",
             source_alias: str | None = None, reply_policy: str | None = None,
             source_handle_id: str | None = None,
             target_handle_id: str | None = None,
             linked_delegated_wake_grant_id: str | None = None,
             legacy_context: Mapping | None = None,
             require_consumer: bool = False,
             delivery_path: str | None = None,
             target_session_ref: str | None = None) -> dict:
        text(body, "body")
        text(target_alias, "target_alias")
        if not isinstance(refs, (tuple, list)):
            raise CommunicationError("references must be a sequence of strings")
        refs = tuple(refs)
        if len(body) > 16000 or any(not isinstance(r, str) or not r.strip() for r in refs):
            raise CommunicationError("invalid body length or references")
        if origin != "agent":
            raise AccessDenied("agent entry cannot create user authority")
        ThreadVisibility(visibility)
        ReplyExpectation(expectation)
        if wake not in {"none", "when_available"} or capture not in {"explicit_only", "provider_final_capture"}:
            raise CommunicationError("invalid wake or capture policy")
        if delivery_path not in {None, "store", "inline", "queued", "unknown"}:
            raise CommunicationError("invalid trusted delivery path")
        if ((delivery_path == "store" and wake != "none")
                or (delivery_path in {"inline", "queued"} and wake == "none")):
            raise CommunicationError("delivery path differs from the submitted wake policy")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 10:
            raise CommunicationError("max_attempts must be 1..10")
        routing = ({"source_alias": source_alias, "reply_policy": reply_policy or "message_only",
                    "source_handle_id": source_handle_id, "target_handle_id": target_handle_id,
                    "linked_delegated_wake_grant_id": linked_delegated_wake_grant_id}
                   if any(value is not None for value in
                          (source_alias, reply_policy, source_handle_id, target_handle_id,
                           linked_delegated_wake_grant_id)) else None)
        expiry = stamp(expires_at) if expires_at is not None else None
        if legacy_context is not None:
            if self.send_compatibility is None:
                raise CommunicationError("legacy send context requires the production compatibility adapter")
            legacy_context = dict(legacy_context)
            canonical(legacy_context)
        payload = dict(target_alias=target_alias, body=body, refs=list(refs), thread_id=thread_id,
                       reply_to=reply_to, visibility=visibility, expectation=expectation,
                       expires_at=expiry, wake=wake, capture=capture, max_attempts=max_attempts,
                       routing=routing, legacy_context=legacy_context)

        def work(now):
            if require_consumer and (self.coordination is None or
                    self.coordination.consumer_status(caller.workspace_id, now)["state"] != "running"):
                raise CommunicationError("consumer_unavailable: start an explicitly initialized core consumer")
            if expiry is not None and expiry <= now:
                raise CommunicationError("cannot send an expired message")
            if routing is not None:
                self.directory.authorize_send_context(caller, target_alias, **routing)
            else:
                self.directory.authorize_send(caller, target_alias)
            binding = self.directory.resolve(caller.workspace_id, target_alias)
            if binding.agent_id == caller.agent_id:
                raise CommunicationError("source and target must differ")
            if reply_to:
                parent = self._message(caller, reply_to)
                if thread_id and parent["thread_id"] != thread_id:
                    raise Conflict("reply_to thread mismatch")
                selected_thread = parent["thread_id"]
            else:
                selected_thread = thread_id
            if selected_thread:
                thread = self._thread(caller, selected_thread)
                if thread.get("status") == "closed":
                    raise Conflict("thread is closed")
                if (thread.get("legacy") and thread["visibility"] == "participants_only"
                        and binding.agent_id not in thread["participants"]):
                    raise AccessDenied("legacy private thread cannot acquire new participants before migration")
            else:
                thread = {"workspace_id": caller.workspace_id,
                          "id": legacy_context["request_id"] if legacy_context else _id("thread"),
                          "visibility": visibility, "participants": [], "legacy": False}
            thread["participants"] = sorted(set(thread["participants"]) | {caller.agent_id, binding.agent_id})
            compatibility = (self.send_compatibility(caller, binding, thread, body, refs,
                                                     reply_to, legacy_context, now)
                             if legacy_context is not None else {})
            message = Message(caller.workspace_id, _id("message"), caller.agent_id, binding.agent_id,
                              thread["id"], body, tuple(refs), now, expiry, reply_to, expectation).to_dict()
            message.update(compatibility)
            delivery = {"workspace_id": caller.workspace_id, "id": delivery_identity(message["id"], binding.agent_id),
                        "message_id": message["id"], "target": binding.agent_id,
                        "binding": binding.to_dict(), "session_key": binding.session_key,
                        "schedule": "pending" if wake != "none" else "none", "wake": wake,
                        "delivery": "stored", "execution": "not_started", "capture": capture,
                        "attempt_count": 0, "max_attempts": max_attempts, "closed_at": None,
                        "routing": routing}
            changes = {"threads": [thread], "messages": [message], "deliveries": [delivery]}
            # These representations join the existing owned send transaction.
            # They are deliberately absent from the semantic idempotency payload:
            # changing display/attempt paths cannot create or mutate a message.
            if self._short_refs_enabled(caller.workspace_id):
                from agent_os.application.services.communication_short_refs import ShortReferences, facts_from_handle
                short = ShortReferences(self)
                short.sync_registration_history(caller.workspace_id, caller.agent_id, now)
                source_facts = None
                if source_alias is not None:
                    endpoint = self.directory.reader.endpoint(caller.workspace_id, source_alias)
                    address, handle = endpoint.get("agentEndpoint", {}), endpoint.get("providerHandle")
                    if (not handle or address.get("agentId") != caller.agent_id
                            or handle.get("agentId") != caller.agent_id
                            or address.get("providerHandleId") != handle.get("handleId")
                            or (source_handle_id is not None and source_handle_id != handle.get("handleId"))):
                        raise AccessDenied("compact source differs from the authorized send binding")
                    source_facts = facts_from_handle(handle, address["provider"])
                    source_facts["alias"] = source_alias
                path = delivery_path or ("store" if wake == "none" else "unknown")
                changes.update(short.for_send(message, delivery, source_facts, via=path, now=now))
            if legacy_context is not None:
                changes["mappings"] = [
                    {"workspace_id": caller.workspace_id, "id": _id("mapping"), "kind": kind,
                     "legacy_id": legacy_context[field], "legacy_sequence": 0,
                     "new_id": message["id"]}
                    for kind, field in (("request", "request_id"), ("dispatch", "dispatch_id"))
                    if legacy_context.get(field) is not None
                ]
            return message, changes, (
                {"viewer": binding.agent_id, "message_id": message["id"], "kind": "message"},)

        def validate_target():
            from agent_os.application.services.communication_short_refs import ShortReferences
            binding = self.directory.resolve(caller.workspace_id, target_alias)
            ShortReferences(self).assert_target_binding(caller, target_session_ref, binding.to_dict())

        return self._operation(caller, "send", key, payload, work,
                               validate=validate_target if target_session_ref is not None else None)

    def _short_refs_enabled(self, workspace_id: str) -> bool:
        available = getattr(self.repo, "short_extension", None)
        return bool(callable(available) and available()
                    and self.repo.get("ref_modes", workspace_id, workspace_id))

    def record_execution_path(self, claim: Claim, via: str) -> None:
        """Executor-only attempt fact; no message/receipt or schedule semantics."""
        if via not in {"inline", "queued"}:
            raise CommunicationError("execution path must be inline or queued")
        with self.repo.transaction():
            now = self._now()
            _, attempt, _, delivery = self._owned(claim, now)
            if not self._short_refs_enabled(claim.workspace_id):
                return
            if attempt["phase"] not in {"started", "running"}:
                raise Conflict("execution path requires a started owned attempt")
            if attempt.get("execution_via") is not None:
                if attempt["execution_via"] != via:
                    raise Conflict("one attempt cannot change its execution path")
                return
            attempt["execution_via"] = via
            delivery["execution_via"] = via
            self.repo.append(claim.workspace_id, claim.owner, "execution_path", now,
                             {"attempts": [attempt], "deliveries": [delivery]})

    def get(self, caller: Caller, message_id: str) -> dict:
        with self.repo.transaction(write=False):
            return self._message(caller, message_id)

    def _status(self, caller: Caller, message_id: str, now: str) -> dict:
        message = self._message(caller, message_id)
        delivery = self._delivery(message)
        receipts = self.repo.receipts(caller.workspace_id, message_id)
        terminal = next((r for r in receipts if r["kind"] in {"final", "reject"} and not r["late"]), None)
        waiters = (self.coordination.waiters(caller.workspace_id, message_id, now)
                   if self.coordination is not None and caller.agent_id in {message["sender"], message["target"]}
                   else [])
        return {"message": message, "delivery": delivery, "receipts": receipts,
                "expired": self._expired(message, now),
                "acknowledged": any(r["kind"] == "ack" and not r["late"] for r in receipts),
                "reply": terminal["kind"] if terminal else "none",
                "reply_expected": message["expectation"], "waiters": waiters,
                "active_waiter_verified": any(w["state"] == "active" for w in waiters)}

    def status(self, caller: Caller, message_id: str) -> dict:
        with self.repo.transaction(write=False):
            return self._status(caller, message_id, self._now())

    def _new_receipt(self, message: dict, delivery: dict, kind: str, body: str,
                     now: str, *, source: str = "explicit", attempt_id: str | None = None,
                     requires_user_review: bool = False) -> dict:
        return {"workspace_id": message["workspace_id"], "id": _id("receipt"),
                "message_id": message["id"], "target": message["target"], "author": message["target"],
                "kind": kind, "body": body, "created_at": now, "source": source,
                "attempt_id": attempt_id, "late": bool(delivery["closed_at"] or self._expired(message, now)),
                "requires_user_review": requires_user_review}

    @staticmethod
    def _receipt_notice(message: dict, receipt: dict) -> tuple[dict, ...]:
        return ({"viewer": message["sender"], "message_id": message["id"],
                 "kind": receipt["kind"], "receipt_id": receipt["id"]},)

    def ack(self, caller: Caller, message_id: str, *, key: str) -> dict:
        return self.reply(caller, message_id, kind="ack", body="", key=key)

    def reply(self, caller: Caller, message_id: str, *, body: str, key: str, kind: str = "final",
              strict_active: bool = False, requires_user_review: bool = False,
              client_metadata: Mapping | None = None) -> dict:
        ReceiptKind(kind)
        if client_metadata is not None and not isinstance(client_metadata, Mapping):
            raise CommunicationError("reply client metadata must be an object")
        metadata = dict(client_metadata or {})
        canonical(metadata)
        if type(strict_active) is not bool or type(requires_user_review) is not bool:
            raise CommunicationError("reply policy flags must be boolean")
        if requires_user_review and kind != "final":
            raise CommunicationError("requires_user_review applies only to final replies")
        if kind != "ack":
            text(body, "reply body")
        if len(body) > 16000 or (kind == "ack" and body):
            raise CommunicationError("invalid receipt body")

        def work(now):
            message = self._message(caller, message_id)
            if caller.agent_id != message["target"]:
                raise AccessDenied("only the intended recipient may reply")
            delivery = self._delivery(message)
            receipts = self.repo.receipts(caller.workspace_id, message_id)
            if strict_active and (delivery["closed_at"] or self._expired(message, now)):
                raise Conflict("message is closed or expired")
            if (message.get("legacy_max_response_length") is not None
                    and len(body) > int(message["legacy_max_response_length"])):
                raise CommunicationError("reply exceeds legacy maximum response length")
            ack = next((r for r in receipts if r["kind"] == "ack"), None)
            terminal = next((r for r in receipts if r["kind"] in {"final", "reject"}), None)
            if kind == "ack" and ack:
                return ack, {}, ()
            if terminal:
                raise Conflict("a terminal reply already exists")
            if kind in {"ack", "progress"} and (delivery["closed_at"] or self._expired(message, now)):
                raise Conflict("message is closed or expired")
            receipt = self._new_receipt(message, delivery, kind, body, now,
                                        requires_user_review=requires_user_review)
            if metadata:
                receipt["client_metadata"] = metadata
            if kind in {"final", "reject"} and delivery["schedule"] == "pending":
                delivery["schedule"] = "done"  # A replied message must not later be activated.
            return receipt, {"receipts": [receipt], "deliveries": [delivery]}, self._receipt_notice(message, receipt)

        return self._operation(caller, "reply", key, {"message_id": message_id, "kind": kind,
            "body": body, "strict_active": strict_active,
            "requires_user_review": requires_user_review,
            "client_metadata": metadata}, work)

    def close(self, caller: Caller, message_id: str, *, key: str,
              strict_active: bool = False, reason: str = "closed",
              requires_user_review: bool | None = None) -> dict:
        if reason not in {"closed", "revoked", "expired", "blocked"}:
            raise CommunicationError("invalid close reason")
        if type(strict_active) is not bool or (requires_user_review is not None
                                                and type(requires_user_review) is not bool):
            raise CommunicationError("invalid close policy flags")
        def work(now):
            message = self._message(caller, message_id)
            if caller.agent_id != message["sender"]:
                raise AccessDenied("only sender can close the message")
            delivery = self._delivery(message)
            if strict_active and (delivery["closed_at"] or message.get("legacy_request_status") == "terminal"
                                  or any(r["kind"] in {"final", "reject"} for r in
                                         self.repo.receipts(caller.workspace_id, message_id))):
                raise Conflict("message is already terminal")
            delivery["closed_at"] = delivery["closed_at"] or now
            delivery["closed_reason"] = reason
            if requires_user_review is not None:
                delivery["requires_user_review"] = requires_user_review
            if delivery["schedule"] == "pending":
                delivery["schedule"] = "cancelled"
            return {"closed_at": delivery["closed_at"], "provider_cancelled": False}, {"deliveries": [delivery]}, (
                {"viewer": message["target"], "message_id": message_id, "kind": "closed"},)
        return self._operation(caller, "close", key, {"message_id": message_id,
            "strict_active": strict_active, "reason": reason,
            "requires_user_review": requires_user_review}, work)

    def inbox(self, caller: Caller, *, cursor: str | None = None, limit: int = 20,
              include_bodies: bool = False) -> dict:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise CommunicationError("limit must be 1..100")
        with self.repo.transaction(write=False):
            self.directory.require_member(caller)
            after, upper = 0, None
            if cursor:
                try:
                    decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                    version, database, workspace, viewer, after, upper = decoded
                    if (version != 1 or database != self.repo.database_id or workspace != caller.workspace_id
                            or viewer != caller.agent_id or type(after) is not int or after < 0
                            or (upper is not None and (type(upper) is not int or upper < after))):
                        raise ValueError()
                except (ValueError, TypeError, UnicodeError) as exc:
                    raise CommunicationError("invalid or differently scoped inbox cursor") from exc
            high = self.repo.high_water()
            if after > high or (upper is not None and upper > high):
                raise CommunicationError("cursor is ahead of this database")
            upper = high if upper is None else upper
            rows = self.repo.inbox(caller.workspace_id, caller.agent_id, after, upper, limit + 1)
            more = len(rows) > limit
            page = rows[:limit]
            items = []
            for row in page:
                try:
                    message = self._message(caller, row["message_id"])
                except AccessDenied:
                    continue
                receipt = (self.repo.get("receipts", caller.workspace_id, row["receipt_id"])
                           if row["receipt_id"] else None)
                item = {**row, "thread_id": message["thread_id"],
                        "from": receipt["author"] if receipt else message["sender"], "to": caller.agent_id}
                if include_bodies:
                    item["body"] = receipt["body"] if receipt else message["body"]
                items.append(item)
            end = page[-1]["sequence"] if more else upper
            encoded = base64.urlsafe_b64encode(canonical(
                [1, self.repo.database_id, caller.workspace_id, caller.agent_id, end, upper if more else None]
            ).encode()).decode()
            return {"items": items, "cursor": encoded, "upper": upper, "has_more": more}

    def observe(self, caller: Caller, message_id: str, *, condition: str, deadline: datetime, key: str) -> dict:
        if condition not in {"ack", "final"}:
            raise CommunicationError("wait condition must be ack or final")
        until = stamp(deadline)

        def work(now):
            message = self._message(caller, message_id)
            if caller.agent_id != message["sender"]:
                raise AccessDenied("only sender can create a reply observation")
            if until < now:
                raise CommunicationError("observation deadline is already past")
            observation = {"workspace_id": caller.workspace_id, "id": _id("observation"),
                           "message_id": message_id, "observer": caller.agent_id, "target": message["target"],
                           "condition": condition, "created_at": now, "deadline": until,
                           "cancelled_at": None, "cancelled_after_sequence": None}
            return observation, {"observations": [observation]}, ()
        return self._operation(caller, "observe", key, {"message_id": message_id, "condition": condition, "deadline": until}, work)

    def _observation(self, caller: Caller, identity: str) -> dict:
        self.directory.require_member(caller)
        observation = self.repo.get("observations", caller.workspace_id, identity)
        if not observation or observation["observer"] != caller.agent_id:
            raise AccessDenied("observation is not owned by caller")
        self._message(caller, observation["message_id"])
        return observation

    def cancel_observation(self, caller: Caller, identity: str, *, key: str) -> dict:
        def work(now):
            observation = self._observation(caller, identity)
            if observation["cancelled_at"] is None:
                observation["cancelled_at"] = now
                observation["cancelled_after_sequence"] = self.repo.high_water()
            return observation, {"observations": [observation]}, ()
        return self._operation(caller, "cancel_observation", key, {"id": identity}, work)

    def _observation_state(self, observation: dict, receipts: list[dict], now: str) -> dict:
        """Evaluate existing receipt/event ordering inside the caller's read UoW."""
        cutoff = min(observation["deadline"], observation["cancelled_at"] or observation["deadline"], now)
        kinds = {"ack", "final", "reject"} if observation["condition"] == "ack" else {"final", "reject"}
        receipt = next((r for r in receipts if r["kind"] in kinds and not r["late"]
                        and r["created_at"] <= cutoff and r["created_at"] < observation["deadline"]
                        and (observation["cancelled_after_sequence"] is None or self.repo.sequence(
                            "receipts", observation["workspace_id"], r["id"]
                        ) <= observation["cancelled_after_sequence"])), None)
        if receipt:
            state = "rejected" if receipt["kind"] == "reject" else "satisfied"
        elif observation["cancelled_at"] and observation["cancelled_at"] <= min(now, observation["deadline"]):
            state = "cancelled"
        elif now >= observation["deadline"]:
            state = "timed_out"
        else:
            state = "pending"
        return {"state": state, "receipt_id": receipt["id"] if receipt else None}

    def observation_status(self, caller: Caller, identity: str) -> dict:
        with self.repo.transaction(write=False):
            observation = self._observation(caller, identity)
            now = self._now()
            receipts = self.repo.receipts(caller.workspace_id, observation["message_id"])
            result = self._observation_state(observation, receipts, now)
            waiters = (self.coordination.waiters(caller.workspace_id, observation["message_id"], now)
                       if self.coordination is not None else [])
            return {"observation": observation, **result,
                    "active_waiter_verified": any(w["state"] == "active" for w in waiters)}

    def own_waits(self, caller: Caller, message_id: str, *, limit: int = 20) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise CommunicationError("wait status limit must be 1..100")
        with self.repo.transaction(write=False):
            self._message(caller,message_id)
            observations = self.repo.own_observations(caller.workspace_id,message_id,caller.agent_id,limit=limit)
        output = []
        for observation in observations:
            # Each read rechecks current permission. Never nest owned UoWs.
            status = self.observation_status(caller,observation["id"])
            output.append({"observationId":observation["id"],"messageId":message_id,
                "state":status["state"],"condition":observation["condition"],
                "deadline":observation["deadline"],"receiptId":status["receipt_id"]})
        return output

    # Executor-only surface. No calls below run a provider or create a worker.
    def due_targets(self, workspace_id: str, *, after: str = "", limit: int = 20,
                    target_agent_id: str | None = None) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise CommunicationError("target page limit must be 1..100")
        with self.repo.transaction(write=False):
            return self.repo.due_targets(workspace_id, self._now(), after=after, limit=limit,
                                         target_agent_id=target_agent_id)

    def activation_context(self, claim: Claim) -> tuple[dict, dict, dict]:
        with self.repo.transaction(write=False):
            _, attempt, message, delivery = self._owned(claim, self._now())
            return message, attempt, delivery

    def due(self, workspace_id: str, *, limit: int = 20,
            target_agent_id: str | None = None) -> list[dict]:
        """Read indexed candidate projections; each item still requires claim."""
        text(workspace_id, "workspace_id")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise CommunicationError("candidate limit must be 1..100")
        with self.repo.transaction(write=False):
            return self.repo.due(workspace_id, self._now(), limit=limit,
                                 target_agent_id=target_agent_id)

    def due_message(self, workspace_id: str, message_id: str) -> list[dict]:
        """Exact candidate lookup; avoids truncating a targeted dispatch behind a page."""
        with self.repo.transaction(write=False):
            message = self.repo.get("messages", workspace_id, message_id)
            if message is None:
                return []
            delivery = self._delivery(message)
            if (delivery["schedule"] == "pending"
                    and (not delivery.get("eligible_after") or delivery["eligible_after"] <= self._now())):
                return [delivery]
            return []

    def expired_slots(self, workspace_id: str, *, limit: int = 20) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise CommunicationError("expired slot limit must be 1..100")
        with self.repo.transaction(write=False):
            return self.repo.expired_slots(workspace_id, self._now(), limit=limit)

    def _expire_slot(self, workspace_id: str, slot: dict, now: str, owner: str) -> str:
        if slot["state"] != "active" or slot["lease_until"] > now:
            return "not_expired"
        old = self.repo.get("attempts", workspace_id, slot["attempt_id"])
        if old is None:
            raise CommunicationError("slot refers to a missing attempt")
        old_message = self.repo.get("messages", workspace_id, old["message_id"])
        if old_message is None:
            raise CommunicationError("attempt refers to a missing message")
        old_delivery = self._delivery(old_message)
        if old["phase"] == "claimed":
            old["phase"] = "expired_before_start"
            old_delivery.update(schedule=self._retry_schedule(old_message, old_delivery, now),
                                delivery="not_delivered", execution="not_started")
            slot["state"] = "free"
            outcome = "retryable_before_start"
        else:
            old["phase"] = "unknown"
            old_delivery.update(schedule="unknown", execution="unknown")
            if old_delivery["delivery"] != "accepted":
                old_delivery["delivery"] = "unknown"
            slot["state"] = "unknown"
            outcome = "reconcile_required"
        self.repo.append(workspace_id, owner, "lease_expired", now,
                         {"attempts": [old], "deliveries": [old_delivery], "slots": [slot]})
        return outcome

    def recover_expired_slots(self, workspace_id: str, *, owner: str,
                              limit: int = 20) -> dict:
        """Reconcile only ledger ownership; started provider calls stay unknown."""
        text(owner, "owner")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise CommunicationError("expired slot limit must be 1..100")
        candidates = self.expired_slots(workspace_id, limit=limit)
        outcomes = []
        for candidate in candidates:
            with self.repo.transaction():
                now = self._now()
                slot = self.repo.get("slots", workspace_id, candidate["id"])
                if slot is not None:
                    outcomes.append(self._expire_slot(workspace_id, slot, now, owner))
        return {"examined": len(candidates), "reconciled": sum(x != "not_expired" for x in outcomes),
                "retryable_before_start": outcomes.count("retryable_before_start"),
                "reconcile_required": outcomes.count("reconcile_required")}

    def claim(self, workspace_id: str, message_id: str, *, owner: str,
              lease_seconds: int = 60, provider_timeout_seconds: int = 120,
              consumer: dict | None = None, activation_nonce: str | None = None) -> dict:
        text(owner, "owner")
        if type(lease_seconds) is not int or lease_seconds <= 0 or type(provider_timeout_seconds) is not int or provider_timeout_seconds <= 0:
            raise CommunicationError("lease and provider timeout must be positive seconds")
        with self.repo.transaction():
            now = self._now()
            if consumer is not None:
                if self.coordination is None or consumer.get("workspace_id") != workspace_id:
                    raise StaleAttempt("consumer scope differs from this workspace")
                self.coordination.require_owner(consumer, now)
            message = self.repo.get("messages", workspace_id, message_id)
            if message is None:
                raise AccessDenied("message is not in this workspace")
            delivery = self._delivery(message)
            if delivery["binding"] is None:
                return {"outcome": "not_pending"}
            slot = self.repo.get("slots", workspace_id, delivery["session_key"])
            if slot and slot["state"] == "active" and slot["lease_until"] <= now:
                self._expire_slot(workspace_id, slot, now, owner)
                delivery = self._delivery(message)
            binding = self._activation_binding(message, delivery)
            if binding.session_key != delivery["session_key"]:
                raise Conflict("delivery session binding changed")
            if slot and slot["state"] != "free":
                return {"outcome": "reconcile_required" if slot["state"] == "unknown" else "busy"}
            if self._expired(message, now) or delivery["closed_at"]:
                return {"outcome": "closed_or_expired"}
            if any(r["kind"] in {"final", "reject"} for r in self.repo.receipts(workspace_id, message_id)):
                return {"outcome": "already_replied"}
            if delivery["schedule"] != "pending":
                return {"outcome": "not_pending"}
            if delivery.get("eligible_after") and delivery["eligible_after"] > now:
                return {"outcome": "not_due"}
            if delivery["attempt_count"] >= delivery["max_attempts"]:
                delivery.update(schedule="failed", failure="attempt_limit")
                self.repo.append(workspace_id, owner, "attempt_limit", now, {"deliveries": [delivery]})
                return {"outcome": "attempt_limit"}
            fence = (slot["fence"] if slot else 0) + 1
            claim = Claim(workspace_id, message_id, binding.agent_id, binding.session_key, _id("attempt"), fence, owner)
            attempt = {**claim.to_dict(), "id": claim.attempt_id, "phase": "claimed", "created_at": now,
                       "binding": binding.to_dict(), "provider_timeout_seconds": provider_timeout_seconds,
                       "provider_deadline": None, "evidence": None, "consumer": consumer}
            slot = {"workspace_id": workspace_id, "id": binding.session_key, "attempt_id": claim.attempt_id,
                    "fence": fence, "state": "active",
                    "lease_until": stamp(datetime.fromisoformat(now) + timedelta(seconds=lease_seconds))}
            delivery.update(schedule="leased", attempt_count=delivery["attempt_count"] + 1)
            self.repo.append(workspace_id, owner, "claimed", now,
                             {"attempts": [attempt], "slots": [slot], "deliveries": [delivery]})
            if activation_nonce is not None:
                if consumer is None or self.coordination is None:
                    raise CommunicationError("activation registration requires a consumer")
                self.coordination.register_activation(consumer, claim.to_dict(), nonce=activation_nonce, now=now)
            return {"outcome": "claimed", "claim": claim.to_dict()}

    def attempt_status(self, claim: Claim) -> dict:
        """Internal diagnostic for this exact attempt, including after terminal release."""
        with self.repo.transaction(write=False):
            attempt = self.repo.get("attempts", claim.workspace_id, claim.attempt_id)
            if not attempt or any(attempt.get(k) != v for k, v in claim.to_dict().items()):
                raise StaleAttempt("attempt identity differs")
            slot = self.repo.get("slots", claim.workspace_id, claim.session_key)
            return {"phase": attempt["phase"], "provider_deadline": attempt["provider_deadline"],
                    "lease_until": slot["lease_until"] if slot and slot["attempt_id"] == claim.attempt_id else None}

    def _owned(self, claim: Claim, now: str, *, reconcile: bool = False) -> tuple[dict, dict, dict, dict]:
        slot = self.repo.get("slots", claim.workspace_id, claim.session_key)
        attempt = self.repo.get("attempts", claim.workspace_id, claim.attempt_id)
        if (not slot or not attempt or slot["attempt_id"] != claim.attempt_id or slot["fence"] != claim.fence
                or any(attempt[k] != v for k, v in claim.to_dict().items())
                or (not reconcile and (slot["state"] != "active" or slot["lease_until"] <= now))
                or (reconcile and slot["state"] != "unknown")):
            raise StaleAttempt("attempt ownership/fence is stale")
        message = self.repo.get("messages", claim.workspace_id, claim.message_id)
        if not reconcile and attempt.get("consumer") is not None:
            if self.coordination is None:
                raise StaleAttempt("consumer coordinator is unavailable")
            self.coordination.require_owner(attempt["consumer"], now, allow_draining=True)
        return slot, attempt, message, self._delivery(message)

    def mark_started(self, claim: Claim) -> None:
        with self.repo.transaction():
            now = self._now()
            slot, attempt, message, delivery = self._owned(claim, now)
            if attempt["phase"] != "claimed":
                raise Conflict("attempt has already started")
            self._activation_binding(message, delivery)
            if delivery["closed_at"] or self._expired(message, now) or any(
                r["kind"] in {"final", "reject"} for r in self.repo.receipts(claim.workspace_id, claim.message_id)
            ):
                raise Conflict("message no longer permits activation")
            attempt.update(phase="started", provider_deadline=stamp(
                datetime.fromisoformat(now) + timedelta(seconds=attempt["provider_timeout_seconds"])))
            # This commits intent BEFORE external I/O. It does not prove that a
            # process or model has actually started; only adapter evidence can.
            delivery["execution"] = "unknown"
            self.repo.append(claim.workspace_id, claim.owner, "started", now,
                             {"attempts": [attempt], "deliveries": [delivery]})

    def release(self, claim: Claim) -> None:
        """Release before start is retryable. Release after start needs reconciliation."""
        with self.repo.transaction():
            now = self._now()
            slot, attempt, message, delivery = self._owned(claim, now)
            safe = attempt["phase"] == "claimed"
            slot["state"] = "free" if safe else "unknown"
            attempt["phase"] = "released_before_start" if safe else "unknown"
            delivery.update(schedule=self._retry_schedule(message, delivery, now) if safe else "unknown",
                            execution="not_started" if safe else "unknown")
            if not safe and delivery["delivery"] != "accepted":
                delivery["delivery"] = "unknown"
            self.repo.append(claim.workspace_id, claim.owner, "released", now,
                             {"attempts": [attempt], "slots": [slot], "deliveries": [delivery]})

    def renew_lease(self, claim: Claim, *, lease_seconds: int) -> dict:
        """Extend only a currently owned, unexpired native-session lease.

        The caller must remain alive and invoke this separately from provider I/O.
        A stale process cannot recover ownership by renewing an expired lease.
        """
        if type(lease_seconds) is not int or lease_seconds <= 0:
            raise CommunicationError("lease_seconds must be positive")
        with self.repo.transaction():
            now = self._now()
            slot, attempt, _, _ = self._owned(claim, now)
            if attempt["phase"] not in {"claimed", "started", "running"}:
                raise StaleAttempt("attempt is no longer renewable")
            extension = stamp(datetime.fromisoformat(now) + timedelta(seconds=lease_seconds))
            slot["lease_until"] = max(slot["lease_until"], extension)
            attempt["renewed_at"] = now
            self.repo.append(claim.workspace_id, claim.owner, "lease_renewed", now,
                             {"slots": [slot], "attempts": [attempt]})
            return {"lease_until": slot["lease_until"], "claim": claim.to_dict()}

    def complete(self, claim: Claim, evidence: ProviderEvidence) -> dict:
        return self._record_evidence(claim, evidence, reconcile=False)

    def reconcile(self, claim: Claim, evidence: ProviderEvidence) -> dict:
        """Explicit executor reconciliation with new stopped evidence; no automatic retry."""
        if not evidence.stopped or evidence.outcome in {"running", "unknown"}:
            raise CommunicationError("reconciliation requires stopped lifecycle evidence")
        return self._record_evidence(claim, evidence, reconcile=True)

    def _record_evidence(self, claim: Claim, evidence: ProviderEvidence, *, reconcile: bool) -> dict:
        with self.repo.transaction():
            now = self._now()
            slot, attempt, message, delivery = self._owned(claim, now, reconcile=reconcile)
            binding = attempt["binding"]
            if (evidence.provider != binding["provider"] or evidence.native_session_id != binding["native_session_id"]
                    or evidence.generation != binding["generation"]):
                raise Conflict("provider evidence does not match the bound native session/generation")
            if attempt["phase"] == "claimed":
                raise Conflict("mark_started must commit before performing provider I/O")
            if evidence.outcome == "not_delivered" and delivery["delivery"] == "accepted":
                raise Conflict("not_delivered contradicts previously recorded acceptance")
            if evidence.final is not None and delivery["capture"] != "provider_final_capture":
                raise AccessDenied("provider final capture is not enabled for this delivery")
            attempt.update(phase=evidence.outcome, evidence=asdict(evidence))
            if evidence.accepted:
                delivery["delivery"] = "accepted"
            outcome = evidence.outcome
            if outcome == "running":
                delivery["execution"] = "running"
            elif outcome == "unknown":
                delivery.update(schedule="unknown", execution="unknown")
                if delivery["delivery"] != "accepted":
                    delivery["delivery"] = "unknown"
                slot["state"] = "unknown"
            else:
                slot["state"] = "free"
                delivery["execution"] = {"finished": "finished", "failed": "failed", "not_delivered": "not_started"}[outcome]
                if outcome == "not_delivered":
                    delivery.update(delivery="not_delivered", schedule=self._retry_schedule(message, delivery, now))
                elif delivery["delivery"] == "accepted":
                    delivery["schedule"] = "done"
                else:
                    delivery.update(delivery="unknown", schedule="unknown")
            changes = {"attempts": [attempt], "slots": [slot], "deliveries": [delivery]}
            notices = ()
            if evidence.final is not None:
                terminals = [r for r in self.repo.receipts(claim.workspace_id, claim.message_id) if r["kind"] in {"final", "reject"}]
                if terminals:
                    # Explicit reply wins; retain captured text only as execution evidence.
                    attempt["capture_result"] = "existing_reply_preserved"
                else:
                    receipt = self._new_receipt(message, delivery, "final", evidence.final, now,
                                                source="provider_final_capture", attempt_id=claim.attempt_id,
                                                requires_user_review=evidence.requires_user_review)
                    changes["receipts"] = [receipt]
                    notices = self._receipt_notice(message, receipt)
                    attempt["capture_result"] = "recorded"
            self.repo.append(claim.workspace_id, claim.owner, "reconciled" if reconcile else "provider_evidence", now, changes, notices)
            return {"delivery": delivery, "attempt": attempt}
