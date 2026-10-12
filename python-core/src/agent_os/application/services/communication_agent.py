"""Bound Agent communication use cases, independent of transports and assembly.

Factories open request-owned services. Production composition must supply the
same legacy send policy used by the CLI, never a policy-free core instance.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import math
from typing import Callable

from agent_os.application.services.communication_wait import CommunicationWait
from agent_os.application.services.communication_envelope import BOUNDARY, CommunicationEnvelope, explain_compact
from agent_os.application.services.communication_short_refs import ShortReferences, facts_from_handle, logical_identity
from agent_os.domain.entities.communication import AccessDenied, Caller, CommunicationError, canonical


NATIVE_FIELDS = {"codex": "codexSessionId", "claude": "claudeSessionUuid",
                 "hermes": "hermesSessionId", "deepseek_harness": "deepseekHarnessSessionId"}


def select(row, names):
    return {name: row[name] for name in names if name in row}


def key_text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise CommunicationError("key must be non-empty and at most 256 characters")
    return value


@dataclass(frozen=True)
class AgentBinding:
    caller: Caller
    alias: str
    handle_id: str
    provider: str
    native_id: str
    generation: str | None = None
    native_identity: str | None = None


def registered_source(service, caller, alias):
    service.directory.require_member(caller)
    result = service.directory.reader.endpoint(caller.workspace_id, alias)
    endpoint, handle = result["agentEndpoint"], result.get("providerHandle")
    if (endpoint["state"] != "active" or endpoint["agentId"] != caller.agent_id
            or endpoint["direction"] not in {"send_only", "send_receive"}
            or not handle or handle["state"] != "active" or handle["agentId"] != caller.agent_id
            or endpoint["providerHandleId"] != handle["handleId"]):
        raise AccessDenied("bound endpoint is not an active sender owned by caller")
    identity = logical_identity(facts_from_handle(handle, endpoint["provider"]))
    return AgentBinding(caller, alias, handle["handleId"], endpoint["provider"],
                        handle[NATIVE_FIELDS[endpoint["provider"]]],
                        handle.get("metadata", {}).get("runtimeBinding", {}).get("generationId"),
                        identity["key"] if identity else None)


class AgentCommunication:
    """Small application surface sharing Core transactions and CLI send policy."""

    def __init__(self, binding: AgentBinding, open_service: Callable, *, backend_policy: Callable,
                 compact_messages: bool = False):
        if type(compact_messages) is not bool:
            raise CommunicationError("compact_messages must be a trusted boolean option")
        self.binding, self.open_service, self.backend_policy = binding, open_service, backend_policy
        self.compact_messages = compact_messages

    def _message_id(self, service, message_id, message_ref, *, required=True):
        if message_id is not None and message_ref is not None:
            raise CommunicationError("message_id and message_ref are mutually exclusive")
        if message_ref is not None:
            return ShortReferences(service).resolve(self.binding.caller, "message", message_ref)
        if message_id is None and required:
            raise CommunicationError("message_id or message_ref is required")
        if message_id is not None and (not isinstance(message_id, str) or not message_id.strip()):
            raise CommunicationError("message_id must be a non-empty string")
        return message_id

    def _session_ref(self, service, alias):
        short = ShortReferences(service)
        if not short.enabled(self.binding.caller.workspace_id):
            return None
        result = service.directory.reader.endpoint(self.binding.caller.workspace_id, alias)
        handle = result.get("providerHandle")
        if not handle:
            return None
        identity = logical_identity(facts_from_handle(handle, result["agentEndpoint"]["provider"]))
        row = service.repo.short_ref(self.binding.caller.workspace_id, "session", object_id=identity["key"]) if identity else None
        return row["code"] if row else None

    def _compact(self, service, message_id, *, include_body=False):
        result = CommunicationEnvelope(service).summary(self.binding.caller, message_id, include_body=include_body)
        if not result.get("enabled"):
            return result
        # Header fields already encode route, authority and waiting facts.
        # Avoid repeating UUIDs and the expanded internal facts by default.
        return {**select(result, ("header", "messageRef", "threadRef", "fromAlias", "toAlias",
                                  "sampledAt", "body")), "boundary": BOUNDARY}

    def explain(self, *, version="B1"):
        with self.service():
            return explain_compact(version)

    def resolve(self, *, kind, ref):
        with self.service() as service:
            identity = ShortReferences(service).resolve(self.binding.caller, kind, ref)
            return {"kind": kind, "ref": ref, "id": identity}

    def session(self, *, ref, include_native=False):
        with self.service() as service:
            return ShortReferences(service).lookup_session(self.binding.caller, ref, include_native=include_native)

    def compact(self, *, message_id=None, message_ref=None, include_body=False):
        with self.service() as service:
            identity = self._message_id(service, message_id, message_ref)
            return self._compact(service, identity, include_body=include_body)

    @contextmanager
    def service(self):
        with self.open_service() as service:
            if registered_source(service, self.binding.caller, self.binding.alias) != self.binding:
                raise AccessDenied("bound endpoint changed; restart with an explicitly verified binding")
            yield service

    def self_info(self):
        with self.service() as service:
            result = {"workspaceId": self.binding.caller.workspace_id,
                    "agentId": self.binding.caller.agent_id, "alias": self.binding.alias,
                    "provider": self.binding.provider, "consumer": self.consumer(service),
                    "delivery": ["store", "queued"], "wait": ["ack", "final"],
                    "authority": "agent"}
            if self.compact_messages:
                result["sessionRef"] = self._session_ref(service, self.binding.alias)
                result["compactEnabled"] = ShortReferences(service).enabled(self.binding.caller.workspace_id)
                if result["compactEnabled"]:
                    result.pop("agentId")
            return result

    def consumer(self, service):
        return select(service.coordination.consumer_status(self.binding.caller.workspace_id, service._now()),
                      ("state", "sampledAt", "leaseUntil"))

    def peers(self, *, after="", limit=20):
        if type(limit) is not int or not 1 <= limit <= 100 or not isinstance(after, str):
            raise CommunicationError("peers limit must be 1..100 and after must be an alias")
        with self.service() as service:
            rows = sorted(service.directory.reader.endpoints(self.binding.caller.workspace_id),
                          key=lambda row: row["alias"])
            peers = []
            for row in rows:
                if row["alias"] <= after or row["agentId"] == self.binding.caller.agent_id:
                    continue
                try:
                    binding = service.directory.resolve(self.binding.caller.workspace_id, row["alias"])
                except (AccessDenied, ValueError):
                    continue
                peer = {"agentId": binding.agent_id, "alias": binding.alias,
                        "provider": binding.provider, "registration": "active"}
                if self.compact_messages:
                    peer["sessionRef"] = self._session_ref(service, binding.alias)
                    if peer["sessionRef"]:
                        peer.pop("agentId")
                peers.append(peer)
                if len(peers) > limit:
                    break
            more = len(peers) > limit
            return {"peers": peers[:limit], "nextAfter": peers[limit-1]["alias"] if more else None,
                    "hasMore": more, "sampledAt": service._now()}

    def send(self, *, to=None, body, key, delivery="queued", expectation="none", thread_id=None,
             reply_to=None, refs=(), grant_id=None, target_ref=None, thread_ref=None, reply_ref=None):
        key_text(key)
        if delivery not in {"store", "queued"} or expectation not in {"none", "ack", "final"}:
            raise CommunicationError("invalid delivery or expectation")
        if not isinstance(refs, (tuple, list)) or len(refs) > 20:
            raise CommunicationError("refs must contain at most 20 references")
        with self.service() as service:
            if service.send_compatibility is None:
                raise CommunicationError("production send compatibility is required")
            if (to is None) == (target_ref is None):
                raise CommunicationError("exactly one of to and target_ref is required")
            if thread_id is not None and thread_ref is not None:
                raise CommunicationError("thread_id and thread_ref are mutually exclusive")
            if reply_to is not None and reply_ref is not None:
                raise CommunicationError("reply_to and reply_ref are mutually exclusive")
            short = ShortReferences(service)
            if target_ref is not None:
                to = short.target_alias(self.binding.caller, target_ref)
            if thread_ref is not None:
                thread_id = short.resolve(self.binding.caller, "thread", thread_ref)
            if reply_ref is not None:
                reply_to = short.resolve(self.binding.caller, "message", reply_ref)
            target = service.directory.resolve(self.binding.caller.workspace_id, to)
            backend, capture = self.backend_policy(target.provider)
            if delivery == "store":
                backend, capture = None, "explicit_only"
            stable = sha256(canonical([self.binding.caller.workspace_id,
                                      self.binding.caller.agent_id, key]).encode()).hexdigest()
            request_id = "agent-exchange-request-mcp-" + stable
            dispatch_id = "agent-dispatch-mcp-" + stable if delivery == "queued" else None
            # Resolve the parent through the same ledger; the compatibility policy
            # still owns depth, count, follow-up, thread budget and review limits.
            parent = service.get(self.binding.caller, reply_to) if reply_to else None
            context = {"request_id": request_id, "dispatch_id": dispatch_id,
                       "request_kind": "sync", "parent_request_id": parent.get("legacy_request_id") if parent else None,
                       "thread_id": thread_id, "provider_backend": backend,
                       "capture_policy": capture, "metadata": {"communicationEntry": "bound_agent.v1"}}
            if parent and not context["parent_request_id"]:
                raise CommunicationError("reply_to has no compatible parent request mapping")
            message = service.send(self.binding.caller, target_alias=to, body=body, key=key,
                refs=tuple(refs), thread_id=thread_id, reply_to=reply_to, expectation=expectation,
                wake="none" if delivery == "store" else "when_available", capture=capture,
                source_alias=self.binding.alias, source_handle_id=self.binding.handle_id,
                target_handle_id=target.handle_id,
                reply_policy="message_only" if expectation == "none" else "source_handle_required",
                linked_delegated_wake_grant_id=grant_id, legacy_context=context,
                require_consumer=delivery == "queued", delivery_path=delivery,
                target_session_ref=target_ref)
            facts = service.status(self.binding.caller, message["id"])
            result = {"messageId": message["id"], "threadId": message["thread_id"],
                    "deliveryId": facts["delivery"]["id"],
                    "from": message["sender"], "to": message["target"], "authority": "agent",
                    "delivery": delivery, "expectation": expectation, "capture": facts["delivery"]["capture"],
                    "schedule": facts["delivery"]["schedule"], "deliveryState": facts["delivery"]["delivery"],
                    "executionState": facts["delivery"]["execution"], "consumer": self.consumer(service)}
            if self.compact_messages:
                summary = self._compact(service, message["id"])
                if summary.get("messageRef"):
                    result = {**summary, **select(result, ("deliveryState", "executionState", "consumer"))}
            return result

    def inbox(self, *, cursor=None, limit=20, include_bodies=False, include_full=False):
        with self.service() as service:
            result = service.inbox(self.binding.caller, cursor=cursor, limit=limit, include_bodies=include_bodies)
            if self.compact_messages and not include_full:
                items = []
                for item in result["items"]:
                    summary = self._compact(service, item["message_id"])
                    if summary.get("messageRef"):
                        visible = select(item, ("kind", "sequence", "created_at", "body", "receipt_kind",
                                                "source", "late", "requires_user_review"))
                        if item["kind"] == "message":
                            item = {**summary, **visible}
                        else:
                            # Request header must never masquerade as a receipt.
                            item = {**select(summary, ("messageRef", "threadRef")), **visible,
                                    "fromAlias": summary["toAlias"], "toAlias": summary["fromAlias"]}
                    items.append(item)
                result["items"] = items
            return result

    def receipt(self, *, message_id=None, message_ref=None, key, kind="ack", body=""):
        key_text(key)
        with self.service() as service:
            message_id = self._message_id(service, message_id, message_ref)
            row = service.reply(self.binding.caller, message_id, key=key, kind=kind, body=body)
            if self.compact_messages:
                summary = self._compact(service, message_id)
                if summary.get("messageRef"):
                    return {"messageRef": summary["messageRef"], **select(row,
                        ("kind", "created_at", "source", "late", "requires_user_review"))}
            return select(row, ("id", "message_id", "kind", "created_at", "source", "late", "requires_user_review"))

    def status(self, *, message_id=None, message_ref=None, observation_id=None, include_bodies=False,
               receipt_limit=20, include_full=False):
        if type(receipt_limit) is not int or not 1 <= receipt_limit <= 20:
            raise CommunicationError("receipt_limit must be 1..20")
        with self.service() as service:
            caller = self.binding.caller
            message_id = self._message_id(service, message_id, message_ref, required=False)
            result = {"consumer": self.consumer(service), "sampledAt": service._now()}
            if observation_id:
                observed = service.observation_status(caller, observation_id)
                observation = observed["observation"]
                if message_id and message_id != observation["message_id"]:
                    raise CommunicationError("observation/message mismatch")
                message_id = observation["message_id"]
                result["observation"] = {**select(observation, ("id", "message_id", "condition", "deadline")),
                                         "state": observed["state"], "receiptId": observed["receipt_id"]}
            if message_id:
                facts = service.status(caller, message_id)
                result.update(message=select(facts["message"], ("id", "thread_id", "sender", "target", "origin",
                    "created_at", "expires_at", "expectation", "reply_to")),
                    delivery=select(facts["delivery"], ("id", "schedule", "wake", "capture", "delivery", "execution",
                                                     "attempt_count", "closed_at", "closed_reason")),
                    reply=facts["reply"], acknowledged=facts["acknowledged"], expired=facts["expired"],
                    ownWaits=service.own_waits(caller, message_id, limit=20))
                # Status is bounded, including repeated progress receipts. Inbox
                # remains the authoritative incremental route for older receipts.
                result["receipts"] = [select(r, ("id", "kind", "source", "created_at", "late", "requires_user_review")
                    + (("body",) if include_bodies else ())) for r in facts["receipts"][-receipt_limit:]]
                result["receiptsHasMore"] = len(facts["receipts"]) > receipt_limit
                if facts["message"]["sender"] == caller.agent_id:
                    result["verifiedWaiters"] = facts["waiters"][-20:]
                    result["activeWaiterVerified"] = facts["active_waiter_verified"]
                if include_bodies:
                    result["message"]["body"] = facts["message"]["body"]
                if self.compact_messages and not include_full:
                    summary = self._compact(service, message_id, include_body=include_bodies)
                    if summary.get("messageRef"):
                        result = {**summary, **select(result, ("consumer", "reply", "acknowledged", "expired",
                            "receiptsHasMore", "ownWaits")),
                            "deliveryState": facts["delivery"]["delivery"],
                            "executionState": facts["delivery"]["execution"],
                            "receipts": [select(r, ("kind", "source", "created_at", "late", "requires_user_review")
                                + (("body",) if include_bodies else ())) for r in facts["receipts"][-receipt_limit:] ],
                            **({"observation": select(result["observation"], ("id", "condition", "deadline", "state"))}
                               if "observation" in result else {})}
            return result

    def wait(self, *, message_id=None, message_ref=None, condition="ack", timeout=15, include_bodies=False, cancelled=None):
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise CommunicationError("timeout must be finite and within 0..120 seconds")
        with self.service() as service:
            message_id = self._message_id(service, message_id, message_ref)
            result = CommunicationWait(service, service.coordination).wait(self.binding.caller,
                message_id, condition=condition, timeout=timeout, include_bodies=include_bodies, cancelled=cancelled)
            result["consumer"] = select(result["consumer"], ("state", "sampledAt", "leaseUntil"))
            result["recheck"] = "status(message_id) or status(observation_id)"
            if self.compact_messages:
                summary = self._compact(service, message_id)
                if summary.get("messageRef"):
                    result = {**summary, **select(result, ("state", "condition", "deadline", "observationId",
                                                          "consumer", "reply", "cancelled")),
                              "recheck": "status(message_ref) or status(observation_id)"}
            return result

    def cancel_wait(self, *, observation_id, key):
        key_text(key)
        with self.service() as service:
            service.cancel_observation(self.binding.caller, observation_id, key=key)
            status = service.observation_status(self.binding.caller, observation_id)
            return {"observationId": observation_id, "messageId": status["observation"]["message_id"],
                    "state": status["state"], "receiptId": status["receipt_id"], "executionCancelled": False}
