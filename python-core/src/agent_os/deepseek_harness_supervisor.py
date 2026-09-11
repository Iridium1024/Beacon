from __future__ import annotations

import argparse
from collections.abc import Mapping as MappingABC
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import socketserver
import threading
import time
from typing import BinaryIO, Mapping
from uuid import uuid4

from agent_os.application.services.deepseek_harness_managed_runtime import (
    DeepSeekHarnessContinuityError,
    DeepSeekHarnessDeliveryError,
    DeepSeekHarnessJsonRpcTransport,
    DeepSeekHarnessProtocolError,
    DeepSeekHarnessRuntimeSpec,
    read_runtime_state,
    write_runtime_state,
)


_MAX_IPC_BYTES = 1024 * 1024


class _OwnerLease:
    """A process-lifetime, cross-platform file lock for one generation."""

    def __init__(self, path: str, identity: Mapping[str, object]) -> None:
        self.path = Path(path)
        self.identity = dict(identity)
        self._stream: BinaryIO | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise DeepSeekHarnessContinuityError(
                "another supervisor already owns the runtime generation lease."
            ) from exc
        stream.seek(0)
        stream.truncate()
        stream.write(
            json.dumps(
                self.identity,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        stream.flush()
        os.fsync(stream.fileno())
        stream.seek(0)
        self._stream = stream

    def release(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        stream.close()


class _OperationLease:
    """Atomic evidence that no second process may enqueue another prompt."""

    def __init__(
        self,
        path: str,
        *,
        generation_id: str,
        owner_nonce: str,
        operation_id: str,
    ) -> None:
        self.path = Path(path)
        self.payload = {
            "schema": "deepseek_harness_operation_lease.v1",
            "generationId": generation_id,
            "ownerNonce": owner_nonce,
            "operationId": operation_id,
            "ownerPid": os.getpid(),
            "createdAt": _utc_now(),
        }
        self._owned = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                self.path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            return False
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(
                json.dumps(
                    self.payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            stream.flush()
            os.fsync(stream.fileno())
        self._owned = True
        return True

    def release(self) -> None:
        if not self._owned:
            return
        self._owned = False
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, MappingABC):
            return
        if (
            raw.get("generationId") != self.payload["generationId"]
            or raw.get("ownerNonce") != self.payload["ownerNonce"]
            or raw.get("operationId") != self.payload["operationId"]
        ):
            return
        try:
            self.path.unlink()
        except OSError:
            pass


class _ThreadingLoopbackServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, supervisor: "DeepSeekHarnessSupervisor") -> None:
        self.supervisor = supervisor
        super().__init__(("127.0.0.1", 0), _SupervisorRequestHandler)


class _SupervisorRequestHandler(socketserver.StreamRequestHandler):
    server: _ThreadingLoopbackServer

    def handle(self) -> None:
        line = self.rfile.readline(_MAX_IPC_BYTES + 1)
        if len(line) > _MAX_IPC_BYTES:
            self._send(
                {
                    "schema": "deepseek_harness_supervisor_response.v1",
                    "ok": False,
                    "status": "rejected",
                    "failureCategory": "ipc_request_oversized",
                }
            )
            return
        try:
            decoded = line.decode("utf-8", errors="strict")
            request = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(
                {
                    "schema": "deepseek_harness_supervisor_response.v1",
                    "ok": False,
                    "status": "rejected",
                    "failureCategory": "ipc_request_malformed",
                }
            )
            return
        if not isinstance(request, MappingABC):
            self._send(
                {
                    "schema": "deepseek_harness_supervisor_response.v1",
                    "ok": False,
                    "status": "rejected",
                    "failureCategory": "ipc_request_not_object",
                }
            )
            return
        self._send(self.server.supervisor.handle_request(dict(request)))

    def _send(self, value: Mapping[str, object]) -> None:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        if len(encoded) > _MAX_IPC_BYTES:
            encoded = (
                b'{"schema":"deepseek_harness_supervisor_response.v1",'
                b'"ok":false,"status":"failed",'
                b'"failureCategory":"ipc_response_oversized"}\n'
            )
        self.wfile.write(encoded)
        self.wfile.flush()


class DeepSeekHarnessSupervisor:
    def __init__(self, spec: DeepSeekHarnessRuntimeSpec) -> None:
        self.spec = spec
        self.instance_id = f"dsh-supervisor-{uuid4()}"
        self.process_started_at = time.time()
        self._state_lock = threading.RLock()
        self._operation_lock = threading.Lock()
        self._stopping = threading.Event()
        self._transport = DeepSeekHarnessJsonRpcTransport(spec)
        self._server: _ThreadingLoopbackServer | None = None
        self._monitor: threading.Thread | None = None
        self._token = Path(spec.paths.token_path).read_text(encoding="utf-8").strip()
        self._state = dict(read_runtime_state(spec.paths.state_path))
        self._owner_lease = _OwnerLease(
            spec.paths.owner_lease_path,
            {
                "schema": "deepseek_harness_owner_lease.v1",
                "runtimeId": spec.runtime_id,
                "generationId": spec.generation_id,
                "ownerNonce": spec.owner_nonce,
                "supervisorInstanceId": self.instance_id,
                "supervisorPid": os.getpid(),
                "processStartedAt": self.process_started_at,
            },
        )
        self._session_owner_lease = _OwnerLease(
            spec.paths.session_owner_lease_path,
            {
                "schema": "deepseek_harness_session_owner_lease.v1",
                "runtimeId": spec.runtime_id,
                "generationId": spec.generation_id,
                "ownerNonce": spec.owner_nonce,
                "workspaceId": spec.workspace_id,
                "agentId": spec.agent_id,
                "handleId": spec.handle_id,
                "dshSessionId": spec.dsh_session_id,
                "sessionRoot": spec.session_root,
                "supervisorInstanceId": self.instance_id,
                "supervisorPid": os.getpid(),
                "processStartedAt": self.process_started_at,
            },
        )

    def run(self) -> int:
        self._validate_bootstrap_state()
        try:
            self._owner_lease.acquire()
        except DeepSeekHarnessContinuityError as exc:
            self._write_terminal_start_failure(
                "duplicate_supervisor_owner",
                str(exc),
            )
            return 2
        try:
            self._session_owner_lease.acquire()
        except DeepSeekHarnessContinuityError as exc:
            self._write_terminal_start_failure(
                "session_owner_conflict",
                (
                    "the persistent DSH session already has a live Beacon owner; "
                    "reuse that runtime, stop it cleanly, or choose a different session. "
                    f"{exc}"
                ),
            )
            self._owner_lease.release()
            return 2
        operation_lease = Path(self.spec.paths.operation_lease_path)
        if operation_lease.exists():
            self._write_terminal_start_failure(
                "stale_operation_lease",
                "a stale operation lease exists; the previous generation cannot be resumed.",
                continuity_lost=True,
            )
            self._owner_lease.release()
            self._session_owner_lease.release()
            return 3
        try:
            self._server = _ThreadingLoopbackServer(self)
            runtime_evidence = self._transport.start()
            host, port = self._server.server_address
            now = _utc_now()
            self._state.update(
                {
                    "lifecycle": "ready",
                    "runtimeState": "idle",
                    "supervisorInstanceId": self.instance_id,
                    "supervisorPid": os.getpid(),
                    "supervisorProcessStartedAt": self.process_started_at,
                    "supervisorProcessEvidence": _process_evidence(
                        os.getpid(),
                        self.process_started_at,
                        self.spec.owner_nonce,
                    ),
                    "runtimePid": runtime_evidence.get("processId"),
                    "runtimeProcessStartedAt": runtime_evidence.get(
                        "processStartedAt"
                    ),
                    "runtimeProcessEvidence": _process_evidence(
                        int(runtime_evidence.get("processId") or 0),
                        float(runtime_evidence.get("processStartedAt") or 0),
                        self.spec.owner_nonce,
                    ),
                    "serverInfo": {
                        "name": runtime_evidence.get("serverName"),
                        "version": runtime_evidence.get("serverVersion"),
                    },
                    "ipcEndpoint": {
                        "transport": "tcp_loopback_jsonl",
                        "host": host,
                        "port": port,
                        "ownerTokenRequired": True,
                        "trustBoundary": "same_local_user_machine",
                    },
                    "startedAt": now,
                    "heartbeatAt": now,
                    "lastSeenAt": now,
                }
            )
            self._persist_state()
            self._monitor = threading.Thread(
                target=self._monitor_runtime,
                name=f"beacon-dsh-monitor-{self.spec.generation_id}",
                daemon=True,
            )
            self._monitor.start()
            self._server.serve_forever(poll_interval=0.25)
            return 0
        except BaseException as exc:
            if not self._stopping.is_set():
                self._write_terminal_start_failure(
                    "runtime_start_failed",
                    f"{exc.__class__.__name__}: {exc}",
                    continuity_lost=True,
                )
            self._transport.force_terminate()
            return 4
        finally:
            if self._server is not None:
                self._server.server_close()
            self._session_owner_lease.release()
            self._owner_lease.release()

    def handle_request(self, request: Mapping[str, object]) -> Mapping[str, object]:
        identity_failure = self._validate_request_identity(request)
        if identity_failure is not None:
            return identity_failure
        method = request.get("method")
        payload = request.get("payload")
        if not isinstance(payload, MappingABC):
            payload = {}
        self._touch_heartbeat()
        if method == "status":
            return self._status_response()
        if method == "submit":
            return self._submit(dict(payload))
        if method == "stop":
            return self._stop(dict(payload))
        return self._failure("ipc_method_unknown", "unknown supervisor method")

    def _submit(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        if self._stopping.is_set() or not self._transport.is_alive():
            return self._failure(
                "session_continuity_lost",
                "the owned runtime generation is not live; explicit resume or recreate is required.",
                status="continuity_lost",
            )
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            return self._failure("prompt_missing", "message is required")
        operation_id = str(payload.get("operationId") or f"dsh-operation-{uuid4()}")
        if not self._operation_lock.acquire(blocking=False):
            return self._busy_response()
        operation_lease = _OperationLease(
            self.spec.paths.operation_lease_path,
            generation_id=self.spec.generation_id,
            owner_nonce=self.spec.owner_nonce,
            operation_id=operation_id,
        )
        if not operation_lease.acquire():
            self._operation_lock.release()
            return self._busy_response()
        with self._state_lock:
            if self._state.get("activeOperationId") is not None:
                operation_lease.release()
                self._operation_lock.release()
                return self._busy_response()
            self._state["activeOperationId"] = operation_id
            self._state["runtimeState"] = "busy"
            self._state["lastSeenAt"] = _utc_now()
            self._persist_state_locked()
        try:
            result = self._transport.run_operation(
                operation_id=operation_id,
                session_id=self.spec.dsh_session_id,
                message=message,
                timeout_seconds=self.spec.operation_timeout_seconds,
            )
            with self._state_lock:
                self._state["activeOperationId"] = None
                self._state["runtimeState"] = "idle"
                self._state["lastStatus"] = "idle"
                self._state["lastAcceptedMessageId"] = result.message_id
                self._state["durableEventWatermark"] = result.idle_watermark
                self._state["lastOperation"] = result.to_metadata(
                    include_response=False
                )
                self._state["lastSeenAt"] = _utc_now()
                self._persist_state_locked()
            return {
                "schema": "deepseek_harness_supervisor_response.v1",
                "ok": True,
                "status": "completed",
                "runtimeId": self.spec.runtime_id,
                "generationId": self.spec.generation_id,
                "dshSessionId": self.spec.dsh_session_id,
                "operation": result.to_metadata(include_response=True),
                "providerFinalCaptureAllowed": (
                    self.spec.reply_writeback_mode == "provider_final_capture"
                    and result.trusted_final
                ),
                "ambiguousDelivery": False,
                "runtimeState": dict(self._state),
            }
        except DeepSeekHarnessDeliveryError as exc:
            self._lose_continuity(
                "prompt_transport_failure",
                ambiguous_delivery=exc.ambiguous_delivery,
            )
            return self._failure(
                "ambiguous_delivery"
                if exc.ambiguous_delivery
                else "prompt_not_submitted",
                str(exc),
                status="continuity_lost",
                ambiguous_delivery=exc.ambiguous_delivery,
            )
        except (DeepSeekHarnessProtocolError, DeepSeekHarnessContinuityError) as exc:
            self._lose_continuity(
                "runtime_protocol_or_continuity_failure",
                ambiguous_delivery=True,
            )
            return self._failure(
                "runtime_protocol_or_continuity_failure",
                str(exc),
                status="continuity_lost",
                ambiguous_delivery=True,
            )
        except BaseException as exc:
            self._lose_continuity(
                "runtime_operation_failure",
                ambiguous_delivery=True,
            )
            return self._failure(
                "runtime_operation_failure",
                f"{exc.__class__.__name__}: {exc}",
                status="continuity_lost",
                ambiguous_delivery=True,
            )
        finally:
            operation_lease.release()
            self._operation_lock.release()

    def _stop(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        if (
            payload.get("acknowledgeRuntimeStop") is not True
            and payload.get("acknowledgeContinuityLoss") is not True
        ):
            return self._failure(
                "runtime_stop_acknowledgement_required",
                "stop requires acknowledgeRuntimeStop=true.",
                status="rejected",
            )
        self._stopping.set()
        active = self._state.get("activeOperationId") is not None
        if active:
            self._transport.force_terminate()
            stop_mode = "active_forced_termination"
            lifecycle = "continuity_lost"
            ambiguous_delivery = True
        else:
            shutdown = self._transport.graceful_shutdown()
            stop_mode = str(shutdown.get("shutdown"))
            lifecycle = "stopped"
            ambiguous_delivery = False
        with self._state_lock:
            now = _utc_now()
            self._state.update(
                {
                    "activeOperationId": None,
                    "lifecycle": lifecycle,
                    "runtimeState": "unavailable",
                    "lastStatus": "unavailable",
                    "continuityLostAt": now if active else None,
                    "continuityLossReason": (
                        "active_operation_forced_termination" if active else None
                    ),
                    "ambiguousDelivery": ambiguous_delivery,
                    "stoppedAt": now,
                    "stopMode": stop_mode,
                }
            )
            self._persist_state_locked()
        self._owner_lease.release()
        self._session_owner_lease.release()
        self._shutdown_server_async()
        return {
            "schema": "deepseek_harness_supervisor_response.v1",
            "ok": True,
            "status": lifecycle,
            "stopMode": stop_mode,
            "continuityLost": active,
            "ambiguousDelivery": ambiguous_delivery,
            "resumeRequired": True,
            "resumeAvailable": not ambiguous_delivery,
            "resumeRequiresAmbiguousDeliveryAcknowledgement": ambiguous_delivery,
            "requiresRecreate": False,
            "runtimeState": dict(self._state),
        }

    def _status_response(self) -> Mapping[str, object]:
        if not self._transport.is_alive() and not self._stopping.is_set():
            self._lose_continuity(
                "runtime_process_not_live",
                ambiguous_delivery=self._state.get("activeOperationId") is not None,
            )
        return {
            "schema": "deepseek_harness_supervisor_response.v1",
            "ok": self._state.get("lifecycle") == "ready",
            "status": self._state.get("runtimeState"),
            "statusAuthority": "owned_live",
            "ownerLeaseHeld": True,
            "runtimeProcessLive": self._transport.is_alive(),
            "runtimeState": dict(self._state),
        }

    def _busy_response(self) -> Mapping[str, object]:
        return {
            "schema": "deepseek_harness_supervisor_response.v1",
            "ok": False,
            "status": "busy",
            "failureCategory": "target_runtime_busy",
            "failureReason": (
                "one prompt operation already owns this DSH session/generation; "
                "Beacon did not prompt, steer, queue, replay, or create a session."
            ),
            "ambiguousDelivery": False,
            "activeOperationId": self._state.get("activeOperationId"),
            "runtimeState": dict(self._state),
        }

    def _failure(
        self,
        category: str,
        reason: str,
        *,
        status: str = "failed",
        ambiguous_delivery: bool = False,
    ) -> Mapping[str, object]:
        return {
            "schema": "deepseek_harness_supervisor_response.v1",
            "ok": False,
            "status": status,
            "failureCategory": category,
            "failureReason": reason,
            "ambiguousDelivery": ambiguous_delivery,
            "runtimeState": dict(self._state),
        }

    def _validate_request_identity(
        self,
        request: Mapping[str, object],
    ) -> Mapping[str, object] | None:
        token = request.get("ownerToken")
        if not isinstance(token, str) or not hmac.compare_digest(token, self._token):
            return self._failure(
                "ipc_owner_token_rejected",
                "owner token rejected",
                status="rejected",
            )
        expected = {
            "workspaceId": self.spec.workspace_id,
            "agentId": self.spec.agent_id,
            "handleId": self.spec.handle_id,
            "runtimeId": self.spec.runtime_id,
            "generationId": self.spec.generation_id,
        }
        mismatches = {
            key: {"expected": value, "actual": request.get(key)}
            for key, value in expected.items()
            if request.get(key) != value
        }
        if mismatches:
            return {
                **self._failure(
                    "ipc_runtime_identity_rejected",
                    "workspace/agent/handle/runtime/generation identity mismatch",
                    status="rejected",
                ),
                "mismatches": mismatches,
            }
        return None

    def _validate_bootstrap_state(self) -> None:
        expected = {
            "runtimeId": self.spec.runtime_id,
            "generationId": self.spec.generation_id,
            "ownerNonce": self.spec.owner_nonce,
            "workspaceId": self.spec.workspace_id,
            "agentId": self.spec.agent_id,
            "handleId": self.spec.handle_id,
            "dshSessionId": self.spec.dsh_session_id,
        }
        for key, value in expected.items():
            if self._state.get(key) != value:
                raise DeepSeekHarnessContinuityError(
                    f"runtime bootstrap identity mismatch: {key}"
                )
        if self._state.get("lifecycle") not in {"starting", "start_failed"}:
            raise DeepSeekHarnessContinuityError(
                "old runtime state cannot be resumed by a new supervisor process."
            )

    def _monitor_runtime(self) -> None:
        while not self._stopping.wait(1.0):
            if not self._transport.is_alive():
                self._lose_continuity(
                    "runtime_process_exited",
                    ambiguous_delivery=self._state.get("activeOperationId") is not None,
                )
                return
            self._touch_heartbeat()

    def _touch_heartbeat(self) -> None:
        with self._state_lock:
            now = _utc_now()
            self._state["heartbeatAt"] = now
            self._state["lastSeenAt"] = now
            self._persist_state_locked()

    def _lose_continuity(
        self,
        reason: str,
        *,
        ambiguous_delivery: bool,
    ) -> None:
        if self._stopping.is_set():
            return
        self._stopping.set()
        self._transport.force_terminate()
        with self._state_lock:
            now = _utc_now()
            self._state.update(
                {
                    "lifecycle": "continuity_lost",
                    "runtimeState": "unavailable",
                    "lastStatus": "unavailable",
                    "continuityLostAt": now,
                    "continuityLossReason": reason,
                    "ambiguousDelivery": ambiguous_delivery,
                    "activeOperationId": None,
                }
            )
            self._persist_state_locked()
        self._owner_lease.release()
        self._session_owner_lease.release()
        self._shutdown_server_async()

    def _write_terminal_start_failure(
        self,
        category: str,
        reason: str,
        *,
        continuity_lost: bool = False,
    ) -> None:
        with self._state_lock:
            now = _utc_now()
            self._state.update(
                {
                    "lifecycle": "continuity_lost" if continuity_lost else "start_failed",
                    "runtimeState": "unavailable",
                    "failureCategory": category,
                    "failureReason": reason,
                    "continuityLostAt": now if continuity_lost else None,
                    "continuityLossReason": category if continuity_lost else None,
                    "heartbeatAt": now,
                    "lastSeenAt": now,
                }
            )
            self._persist_state_locked()

    def _persist_state(self) -> None:
        with self._state_lock:
            self._persist_state_locked()

    def _persist_state_locked(self) -> None:
        write_runtime_state(self.spec.paths.state_path, self._state)

    def _shutdown_server_async(self) -> None:
        server = self._server
        if server is None:
            return
        threading.Thread(
            target=server.shutdown,
            name=f"beacon-dsh-shutdown-{self.spec.generation_id}",
            daemon=True,
        ).start()


def _process_evidence(pid: int, started_at: float, owner_nonce: str) -> str:
    raw = f"{pid}:{started_at:.9f}:{owner_nonce}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Beacon local-only DeepSeek Harness managed runtime supervisor."
    )
    parser.add_argument("--spec", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    raw = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    if not isinstance(raw, MappingABC):
        raise ValueError("runtime spec must be a JSON object.")
    spec = DeepSeekHarnessRuntimeSpec.from_mapping(raw)
    if Path(args.spec).resolve() != Path(spec.paths.spec_path).resolve():
        raise ValueError("runtime spec path does not match its owned identity.")
    return DeepSeekHarnessSupervisor(spec).run()


if __name__ == "__main__":
    raise SystemExit(main())
