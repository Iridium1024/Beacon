from __future__ import annotations

from datetime import datetime, timezone
import tempfile
import unittest
from pathlib import Path
from typing import Mapping

from agent_os.application.services.console_projection import (
    ConsoleProjectionService,
)
from agent_os.application.services.local_platform_application import (
    LocalPlatformApplication,
)
from agent_os.domain.value_objects.identifiers import (
    PlatformEventId,
    WorkspaceId,
)
from agent_os.infrastructure.config import LocalPlatformSettings
from agent_os.infrastructure.persistence.event_log import (
    PlatformEventKind,
    PlatformEventLogEntry,
    PlatformEventRecord,
)


class ConsoleProjectionTests(unittest.TestCase):
    def test_application_projects_four_provider_identities_without_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "workspace").mkdir()
            (root / "plugins").mkdir()
            app = LocalPlatformApplication(
                LocalPlatformSettings(
                    database=str(root / "platform.sqlite3"),
                    workspace_root=str(root / "workspace"),
                    plugins_directory=str(root / "plugins"),
                )
            )
            app.create_workspace(
                workspace_id="workspace-console",
                agent_id="agent-source",
                display_name="Console demo",
                root_path=str(root / "workspace" / "private" / "project"),
            )
            app.create_agent(
                workspace_id="workspace-console",
                agent_id="agent-target",
                name="Target",
                description="fake target",
            )
            app.register_claude_session_handle(
                workspace_id="workspace-console",
                agent_id="agent-source",
                handle_id="handle-collision-claude",
                claude_session_uuid="11111111-1111-4111-8111-111111111111",
                cwd=str(root / "workspace"),
                created_by="test",
                reason="fixture",
            )
            app.register_codex_session_handle(
                workspace_id="workspace-console",
                agent_id="agent-source",
                handle_id="handle-collision-codex",
                codex_session_id="11111111-1111-4111-8111-111111111111",
                cwd=str(root / "workspace"),
                created_by="test",
                reason="fixture",
            )
            app.register_hermes_session_handle(
                workspace_id="workspace-console",
                agent_id="agent-target",
                handle_id="handle-hermes",
                hermes_session_id="hermes-demo-01",
                cwd=str(root / "workspace"),
                created_by="test",
                reason="fixture",
            )
            app.register_deepseek_harness_session_handle(
                workspace_id="workspace-console",
                agent_id="agent-target",
                handle_id="handle-dsh",
                deepseek_harness_session_id="dsh-demo-01",
                cwd=str(root / "workspace"),
                created_by="test",
                reason="fixture",
            )
            app.create_agent_dispatch(
                workspace_id="workspace-console",
                dispatch_id="dispatch-demo",
                exchange_request_id="request-demo",
                source_agent_id="agent-source",
                target_agent_id="agent-target",
                target_provider="deepseek_harness",
                target_handle_id="handle-dsh",
                request_kind="question",
                request_summary="SECRET PROMPT CONTENT MUST NOT LEAK",
            )

            view = app.get_console_workspace_view(
                workspace_id="workspace-console",
                limit=200,
            )

            self.assertEqual(view["schema"], "beacon.console.v1")
            self.assertTrue(view["readOnly"])
            identities = [
                (
                    item["identity"]["provider"],
                    item["identity"]["nativeSessionId"],
                )
                for item in view["sessions"]
            ]
            self.assertIn(
                ("claude", "11111111-1111-4111-8111-111111111111"),
                identities,
            )
            self.assertIn(
                ("codex", "11111111-1111-4111-8111-111111111111"),
                identities,
            )
            self.assertIn(("hermes", "hermes-demo-01"), identities)
            self.assertIn(("deepseek_harness", "dsh-demo-01"), identities)
            dsh = next(
                item
                for item in view["sessions"]
                if item["identity"]["provider"] == "deepseek_harness"
            )
            self.assertTrue(dsh["nativeDshSession"])
            self.assertFalse(dsh["foreignProjectionOnly"])
            self.assertEqual(
                dsh["continuity"]["scope"],
                "persistent_native_session",
            )
            serialized = repr(view)
            self.assertNotIn("SECRET PROMPT", serialized)
            self.assertNotIn("request_summary", serialized)
            self.assertNotIn("metadata", serialized)
            self.assertNotIn(str(root), view["workspace"]["rootSummary"])

    def test_unknown_values_duplicates_paging_and_sensitive_payload_are_bounded(self) -> None:
        first = _event(
            sequence=2,
            event_id="event-duplicate",
            event_kind=PlatformEventKind.CONTEXT_UPDATE_APPENDED,
            payload={"prompt": "do not leak", "token": "do not leak"},
        )
        duplicate = _event(
            sequence=3,
            event_id="event-duplicate",
            event_kind=PlatformEventKind.AGENT_DISPATCH_CHANGED,
        )
        third = _event(
            sequence=8,
            event_id="event-third",
            event_kind=PlatformEventKind.DEEPSEEK_HARNESS_RUNTIME_LIFECYCLE_RECORDED,
        )
        service = ConsoleProjectionService(
            operations=_FakeOperations(),
            event_log=_FakeEventLog((third, duplicate, first)),
        )

        first_page = service.workspace_view("workspace-fake", limit=1)
        timeline = first_page["timeline"]
        self.assertEqual(len(timeline["events"]), 1)
        self.assertTrue(timeline["page"]["hasMore"])
        self.assertEqual(timeline["page"]["nextCursor"], "ord:1")
        self.assertEqual(timeline["events"][0]["category"]["value"], "unknown")
        self.assertFalse(timeline["events"][0]["category"]["known"])
        self.assertNotIn("do not leak", repr(first_page))
        self.assertNotIn("/private", first_page["workspace"]["rootSummary"])

        second_page = service.workspace_view(
            "workspace-fake",
            cursor="ord:1",
            limit=10,
        )
        self.assertEqual(
            [item["eventId"] for item in second_page["timeline"]["events"]],
            ["event-third"],
        )
        self.assertEqual(second_page["sessions"][0]["state"]["value"], "unknown")
        self.assertEqual(
            second_page["sessions"][0]["state"]["rawValue"],
            "future_state",
        )
        out_of_range = service.workspace_view(
            "workspace-fake",
            cursor="ord:99",
            limit=10,
        )
        self.assertTrue(out_of_range["timeline"]["page"]["rebuildRequired"])
        with self.assertRaisesRegex(ValueError, "cursor"):
            service.workspace_view("workspace-fake", cursor="sequence:4")
        with self.assertRaisesRegex(ValueError, "between 1 and 200"):
            service.workspace_view("workspace-fake", limit=201)

    def test_capabilities_report_current_beacon_implementation(self) -> None:
        service = ConsoleProjectionService(
            operations=_FakeOperations(),
            event_log=_FakeEventLog(()),
        )
        response = service.provider_backends()
        by_id = {item["backendId"]: item for item in response["items"]}
        dsh = by_id["deepseek_harness_sdk_stdio"]
        self.assertEqual(dsh["statusAuthority"]["value"], "owned_live")
        self.assertTrue(dsh["capabilities"]["canOwnRuntime"])
        self.assertTrue(dsh["capabilities"]["canSend"])
        self.assertTrue(dsh["capabilities"]["canResume"])
        self.assertTrue(dsh["capabilities"]["canCaptureFinalMessage"])
        self.assertFalse(dsh["capabilities"]["canCancel"])
        self.assertTrue(dsh["capabilities"]["canResumeAcrossProcess"])
        self.assertFalse(dsh["capabilities"]["canReadHistory"])
        self.assertTrue(dsh["canResumeAcrossRuntimeRestart"])
        self.assertEqual(dsh["maxConcurrentOperations"], 1)


class _FakeOperations:
    def list_workspaces(self) -> Mapping[str, object]:
        return {
            "workspaces": [
                {
                    "workspaceId": "workspace-fake",
                    "displayName": "Fake workspace",
                    "rootPath": "/private/root/project",
                    "status": "active",
                    "updatedAt": "2026-08-24T00:00:00+00:00",
                    "sourceEventSequence": 1,
                    "metadata": {"credential": "do not leak"},
                }
            ]
        }

    def list_agent_registrations(self, _workspace_id: str) -> Mapping[str, object]:
        return {
            "agents": [
                {
                    "agentId": "agent-fake",
                    "name": "Fake agent",
                    "status": "future_status",
                    "capabilities": [{"name": "observe"}],
                }
            ]
        }

    def list_agent_dispatches(
        self,
        _workspace_id: str,
        *,
        limit: int = 20,
    ) -> Mapping[str, object]:
        self.last_limit = limit
        return {"agentDispatches": []}

    def list_claude_session_handles(
        self,
        _workspace_id: str,
        *,
        include_inactive: bool = False,
    ) -> Mapping[str, object]:
        self.include_inactive = include_inactive
        return {
            "claudeSessionHandles": [
                {
                    "workspaceId": "workspace-fake",
                    "agentId": "agent-fake",
                    "handleId": "handle-fake",
                    "provider": "claude",
                    "claudeSessionUuid": "native-fake",
                    "cwd": "/private/root/project",
                    "state": "future_state",
                    "metadata": {"prompt": "do not leak"},
                }
            ]
        }

    def list_codex_session_handles(self, *args, **kwargs) -> Mapping[str, object]:
        return {"codexSessionHandles": []}

    def list_hermes_session_handles(self, *args, **kwargs) -> Mapping[str, object]:
        return {"hermesSessionHandles": []}

    def list_deepseek_harness_session_handles(
        self,
        *args,
        **kwargs,
    ) -> Mapping[str, object]:
        return {"deepseekHarnessSessionHandles": []}


class _FakeEventLog:
    def __init__(self, entries: tuple[PlatformEventLogEntry, ...]) -> None:
        self.entries = entries

    def initialize(self) -> None:
        return None

    def append(self, record: PlatformEventRecord) -> int:
        raise AssertionError("read-only projection must not append")

    def list_workspace_events(
        self,
        _workspace_id: WorkspaceId,
    ) -> tuple[PlatformEventLogEntry, ...]:
        return self.entries

    def list_session_events(self, **kwargs) -> tuple[PlatformEventLogEntry, ...]:
        return ()


def _event(
    *,
    sequence: int,
    event_id: str,
    event_kind: PlatformEventKind,
    payload: Mapping[str, object] | None = None,
) -> PlatformEventLogEntry:
    return PlatformEventLogEntry(
        sequence=sequence,
        record=PlatformEventRecord.create(
            event_id=PlatformEventId(event_id),
            workspace_id=WorkspaceId("workspace-fake"),
            event_kind=event_kind,
            aggregate_type="fixture",
            aggregate_id=f"aggregate-{sequence}",
            occurred_at=datetime(2026, 8, 24, 0, sequence, tzinfo=timezone.utc),
            payload=payload,
        ),
    )


if __name__ == "__main__":
    unittest.main()
