import sys
from pathlib import Path
import unittest


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "source"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from bridges.xiaomi import xiaomi_config  # noqa: E402
from bridges.xiaomi.xiaomi_config import (  # noqa: E402
    DEFAULT_ADDRESS,
    apply_remote_identity,
    default_config,
    default_keys_config,
    device_token_from_address,
    normalize_bluetooth_address,
)


class XiaomiConfigTests(unittest.TestCase):
    def test_codex_preset_opens_codex_and_keeps_send_navigation(self) -> None:
        bindings = xiaomi_config.codex_button_bindings()

        self.assertEqual(bindings["power"][0]["type"], "command")
        self.assertEqual(bindings["power"][0]["label"], "打开 Codex")
        command = bindings["power"][0]["args"][-1]
        self.assertIn("Get-StartApps", command)
        self.assertIn("'Codex', 'ChatGPT'", command)
        self.assertIn("Start-Process 'codex:'", command)
        self.assertEqual(bindings["ok"][0]["keys"], ["enter"])
        self.assertEqual(bindings["up"][0]["keys"], ["up"])
        self.assertEqual(bindings["down"][0]["keys"], ["down"])
        self.assertEqual(bindings["back"][0]["keys"], ["backspace"])
        self.assertEqual(bindings["menu"][0]["keys"], ["esc"])
        self.assertEqual(bindings["mic"][0]["keys"], list(xiaomi_config.CODEX_VOICE_HOTKEY))
        self.assertEqual(xiaomi_config.CODEX_VOICE_TRIGGER_MODE, "hold")
        self.assertEqual(default_config()["voice_trigger_mode"], "hold")
        self.assertEqual(default_config()["active_preset"], "codex")
        self.assertEqual(default_keys_config()["button_bindings"]["power"][0]["type"], "command")
        self.assertEqual(
            default_keys_config()["button_bindings"]["power"][0]["label"],
            "打开 Codex",
        )

    def test_workbuddy_preset_opens_workbuddy_and_uses_toggle_voice(self) -> None:
        bindings = xiaomi_config.workbuddy_button_bindings()

        self.assertEqual(bindings["power"][0]["type"], "command")
        self.assertEqual(bindings["power"][0]["label"], "打开 WorkBuddy")
        command = bindings["power"][0]["args"][-1]
        self.assertIn("Get-StartApps", command)
        self.assertIn("'WorkBuddy'", command)
        self.assertIn("Start-Process 'workbuddy:'", command)
        self.assertEqual(bindings["mic"][0]["keys"], ["ctrl", "d"])
        self.assertEqual(bindings["ok"][0]["keys"], ["enter"])
        self.assertEqual(bindings["back"][0]["keys"], ["backspace"])
        self.assertEqual(bindings["menu"][0]["keys"], ["esc"])
        self.assertEqual(xiaomi_config.WORKBUDDY_VOICE_TRIGGER_MODE, "toggle")
        self.assertEqual(
            xiaomi_config.resolve_hotkey_virtual_keys(
                xiaomi_config.WORKBUDDY_VOICE_HOTKEY
            ),
            [0x11, ord("D")],
        )

    def test_normalizes_supported_address_formats(self):
        self.assertEqual(
            normalize_bluetooth_address("aa-bb-cc-dd-ee-ff"),
            "AA:BB:CC:DD:EE:FF",
        )
        self.assertEqual(
            normalize_bluetooth_address("aabbccddeeff"),
            "AA:BB:CC:DD:EE:FF",
        )

    def test_rejects_missing_or_invalid_address(self):
        for value in ("", "AA:BB", "GG:BB:CC:DD:EE:FF"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_bluetooth_address(value)

    def test_device_filter_is_derived_from_address(self):
        address = "AA:BB:CC:DD:EE:FF"
        config = default_config()
        keys_config = default_keys_config()
        self.assertEqual(device_token_from_address(address), "aabbccddeeff")
        self.assertEqual(apply_remote_identity(config, keys_config, address), address)
        self.assertEqual(config["address"], address)
        self.assertEqual(keys_config["device_match"], ["aabbccddeeff"])

    def test_defaults_do_not_embed_a_user_device(self):
        self.assertEqual(DEFAULT_ADDRESS, "")
        self.assertEqual(default_config()["address"], "")
        self.assertEqual(default_keys_config()["device_match"], [])
        self.assertFalse(hasattr(xiaomi_config, "LEGACY_TEST_ADDRESS"))


if __name__ == "__main__":
    unittest.main()
