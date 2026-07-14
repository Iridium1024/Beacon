from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_os.application.services.provider_session_profile import (
    load_provider_session_registry,
    resolve_provider_session_registry_path,
    save_provider_session_registry,
)


class ProviderSessionRegistryPathTests(unittest.TestCase):
    def test_resolver_reports_stable_path_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            explicit = resolve_provider_session_registry_path(
                explicit=str(root / "explicit.json"),
            )
            profile = resolve_provider_session_registry_path(
                profile={"providerSessionRegistry": str(root / "profile.json")},
            )
            environment = resolve_provider_session_registry_path(
                environment={
                    "AGENT_OS_PROVIDER_SESSION_REGISTRY": str(root / "env.json")
                },
            )
            project = resolve_provider_session_registry_path(project_root=root)
            workspace = resolve_provider_session_registry_path(
                workspace_root=str(root / ".beacon" / "workspaces" / "one" / "workspace-root"),
            )
            cwd = resolve_provider_session_registry_path(cwd=root)

            self.assertEqual(explicit.registry_path_source, "explicit_cli")
            self.assertEqual(profile.registry_path_source, "profile")
            self.assertEqual(environment.registry_path_source, "environment")
            self.assertEqual(project.registry_path_source, "project_default")
            self.assertEqual(workspace.registry_path_source, "workspace_derived")
            self.assertEqual(cwd.registry_path_source, "cwd_default")
            self.assertFalse(explicit.exists)
            self.assertFalse(explicit.readable)
            self.assertTrue(explicit.writable)

    def test_atomic_save_preserves_unicode_and_old_file_on_replace_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry_path = Path(directory) / "nested" / "会话" / "registry.json"
            original = {
                "profiles": [{"profileAlias": "旧会话", "profileId": "old"}],
                "memberships": [],
            }
            save_provider_session_registry(registry_path, original)
            self.assertTrue(registry_path.exists())
            self.assertEqual(
                load_provider_session_registry(registry_path)["profiles"][0][
                    "profileAlias"
                ],
                "旧会话",
            )
            original_content = registry_path.read_text(encoding="utf-8")

            replacement = {
                "profiles": [{"profileAlias": "新会话", "profileId": "new"}],
                "memberships": [],
            }
            with patch(
                "agent_os.application.services.provider_session_profile.os.replace",
                side_effect=OSError("simulated replace failure"),
            ):
                with self.assertRaisesRegex(OSError, "simulated replace failure"):
                    save_provider_session_registry(registry_path, replacement)

            self.assertEqual(
                registry_path.read_text(encoding="utf-8"),
                original_content,
            )
            self.assertEqual(
                list(registry_path.parent.glob(f".{registry_path.name}.*.tmp")),
                [],
            )


if __name__ == "__main__":
    unittest.main()
