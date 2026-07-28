from __future__ import annotations

import sys
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "source"))

import remote_bridge_hub as hub  # noqa: E402


def widget_texts(widget: tk.Misc) -> list[str]:
    values: list[str] = []
    for child in widget.winfo_children():
        try:
            text = str(child.cget("text"))
        except tk.TclError:
            text = ""
        if text:
            values.append(text)
        values.extend(widget_texts(child))
    return values


class FakeManager:
    def __init__(self) -> None:
        self.config = {"community_url": hub.DEFAULT_COMMUNITY_URL}
        self.bridges = {
            name: SimpleNamespace(spec=SimpleNamespace(name=label))
            for name, label in (
                ("xiaomi", "小米蓝牙遥控器 2 Pro"),
                ("t1", "T1 遥控器"),
                ("hanvon", "汉王语音笔"),
            )
        }

    @staticmethod
    def enabled(_bridge_id: str) -> bool:
        return True


class CommunityEntryTests(unittest.TestCase):
    def test_xiaomi_hid_injector_is_an_allowed_internal_role(self) -> None:
        self.assertIn("xiaomi-hid-injector", hub.INTERNAL_ROLES)

    def test_bridge_toggle_labels_make_enabled_state_explicit(self) -> None:
        self.assertEqual(hub.bridge_toggle_label(True), "✓ 已启用")
        self.assertEqual(hub.bridge_toggle_label(False), "○ 已停用")

    def test_missing_voice_driver_keeps_normal_buttons_available(self) -> None:
        text = hub.audio_status_text(False, 20)
        self.assertIn("语音驱动未就绪", text)
        self.assertIn("普通按键仍可使用", text)

    def test_internal_role_failure_is_logged_instead_of_escaping(self) -> None:
        with (
            patch.object(hub, "run_internal_role", side_effect=RuntimeError("simulated")),
            patch.object(hub, "app_log") as logged,
            patch("builtins.print"),
        ):
            result = hub.run_internal_role_safely("audio", [])
        self.assertEqual(result, 70)
        self.assertIn("internal role failed role=audio", logged.call_args.args[0])

    def test_default_config_uses_stable_https_community_url(self) -> None:
        config = hub.default_config()
        self.assertEqual(config["community_url"], hub.DEFAULT_COMMUNITY_URL)
        self.assertTrue(config["community_url"].startswith("https://"))

    def test_community_url_rejects_insecure_or_credentialed_values(self) -> None:
        self.assertEqual(hub.validated_community_url("http://join.example/group"), "")
        self.assertEqual(hub.validated_community_url("https://user:pass@join.example/group"), "")
        self.assertEqual(hub.validated_community_url("not a url"), "")
        self.assertEqual(
            hub.validated_community_url("https://join.example/group"),
            "https://join.example/group",
        )

    def test_open_community_page_uses_the_system_browser(self) -> None:
        with patch.object(hub.webbrowser, "open", return_value=True) as opened:
            self.assertTrue(hub.open_community_page("https://join.example/group"))
        opened.assert_called_once_with("https://join.example/group", new=2)

    def test_main_window_has_a_permanent_community_entry(self) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            application = object.__new__(hub.HubApplication)
            application.root = root
            application.manager = FakeManager()
            application.status_labels = {}
            application.audio_status_var = tk.StringVar(
                value=hub.audio_status_text(False, None)
            )
            application.enabled_vars = {}
            application.toggle_labels = {}
            application.toggle_buttons = {}
            application._build_window()
            root.update_idletasks()
            texts = widget_texts(root)
            self.assertIn("用户社群", texts)
            self.assertIn("查看微信二维码", texts)
            self.assertEqual(
                {value.get() for value in application.toggle_labels.values()},
                {"✓ 已启用"},
            )
            self.assertTrue(
                all(widget.winfo_class() == "TButton" for widget in application.toggle_buttons.values())
            )
            self.assertLessEqual(root.winfo_reqheight(), root.winfo_screenheight())
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
