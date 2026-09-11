from __future__ import annotations

import unittest

from agent_os.application.services.provider_backend_control import (
    CallableProviderBackendAdapter,
    ManagedRuntimeBindingSet,
    ManagedRuntimeThreadBinding,
    ProviderBackendId,
    provider_backend_registry,
    resolve_provider_backend,
)


class ProviderBackendControlTests(unittest.TestCase):
    def test_registry_exposes_current_backends_and_explicit_capabilities(self) -> None:
        registry = provider_backend_registry()

        self.assertEqual(
            set(registry),
            {
                "claude_cli",
                "claude_agent_sdk",
                "codex_exec_resume",
                "codex_app_server_stdio",
                "hermes_cli",
                "hermes_tui_gateway_stdio",
                "deepseek_harness_sdk_stdio",
            },
        )
        app_server = registry["codex_app_server_stdio"]
        self.assertEqual(app_server["lifecycle"], "short_lived_operation")
        self.assertEqual(app_server["runtimeOwnership"], "operation_owned")
        self.assertEqual(app_server["statusAuthority"], "point_read")
        self.assertFalse(
            app_server["capabilities"]["canManageMultipleThreads"]
        )
        self.assertFalse(
            app_server["capabilities"]["canReadOwnedLiveStatus"]
        )
        self.assertFalse(app_server["capabilities"]["canStartDetached"])

        for backend in registry.values():
            capabilities = backend["capabilities"]
            self.assertEqual(
                set(capabilities),
                {
                    "canExecuteInline",
                    "canStartDetached",
                    "canWait",
                    "canReadStatus",
                    "canReadOwnedLiveStatus",
                    "canManageMultipleThreads",
                    "canSupplementActiveTurn",
                    "canCancel",
                    "canCaptureFinalMessage",
                    "canOwnRuntime",
                },
            )
            if backend["backendId"] != "hermes_tui_gateway_stdio":
                self.assertFalse(capabilities["canCancel"])

        claude_sdk = registry["claude_agent_sdk"]
        self.assertEqual(claude_sdk["lifecycle"], "short_lived_operation")
        self.assertEqual(claude_sdk["runtimeOwnership"], "operation_owned")
        self.assertTrue(claude_sdk["capabilities"]["canOwnRuntime"])
        self.assertFalse(claude_sdk["capabilities"]["canReadStatus"])

        dsh = registry["deepseek_harness_sdk_stdio"]
        self.assertEqual(dsh["schema"], "provider_backend_descriptor.v2")
        self.assertEqual(dsh["lifecycle"], "managed_runtime")
        self.assertEqual(dsh["runtimeOwnership"], "persistent_owned")
        self.assertEqual(dsh["statusAuthority"], "owned_live")
        self.assertEqual(dsh["continuityScope"], "persistent_native_session")
        self.assertTrue(dsh["canResumeAcrossRuntimeRestart"])
        self.assertEqual(dsh["cancelScope"], "none")
        self.assertEqual(dsh["maxConcurrentOperations"], 1)
        self.assertTrue(dsh["existingSessionImport"])
        self.assertEqual(
            dsh["runtimeLossEffect"],
            "runtime_generation_unavailable_resume_required",
        )
        self.assertTrue(dsh["capabilities"]["canReadOwnedLiveStatus"])
        self.assertFalse(dsh["capabilities"]["canSupplementActiveTurn"])

    def test_deepseek_harness_backend_is_explicit_and_never_falls_back(self) -> None:
        selection = resolve_provider_backend("deepseek_harness")

        self.assertIs(
            selection.effective_backend,
            ProviderBackendId.DEEPSEEK_HARNESS_SDK_STDIO,
        )
        self.assertFalse(selection.fallback_applied)
        with self.assertRaisesRegex(ValueError, "managed_runtime"):
            resolve_provider_backend(
                "deepseek_harness",
                deepseek_harness_activation_backend="headless",
            )

    def test_codex_default_and_explicit_backend_selection_do_not_fallback(self) -> None:
        default = resolve_provider_backend(
            "codex",
            codex_activation_backend="exec_resume",
            source="default",
        )
        app_server = resolve_provider_backend(
            "codex",
            codex_activation_backend="app_server",
            source="explicit_cli",
        )

        self.assertIs(default.effective_backend, ProviderBackendId.CODEX_EXEC_RESUME)
        self.assertIs(
            app_server.effective_backend,
            ProviderBackendId.CODEX_APP_SERVER_STDIO,
        )
        self.assertFalse(default.fallback_applied)
        self.assertFalse(app_server.fallback_applied)
        self.assertNotIn("fallbackReason", app_server.to_metadata())

    def test_claude_default_and_agent_sdk_selection_do_not_fallback(self) -> None:
        default = resolve_provider_backend("claude")
        sdk = resolve_provider_backend(
            "claude",
            claude_activation_backend="agent_sdk",
            source="explicit_cli",
        )

        self.assertIs(default.effective_backend, ProviderBackendId.CLAUDE_CLI)
        self.assertIs(sdk.effective_backend, ProviderBackendId.CLAUDE_AGENT_SDK)
        self.assertFalse(default.fallback_applied)
        self.assertFalse(sdk.fallback_applied)
        self.assertEqual(sdk.source, "explicit_cli")

    def test_hermes_default_and_tui_gateway_selection_do_not_fallback(self) -> None:
        default = resolve_provider_backend("hermes")
        gateway = resolve_provider_backend(
            "hermes",
            hermes_activation_backend="tui_gateway",
            source="explicit_cli",
        )

        self.assertIs(default.effective_backend, ProviderBackendId.HERMES_CLI)
        self.assertIs(
            gateway.effective_backend,
            ProviderBackendId.HERMES_TUI_GATEWAY_STDIO,
        )
        self.assertFalse(gateway.fallback_applied)
        self.assertEqual(gateway.descriptor.status_authority.value, "point_read")
        self.assertTrue(gateway.descriptor.capabilities.can_cancel)

    def test_callable_adapter_reuses_existing_executor(self) -> None:
        selection = resolve_provider_backend("claude")
        called: list[str] = []
        adapter = CallableProviderBackendAdapter(
            selection=selection,
            executor=lambda: called.append("executed") or {"ok": True},
        )

        self.assertEqual(adapter.execute_inline(), {"ok": True})
        self.assertEqual(called, ["executed"])

    def test_managed_runtime_scaffold_tracks_threads_independently(self) -> None:
        bindings = ManagedRuntimeBindingSet()
        bindings.bind_thread(
            ManagedRuntimeThreadBinding(
                thread_id="thread-a",
                workspace_root="C:/same-project",
            )
        )
        bindings.bind_thread(
            ManagedRuntimeThreadBinding(
                thread_id="thread-b",
                workspace_root="C:/same-project",
            )
        )

        self.assertNotEqual(
            bindings.lock_for("thread-a"),
            bindings.lock_for("thread-b"),
        )
        metadata = bindings.to_metadata()
        self.assertFalse(metadata["implemented"])
        self.assertFalse(metadata["processManaged"])
        self.assertEqual(metadata["lockScope"], "thread_id")
        self.assertEqual(
            [item["threadId"] for item in metadata["bindings"]],
            ["thread-a", "thread-b"],
        )


if __name__ == "__main__":
    unittest.main()
