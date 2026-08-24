from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "source"
sys.path.insert(0, str(SOURCE))

from standalone.environment_check import evaluate_environment


class EnvironmentCheckTests(unittest.TestCase):
    def _fixture(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "support").mkdir()
        (root / "support" / "configure-xiaomi-audio.ps1").write_text(
            "# fixture", encoding="utf-8"
        )
        config = root / "xiaomi.json"
        config.write_text(json.dumps({"voice_hotkey": ["ctrl", "win"]}), encoding="utf-8")
        logs = root / "logs"
        logs.mkdir()
        (logs / "bridge.log").write_text(
            "XIAOMI HID TAP READY pid=1234", encoding="utf-8"
        )
        return temporary, root, config, logs

    def test_ready_environment_passes_all_core_checks(self) -> None:
        temporary, root, config, logs = self._fixture()
        self.addCleanup(temporary.cleanup)
        results = evaluate_environment(
            app_dir=root,
            config_path=config,
            log_dir=logs,
            worker_status={"bridge_alive": True, "audio_alive": True},
            audio_devices=[
                {"name": "CABLE Input (VB-Audio Virtual Cable)", "max_output_channels": 2},
                {"name": "CABLE Output (VB-Audio Virtual Cable)", "max_input_channels": 2},
            ],
            platform_name="Windows",
            platform_release="11",
        )

        by_key = {item.key: item for item in results}
        self.assertEqual(by_key["vb_cable"].status, "pass")
        self.assertEqual(by_key["workers"].status, "pass")
        self.assertEqual(by_key["remote"].status, "pass")
        self.assertFalse([item for item in results if item.status == "fail"])

    def test_missing_capture_endpoint_produces_actionable_failure(self) -> None:
        temporary, root, config, logs = self._fixture()
        self.addCleanup(temporary.cleanup)
        results = evaluate_environment(
            app_dir=root,
            config_path=config,
            log_dir=logs,
            worker_status={"bridge_alive": True, "audio_alive": True},
            audio_devices=[
                {"name": "CABLE Input (VB-Audio Virtual Cable)", "max_output_channels": 2},
            ],
            platform_name="Windows",
            platform_release="10",
        )

        cable = next(item for item in results if item.key == "vb_cable")
        self.assertEqual(cable.status, "fail")
        self.assertIn("CABLE Output", cable.detail)
        self.assertIn("安装/修复语音驱动", cable.action)


if __name__ == "__main__":
    unittest.main()
