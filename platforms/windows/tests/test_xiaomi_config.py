import json
import sys
from pathlib import Path
import tempfile
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

    def test_wechat_preset_opens_wechat_and_holds_ctrl_win_for_voice(self) -> None:
        bindings = xiaomi_config.wechat_button_bindings()

        self.assertEqual(bindings["power"][0]["type"], "command")
        self.assertEqual(bindings["power"][0]["label"], "打开微信")
        command = bindings["power"][0]["args"][-1]
        self.assertIn("Get-StartApps", command)
        self.assertIn("'微信', 'WeChat'", command)
        self.assertIn("WeChat.exe", command)
        self.assertEqual(bindings["mic"][0]["keys"], ["ctrl", "win"])
        self.assertEqual(bindings["ok"][0]["keys"], ["enter"])
        self.assertEqual(bindings["back"][0]["keys"], ["backspace"])
        self.assertEqual(bindings["menu"][0]["keys"], ["esc"])
        self.assertEqual(xiaomi_config.WECHAT_VOICE_TRIGGER_MODE, "hold")
        self.assertEqual(
            xiaomi_config.resolve_hotkey_virtual_keys(
                xiaomi_config.WECHAT_VOICE_HOTKEY
            ),
            [0x11, 0x5B],
        )

    def test_qianwen_preset_opens_qwenwork_and_toggles_right_ctrl(self) -> None:
        bindings = xiaomi_config.qianwen_button_bindings()

        self.assertEqual(bindings["power"][0]["type"], "command")
        self.assertEqual(bindings["power"][0]["label"], "打开千问办公")
        command = bindings["power"][0]["args"][-1]
        self.assertIn("'千问办公', 'QwenWork'", command)
        self.assertIn("QwenWork.exe", command)
        self.assertEqual(bindings["mic"][0]["keys"], ["rightctrl"])
        self.assertEqual(xiaomi_config.QIANWEN_VOICE_TRIGGER_MODE, "toggle")
        self.assertEqual(
            xiaomi_config.resolve_hotkey_virtual_keys(
                xiaomi_config.QIANWEN_VOICE_HOTKEY
            ),
            [0xA3],
        )
        self.assertEqual(
            xiaomi_config.hotkey_injection_method(
                xiaomi_config.QIANWEN_VOICE_HOTKEY
            ),
            "scan_code",
        )

    def test_cycle_preset_wraps_and_preserves_the_configured_switch_button(self) -> None:
        config = default_config()
        keys = default_keys_config()
        keys["button_bindings"]["tv"] = [
            {"type": "preset_cycle", "label": "循环切换预设"}
        ]

        active = xiaomi_config.cycle_preset_configuration(config, keys)

        self.assertEqual(active, "workbuddy")
        self.assertEqual(config["active_preset"], "workbuddy")
        self.assertEqual(config["voice_trigger_mode"], "toggle")
        self.assertEqual(config["voice_hotkey"], "ctrl+d")
        self.assertEqual(
            keys["button_bindings"]["power"][0]["label"],
            "打开 WorkBuddy",
        )
        self.assertEqual(
            keys["button_bindings"]["tv"][0]["type"],
            "preset_cycle",
        )

        active = xiaomi_config.cycle_preset_configuration(config, keys)

        self.assertEqual(active, "wechat")
        self.assertEqual(config["voice_trigger_mode"], "hold")
        self.assertEqual(config["voice_hotkey"], "ctrl+win")
        self.assertEqual(
            keys["button_bindings"]["power"][0]["label"],
            "打开微信",
        )
        self.assertEqual(keys["button_bindings"]["tv"][0]["type"], "preset_cycle")

        active = xiaomi_config.cycle_preset_configuration(config, keys)

        self.assertEqual(active, "qianwen")
        self.assertEqual(config["voice_trigger_mode"], "toggle")
        self.assertEqual(config["voice_hotkey"], "rightctrl")
        self.assertEqual(
            keys["button_bindings"]["power"][0]["label"],
            "打开千问办公",
        )
        self.assertEqual(keys["button_bindings"]["tv"][0]["type"], "preset_cycle")

        active = xiaomi_config.cycle_preset_configuration(config, keys)

        self.assertEqual(active, "codex")
        self.assertEqual(config["voice_trigger_mode"], "hold")
        self.assertEqual(config["voice_hotkey"], "rightalt")
        self.assertEqual(keys["button_bindings"]["tv"][0]["type"], "preset_cycle")

    def test_custom_preset_is_available_and_cycles_with_its_voice_settings(self) -> None:
        config = default_config()
        keys = default_keys_config()
        custom_id = "custom_customer"
        keys["custom_presets"][custom_id] = {
            "name": "我的办公",
            "voice_hotkey": "rightctrl",
            "voice_trigger_mode": "toggle",
            "voice_shortcut_enabled": True,
        }
        keys["preset_bindings"][custom_id] = xiaomi_config.qianwen_button_bindings()
        config["active_preset"] = "qianwen"
        keys["button_bindings"] = xiaomi_config.qianwen_button_bindings()

        active = xiaomi_config.cycle_preset_configuration(config, keys)

        self.assertEqual(active, custom_id)
        self.assertEqual(config["voice_hotkey"], "rightctrl")
        self.assertEqual(config["voice_trigger_mode"], "toggle")
        self.assertIn(custom_id, xiaomi_config.available_preset_order(keys))

    def test_each_preset_keeps_its_saved_custom_mapping(self) -> None:
        config = default_config()
        keys = default_keys_config()
        keys["button_bindings"]["menu"] = [
            {"type": "hotkey", "keys": ["f8"]}
        ]

        xiaomi_config.apply_preset_configuration(config, keys, "workbuddy")
        keys["button_bindings"]["volume_up"] = [
            {"type": "hotkey", "keys": ["ctrl", "z"]}
        ]
        xiaomi_config.apply_preset_configuration(config, keys, "codex")

        self.assertEqual(
            keys["button_bindings"]["menu"][0]["keys"], ["f8"]
        )
        xiaomi_config.apply_preset_configuration(config, keys, "workbuddy")
        self.assertEqual(
            keys["button_bindings"]["volume_up"][0]["keys"],
            ["ctrl", "z"],
        )

    def test_saved_active_preset_and_mappings_survive_reload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "xiaomi.json"
            keys_path = root / "xiaomi_keys.json"
            config = default_config()
            keys = default_keys_config()
            xiaomi_config.apply_preset_configuration(
                config, keys, "workbuddy"
            )
            keys["button_bindings"]["menu"] = [
                {"type": "hotkey", "keys": ["f8"]}
            ]
            xiaomi_config.save_preset_button_bindings(
                keys, "workbuddy", keys["button_bindings"]
            )
            xiaomi_config.save_config(config, config_path)
            xiaomi_config.save_keys_config(keys, keys_path)

            loaded_config = xiaomi_config.load_config(config_path)
            loaded_keys = xiaomi_config.load_keys_config(keys_path)

            self.assertEqual(loaded_config["active_preset"], "workbuddy")
            self.assertEqual(
                loaded_keys["button_bindings"]["menu"][0]["keys"],
                ["f8"],
            )
            self.assertEqual(
                loaded_keys["preset_bindings"]["workbuddy"]["menu"][0][
                    "keys"
                ],
                ["f8"],
            )

    def test_schema_two_upgrade_adds_qianwen_without_changing_saved_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            keys_path = Path(temp_dir) / "xiaomi_keys.json"
            legacy = default_keys_config()
            legacy["mapping_schema_version"] = 2
            legacy["preset_bindings"].pop("qianwen")
            legacy["preset_bindings"]["wechat"]["menu"] = [
                {"type": "hotkey", "keys": ["f8"]}
            ]
            keys_path.write_text(json.dumps(legacy), encoding="utf-8")

            migrated = xiaomi_config.load_keys_config(keys_path)

            self.assertEqual(
                migrated["preset_bindings"]["wechat"]["menu"][0]["keys"],
                ["f8"],
            )
            self.assertEqual(
                migrated["preset_bindings"]["qianwen"]["mic"][0]["keys"],
                ["rightctrl"],
            )

    def test_custom_preset_survives_reload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            keys_path = Path(temp_dir) / "xiaomi_keys.json"
            keys = default_keys_config()
            custom_id = "custom_local"
            keys["custom_presets"][custom_id] = {
                "name": "我的千问",
                "voice_hotkey": "rightctrl",
                "voice_trigger_mode": "toggle",
                "voice_shortcut_enabled": True,
            }
            keys["preset_bindings"][custom_id] = (
                xiaomi_config.qianwen_button_bindings()
            )
            xiaomi_config.save_keys_config(keys, keys_path)

            loaded = xiaomi_config.load_keys_config(keys_path)

            self.assertEqual(
                loaded["custom_presets"][custom_id]["name"], "我的千问"
            )
            self.assertEqual(
                loaded["custom_presets"][custom_id]["voice_hotkey"],
                "rightctrl",
            )
            self.assertEqual(
                loaded["preset_bindings"][custom_id]["mic"][0]["keys"],
                ["rightctrl"],
            )

    def test_schema_one_mapping_migrates_into_active_preset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "xiaomi.json").write_text(
                json.dumps({"active_preset": "wechat"}), encoding="utf-8"
            )
            legacy = default_keys_config()
            legacy["mapping_schema_version"] = 1
            legacy.pop("preset_bindings", None)
            legacy["button_bindings"]["tv"] = [
                {"type": "hotkey", "keys": ["f9"]}
            ]
            keys_path = root / "xiaomi_keys.json"
            keys_path.write_text(json.dumps(legacy), encoding="utf-8")

            migrated = xiaomi_config.load_keys_config(keys_path)

            self.assertEqual(
                migrated["preset_bindings"]["wechat"]["tv"][0]["keys"],
                ["f9"],
            )

    def test_special_key_alias_migration_adds_all_windows_variants(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            keys_path = Path(temp_dir) / "xiaomi_keys.json"
            legacy = default_keys_config()
            legacy["button_aliases"]["volume_up"] = [
                "kbd:VK_AF:SC_000:E0:down"
            ]
            keys_path.write_text(json.dumps(legacy), encoding="utf-8")

            migrated = xiaomi_config.load_keys_config(keys_path)

            self.assertIn(
                "kbd:VK_AF:SC_000:N:down",
                migrated["button_aliases"]["volume_up"],
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

    def test_side_specific_modifier_uses_scan_code_injection(self):
        self.assertEqual(
            xiaomi_config.hotkey_injection_method(["leftctrl", "z"]),
            "scan_code",
        )
        self.assertEqual(
            xiaomi_config.hotkey_injection_method(["ctrl", "z"]),
            "virtual_key",
        )


if __name__ == "__main__":
    unittest.main()
