from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from agent_os.infrastructure.config import CoreSettings, DeferredFeatureSettings


class CoreSettingsTests(unittest.TestCase):
    def test_default_deferred_features_stay_disabled(self) -> None:
        settings = CoreSettings(
            workspace_root="workspace",
            plugins_directory="plugins",
        )

        self.assertFalse(settings.deferred_features.finite_round_discussion)
        self.assertFalse(settings.deferred_features.heartbeat)
        self.assertFalse(settings.deferred_features.convergence)
        self.assertFalse(settings.deferred_features.scheduler_heartbeat_path)
        self.assertFalse(settings.deferred_features.heartbeat_terminal_export_consumer)

    def test_deferred_features_can_be_enabled_only_by_explicit_override(self) -> None:
        deferred_features = DeferredFeatureSettings(
            heartbeat=True,
            convergence=True,
        )
        settings = CoreSettings(
            workspace_root="workspace",
            plugins_directory="plugins",
            deferred_features=deferred_features,
        )

        self.assertTrue(settings.deferred_features.heartbeat)
        self.assertTrue(settings.deferred_features.convergence)
        self.assertFalse(settings.deferred_features.finite_round_discussion)
        self.assertFalse(settings.deferred_features.scheduler_heartbeat_path)
        self.assertFalse(settings.deferred_features.heartbeat_terminal_export_consumer)


if __name__ == "__main__":
    unittest.main()
