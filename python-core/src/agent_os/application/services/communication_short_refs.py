"""Optional stable representations of communication facts, not a second ledger.

Allocation is confined to explicit administration or a communication-owned
write. Queries never allocate or change registration/authorization state.
"""
from __future__ import annotations

from datetime import datetime
import ntpath
import posixpath
import re

from agent_os.domain.entities.communication import AccessDenied, Caller, CommunicationError, Conflict, canonical, stamp


PREFIXES = {"codex": "cx", "claude": "cl", "hermes": "he", "deepseek_harness": "ds"}
NATIVE_FIELDS = {"codex": "codexSessionId", "claude": "claudeSessionUuid",
                 "hermes": "hermesSessionId", "deepseek_harness": "deepseekHarnessSessionId"}
CODE = re.compile(r"(?:P|M|T|cx|cl|he|ds)[1-9][0-9]{0,14}\Z")
MAX_NUMBER = 999999999999999


def canonical_scope(value):
    """Normalize stored absolute namespaces without filesystem or env access."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if ntpath.isabs(value) and (ntpath.splitdrive(value)[0] or value.startswith("\\\\")):
        return ntpath.normcase(ntpath.normpath(value))
    if posixpath.isabs(value):
        return posixpath.normpath(value)
    return None


def logical_identity(facts):
    """Responsibility and native continuity are separate, both are in the key."""
    if not isinstance(facts, dict):
        return None
    agent, provider, native = (facts.get(name) for name in ("agent_id", "provider", "native_session_id"))
    if (provider not in PREFIXES or not isinstance(agent, str) or not agent.strip()
            or not isinstance(native, str) or not native.strip()):
        return None
    identity = {"agent_id": agent.strip(), "provider": provider,
                "native_session_id": native.strip(), "native_scope": canonical_scope(facts.get("native_scope"))}
    identity["key"] = canonical([identity["agent_id"], provider, identity["native_session_id"], identity["native_scope"]])
    return identity


def facts_from_handle(handle, provider):
    metadata = handle.get("metadata") or {}
    identity = metadata.get(provider + "SessionIdentity") or {}
    runtime = metadata.get("runtimeBinding") or {}
    return {"agent_id": handle.get("agentId"), "provider": provider,
            "native_session_id": handle.get(NATIVE_FIELDS[provider]),
            "native_scope": runtime.get("sessionRoot") if provider == "deepseek_harness" else identity.get("runtimeHome"),
            "handle_id": handle.get("handleId"), "generation": runtime.get("generationId")}


class ShortReferences:
    def __init__(self, service):
        self.service, self.repo, self.directory = service, service.repo, service.directory

    def enabled(self, workspace_id):
        return bool(self.repo.short_extension() and self.repo.get("ref_modes", workspace_id, workspace_id))

    def _require(self, workspace_id):
        if not self.enabled(workspace_id):
            raise CommunicationError("short references require explicit workspace initialization")

    def _new_ref(self, workspace_id, kind, object_id, prefix, now, pending, *, provenance, identity=None):
        prior = self.repo.short_ref(workspace_id, kind, object_id=object_id)
        if prior:
            return prior
        prior = next((row for row in pending if row["workspace_id"] == workspace_id
                      and row["kind"] == kind and row["object_id"] == object_id), None)
        if prior:
            return prior
        number = self.repo.next_short_number(workspace_id, kind, prefix)
        matching = [row["number"] for row in pending if row["kind"] == kind
                    and row["code"].startswith(prefix)
                    and (kind == "workspace" or row["workspace_id"] == workspace_id)]
        number = max([number, *(value + 1 for value in matching)])
        if number > MAX_NUMBER:
            raise Conflict("short reference namespace exhausted")
        result = {"workspace_id": workspace_id, "id": canonical([kind, object_id]),
                  "kind": kind, "code": prefix + str(number), "object_id": object_id,
                  "number": number, "allocated_at": now, "provenance": provenance}
        if identity:
            result["identity"] = identity
        pending.append(result)
        return result

    def _sync_workspaces(self, actor, now):
        for row in self.directory.reader.workspace_inventory():
            workspace_id = row["workspace_id"]
            if self.repo.short_ref(workspace_id, "workspace", object_id=workspace_id):
                continue
            pending = []
            self._new_ref(workspace_id, "workspace", workspace_id, "P", now, pending,
                          provenance={"order": "registration_event" if row.get("sequence") else "deterministic_fallback",
                                      "sequence": row.get("sequence")})
            self.repo.append(workspace_id, actor, "short_workspace_registered", now, {"short_refs": pending})

    def sync_registration_history(self, workspace_id, actor=None, now=None):
        """Caller already owns a write UoW; never nest or commit one here."""
        self._require(workspace_id)
        self.repo.require_short_write()
        actor, now = actor or "short-reference-sync", now or self.service._now()
        self._sync_workspaces(actor, now)
        marker = self.repo.get("ref_modes", workspace_id, workspace_id)
        watermark = marker.get("registration_high_water", 0)
        rows = self.directory.reader.registration_history(workspace_id, after=watermark)
        trusted = sorted((row for row in rows if row.get("action") == "registered"
                          and type(row.get("sequence")) is int and row["sequence"] > 0),
                         key=lambda row: (row["sequence"], row.get("handle_id") or ""))
        pending = []
        for row in trusted:
            identity = logical_identity(row)
            # State changes retain tombstones; only trusted registration facts
            # allocate new identities. Legacy incomplete facts remain unknown.
            if identity is None:
                continue
            self._new_ref(workspace_id, "session", identity["key"], PREFIXES[identity["provider"]],
                          now, pending, identity=identity,
                          provenance={"order": "registration_event", "sequence": row["sequence"]})
        # Older snapshots may lack their original registration action. Current
        # exact handles and retained snapshots are sufficient for identity, but
        # are not evidence of true registration order. Allocate deterministically
        # after the trusted event group and record that distinction permanently.
        fallback = [identity for row in rows if (identity := logical_identity(row)) is not None]
        for endpoint in self.directory.reader.endpoints(workspace_id):
            result = self.directory.reader.endpoint(workspace_id, endpoint["alias"])
            handle = result.get("providerHandle")
            if handle and endpoint.get("provider") in PREFIXES:
                identity = logical_identity(facts_from_handle(handle, endpoint["provider"]))
                if identity:
                    fallback.append(identity)
        for identity in sorted({row["key"]: row for row in fallback}.values(), key=lambda row: row["key"]):
            self._new_ref(workspace_id, "session", identity["key"], PREFIXES[identity["provider"]],
                          now, pending, identity=identity, provenance={"order": "deterministic_identity_fallback"})
        high = max([watermark, *(row["sequence"] for row in rows
                                if type(row.get("sequence")) is int and row["sequence"] > 0)])
        if pending or high != watermark:
            marker = {**marker, "registration_high_water": high}
            self.repo.append(workspace_id, actor, "short_registration_sync", now,
                             {"short_refs": pending, "ref_modes": [marker]})
        return {"created": len(pending), "registrationHighWater": high}

    def initialize(self, workspace_id, *, operator, stopped_writers_confirmed, backup_path=None):
        """Explicit optional upgrade/backfill; a disk CLI should supply a backup."""
        if stopped_writers_confirmed is not True or not isinstance(operator, str) or not operator.strip():
            raise CommunicationError("short reference upgrade requires operator and stopped-writer confirmation")
        inventory = self.directory.reader.workspace_inventory()
        if not any(row["workspace_id"] == workspace_id and row["status"] == "active" for row in inventory):
            raise AccessDenied("short reference upgrade requires an active existing workspace")
        if self.enabled(workspace_id):
            return {"workspaceId": workspace_id, "created": False, "schemaVersion": 1, "backup": None}
        backup = self.repo.short_reference_backup(backup_path) if backup_path else None
        now = self.service._now()
        with self.repo.transaction():
            self.repo.initialize_short_extension()
            # A parallel explicit initializer may have completed before this
            # connection acquired the writer lock. It must not duplicate facts.
            if self.enabled(workspace_id):
                return {"workspaceId": workspace_id, "created": False, "schemaVersion": 1, "backup": backup}
            marker = {"workspace_id": workspace_id, "id": workspace_id,
                      "enabled_at": now, "registration_high_water": 0, "schema_version": 1}
            self.repo.append(workspace_id, operator, "short_references_enabled", now, {"ref_modes": [marker]})
            self.sync_registration_history(workspace_id, operator, now)
            threads = self.repo.workspace_items("threads", workspace_id)
            messages = self.repo.workspace_items("messages", workspace_id)
            pending = []
            for thread in sorted(threads, key=lambda row: (self.repo.creation_sequence("threads", workspace_id, row["id"]), row["id"])):
                sequence = self.repo.creation_sequence("threads", workspace_id, thread["id"])
                self._new_ref(workspace_id, "thread", thread["id"], "T", now, pending,
                              provenance={"order": "deterministic_import_fallback" if thread.get("historical") else "communication_event",
                                          "sequence": sequence})
            if pending:
                self.repo.append(workspace_id, operator, "short_thread_backfill", now, {"short_refs": pending})
            for message in sorted(messages, key=lambda row: (self.repo.creation_sequence("messages", workspace_id, row["id"]),
                                                             row.get("legacy_request_sequence", 0), row["id"])):
                delivery = self.service._delivery(message)
                changes = self.for_send(message, delivery, source_facts=None, via="unknown", now=now,
                                        historical=True)
                self.repo.append(workspace_id, operator, "short_message_backfill", now, changes)
        return {"workspaceId": workspace_id, "created": True, "schemaVersion": 1,
                "backfilledMessages": len(messages), "backfilledThreads": len(threads), "backup": backup}

    upgrade = initialize

    def _current_facts(self, binding, workspace_id):
        """Current binding scope must come from the exact trusted handle."""
        facts = dict(binding)
        alias = binding.get("alias")
        if alias:
            result = self.directory.reader.endpoint(workspace_id, alias)
            endpoint, handle = result.get("agentEndpoint", {}), result.get("providerHandle")
            if (not handle or endpoint.get("providerHandleId") != binding.get("handle_id")
                    or handle.get("handleId") != binding.get("handle_id")
                    or endpoint.get("agentId") != binding.get("agent_id")
                    or endpoint.get("provider") != binding.get("provider")):
                raise Conflict("short reference route differs from the frozen recipient binding")
            current = facts_from_handle(handle, binding["provider"])
            if any(current.get(name) != binding.get(name) for name in ("agent_id", "native_session_id", "generation")):
                raise Conflict("short reference facts differ from the frozen recipient binding")
            facts["native_scope"] = current["native_scope"]
        return facts

    def _historical_facts(self, binding, message):
        """Recover scope only from evidence that existed before this message.

        Old RecipientBinding records have no namespace field. Today's endpoint
        or a later registration cannot repair that historical omission. A
        missing, malformed or ambiguous event history leaves the identity
        unknown instead of inventing an unscoped identity and a new number.
        """
        if "native_scope" in binding:
            return dict(binding)
        try:
            created = datetime.fromisoformat(message["created_at"])
            if created.utcoffset() is None or stamp(created) != message["created_at"]:
                return None
        except (TypeError, ValueError, OverflowError):
            return None
        candidates = {}
        for row in self.directory.reader.registration_history(message["workspace_id"]):
            if (row.get("action") != "registered" or type(row.get("sequence")) is not int
                    or row["sequence"] <= 0
                    or any(row.get(name) != binding.get(name) for name in
                           ("agent_id", "provider", "native_session_id", "handle_id", "generation"))):
                continue
            try:
                occurred = datetime.fromisoformat(row["occurred_at"])
                if (occurred.utcoffset() is None or stamp(occurred) != row["occurred_at"]
                        or occurred > created):
                    continue
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            identity = logical_identity(row)
            if identity:
                candidates[identity["key"]] = identity
        if len(candidates) != 1:
            return None
        identity = next(iter(candidates.values()))
        return {**binding, "native_scope": identity["native_scope"]}

    def for_send(self, message, delivery, source_facts=None, via="unknown", now=None, *, historical=False):
        workspace_id = message["workspace_id"]
        self._require(workspace_id)
        if via not in {"store", "inline", "queued", "unknown"}:
            raise CommunicationError("invalid actual delivery path")
        if self.repo.get("message_contexts", workspace_id, message["id"]):
            raise Conflict("message identity context is immutable")
        now = now or self.service._now()
        pending = []
        workspace = self.repo.short_ref(workspace_id, "workspace", object_id=workspace_id)
        if not workspace:
            workspace = self._new_ref(workspace_id, "workspace", workspace_id, "P", now, pending,
                                      provenance={"order": "deterministic_fallback"})
        thread = self._new_ref(workspace_id, "thread", message["thread_id"], "T", now, pending,
                               provenance={"order": "communication_event" if not historical else "deterministic_import_fallback"})
        ref = self._new_ref(workspace_id, "message", message["id"], "M", now, pending,
                            provenance={"order": "communication_event", "historical": historical,
                                        "legacySequence": message.get("legacy_request_sequence")})
        target_facts = delivery.get("binding")
        if target_facts:
            target_facts = dict(target_facts)
            if historical:
                target_facts = self._historical_facts(target_facts, message)
            else:
                target_facts = self._current_facts(target_facts, workspace_id)
        source_identity, target_identity = logical_identity(source_facts), logical_identity(target_facts)
        identities, codes = [], []
        for identity, expected in ((source_identity, message["sender"]), (target_identity, message["target"])):
            if identity and identity["agent_id"] != expected:
                raise AccessDenied("short identity does not match the committed route")
            identities.append(identity)
            if identity:
                session = self._new_ref(workspace_id, "session", identity["key"], PREFIXES[identity["provider"]],
                                        now, pending, identity=identity,
                                        provenance={"order": "frozen_binding_fallback", "historical": historical})
                codes.append(session["code"])
            else:
                codes.append(None)
        context = {"workspace_id": workspace_id, "id": message["id"], "workspace_ref": workspace["code"],
                   "message_ref": ref["code"], "thread_ref": thread["code"],
                   "from_ref": codes[0], "to_ref": codes[1], "from_identity": identities[0], "to_identity": identities[1],
                   "via": via, "frozen_at": now, "historical": historical,
                   "provenance": "historical_frozen_binding_source_unknown" if historical else "authorized_send_binding"}
        binding_fields = ("agent_id", "provider", "native_session_id", "native_scope", "alias", "handle_id", "generation")
        context["from_binding"] = ({name: source_facts.get(name) for name in binding_fields} if source_identity else None)
        context["to_binding"] = ({name: target_facts.get(name) for name in binding_fields} if target_identity else None)
        return {"short_refs": pending, "message_contexts": [context]}

    def context(self, workspace_id, message_id):
        return self.repo.get("message_contexts", workspace_id, message_id)

    def resolve(self, caller, kind, code):
        if kind not in {"workspace", "message", "thread"}:
            raise CommunicationError("use session lookup for a short session reference")
        prefix = {"workspace": "P", "message": "M", "thread": "T"}[kind]
        if not isinstance(code, str) or not CODE.fullmatch(code) or not code.startswith(prefix):
            raise CommunicationError("invalid explicitly typed short reference")
        with self.repo.transaction(write=False):
            self.directory.require_member(caller)
            self._require(caller.workspace_id)
            row = self.repo.short_ref(caller.workspace_id, kind, code=code)
            if not row:
                raise AccessDenied("short reference is not visible in this workspace")
            identity = row["object_id"]
            if kind == "message":
                self.service._message(caller, identity)
            elif kind == "thread":
                self.service._thread(caller, identity)
            elif identity != caller.workspace_id:
                raise AccessDenied("short workspace differs from the trusted caller binding")
            return identity

    def lookup_session(self, caller, code, *, include_native=False):
        if (not isinstance(code, str) or not CODE.fullmatch(code)
                or not any(code.startswith(prefix) for prefix in PREFIXES.values())
                or type(include_native) is not bool):
            raise CommunicationError("invalid short session reference or include_native flag")
        with self.repo.transaction(write=False):
            self.directory.require_member(caller)
            self._require(caller.workspace_id)
            row = self.repo.short_ref(caller.workspace_id, "session", code=code)
            if not row:
                raise AccessDenied("short session is not visible in this workspace")
            identity = row["identity"]
            bindings = []
            for endpoint in self.directory.reader.endpoints(caller.workspace_id):
                if endpoint.get("agentId") != identity["agent_id"] or endpoint.get("provider") != identity["provider"]:
                    continue
                result = self.directory.reader.endpoint(caller.workspace_id, endpoint["alias"])
                handle = result.get("providerHandle")
                if (not handle or handle.get("state") != "active" or endpoint.get("state") != "active"
                        or handle.get("agentId") != identity["agent_id"]):
                    continue
                if logical_identity(facts_from_handle(handle, identity["provider"])) != identity:
                    continue
                try:
                    self.directory.require_member(Caller(caller.workspace_id, identity["agent_id"]))
                except AccessDenied:
                    continue
                bindings.append({"alias": endpoint["alias"], "handleId": handle["handleId"],
                                 "generation": (handle.get("metadata") or {}).get("runtimeBinding", {}).get("generationId")})
            result = {"workspaceRef": self.repo.short_ref(caller.workspace_id, "workspace", object_id=caller.workspace_id)["code"],
                      "sessionRef": code, "agentId": identity["agent_id"], "provider": identity["provider"],
                      "registration": "active" if bindings else "tombstone", "bindings": bindings,
                      "scopeKnown": identity["native_scope"] is not None, "provenance": row["provenance"]}
            if include_native:
                result["nativeSessionId"] = identity["native_session_id"]
                # Scope is used for matching but full local paths/config remain
                # internal, even in the on-demand identity response.
            return result

    def _receiver_aliases(self, workspace_id, identity):
        """Read exact live receiver routes in the caller's existing snapshot."""
        aliases = []
        for endpoint in self.directory.reader.endpoints(workspace_id):
            if (endpoint.get("agentId") != identity["agent_id"]
                    or endpoint.get("provider") != identity["provider"]
                    or endpoint.get("direction") not in {"receive_only", "send_receive"}):
                continue
            try:
                binding = self.directory.resolve(workspace_id, endpoint["alias"])
                facts = self._current_facts(binding.to_dict(), workspace_id)
            except AccessDenied:
                continue
            if logical_identity(facts) == identity:
                aliases.append(binding.alias)
        return aliases

    def target_alias(self, caller, code):
        """A short identity is sendable only through one exact active receiver.

        Alias/contact policies may differ even for the same native session.
        Never choose one alphabetically, and never revive a tombstone route.
        The send transaction still revalidates its frozen target handle.
        """
        if (not isinstance(code, str) or not CODE.fullmatch(code)
                or not any(code.startswith(prefix) for prefix in PREFIXES.values())):
            raise CommunicationError("invalid short target reference")
        with self.repo.transaction(write=False):
            self.directory.require_member(caller)
            self._require(caller.workspace_id)
            row = self.repo.short_ref(caller.workspace_id, "session", code=code)
            if not row:
                raise AccessDenied("short target is not visible in this workspace")
            expected = row["identity"]
            candidates = self._receiver_aliases(caller.workspace_id, expected)
            if len(candidates) != 1:
                raise Conflict("short target is inactive or has ambiguous receiver aliases")
            return candidates[0]

    def assert_target_binding(self, caller, code, binding):
        """Final send validation inside its existing owned write transaction."""
        if (not isinstance(code, str) or not CODE.fullmatch(code)
                or not any(code.startswith(prefix) for prefix in PREFIXES.values())):
            raise CommunicationError("invalid short target reference")
        self.directory.require_member(caller)
        self._require(caller.workspace_id)
        self.repo.require_short_write()
        row = self.repo.short_ref(caller.workspace_id, "session", code=code)
        if not row:
            raise AccessDenied("short target is not visible in this workspace")
        if not isinstance(binding, dict) or binding.get("agent_id") != row["identity"]["agent_id"]:
            raise Conflict("short target responsibility differs from the resolved route")
        facts = self._current_facts(binding, caller.workspace_id)
        if logical_identity(facts) != row["identity"]:
            raise Conflict("short target native identity differs from the resolved route")
        if self._receiver_aliases(caller.workspace_id, row["identity"]) != [binding.get("alias")]:
            raise Conflict("short target is inactive or has ambiguous receiver aliases")
