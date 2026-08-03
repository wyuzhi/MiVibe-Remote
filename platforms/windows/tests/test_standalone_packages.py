from __future__ import annotations

from pathlib import Path
import ast
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source"
SETUP = ROOT / "delivery" / "standalone" / "setup"


class StandalonePackageTests(unittest.TestCase):
    def test_three_independent_entries_exist(self) -> None:
        for name in ("xiaomi_main.py", "t1_main.py", "v60_main.py"):
            self.assertTrue((SOURCE / "standalone" / name).is_file(), name)

    def test_t1_and_v60_enable_native_audio(self) -> None:
        for name in ("t1_main.py", "v60_main.py"):
            text = (SOURCE / "standalone" / name).read_text(encoding="utf-8")
            self.assertIn('REMOTE_BRIDGE_AUDIO_TRANSPORT", "native"', text)
            self.assertNotIn("VB-CABLE", text)

    def test_xiaomi_owns_a_separate_config_and_runtime_root(self) -> None:
        text = (SOURCE / "standalone" / "xiaomi_main.py").read_text(encoding="utf-8")
        self.assertIn('REMOTE_BRIDGE_XIAOMI_APP_ID", APP_ID', text)
        self.assertIn('REMOTE_BRIDGE_XIAOMI_RUNTIME_ID", APP_ID', text)
        self.assertNotIn("from bridges.t1", text)
        self.assertNotIn("from bridges.hanvon", text)

    def test_default_build_only_targets_mivibe_remote(self) -> None:
        text = (ROOT / "delivery" / "build-standalone-packages.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn('[string] $Version = "0.1.9"', text)
        self.assertIn('[string[]] $Product = @("xiaomi")', text)
        self.assertIn('Folder = "MiVibeRemote"', text)
        self.assertIn('Exe = "MiVibeRemote.exe"', text)
        self.assertIn('OutputPrefix = "MiVibeRemoteSetup"', text)
        self.assertIn('Checksum = $checksumPath', text)

    def test_xiaomi_settings_has_redistributable_remote_fallback(self) -> None:
        text = (
            SOURCE / "bridges" / "xiaomi" / "xiaomi_settings.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def _draw_remote_silhouette", text)
        self.assertIn("self._draw_remote_silhouette()", text)
        self.assertIn("原创遥控器示意图", text)

    def test_xiaomi_installer_does_not_change_global_microphone_or_privacy(self) -> None:
        text = (
            SETUP / "configure-xiaomi-audio.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertNotIn("Set-DefaultCableMicrophone", text)
        self.assertNotIn("CapabilityAccessManager\\ConsentStore\\microphone", text)
        self.assertIn(
            '"System default microphone: preserved when Windows allows restoration"',
            text,
        )
        self.assertIn('"Microphone privacy settings: unchanged"', text)
        self.assertIn("$exitCode = 1", text)
        self.assertIn("exit $exitCode", text)

    def test_xiaomi_voice_driver_uses_vendor_setup_and_does_not_block_app_install(self) -> None:
        text = (SETUP / "configure-xiaomi-audio.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn('"VBCABLE_Setup_x64.exe"', text)
        self.assertIn("Invoke-OfficialInstaller", text)
        self.assertNotIn("RootDeviceInstaller", text)
        install_body = text.split('"Install" {', 1)[1].split('"Finish" {', 1)[0]
        self.assertNotIn("Invoke-OfficialInstaller", install_body)
        self.assertIn("optional third-party audio driver", install_body)

    def test_specs_do_not_cross_ship_other_hardware_bridges(self) -> None:
        expected = {
            "XiaomiRemoteBridge.spec": ('"bridges.t1"', '"bridges.hanvon"'),
            "T1RemoteBridge.spec": ('"bridges.xiaomi"', '"bridges.hanvon"'),
            "V60PenBridge.spec": ('"bridges.xiaomi"', '"bridges.t1"'),
        }
        for spec_name, exclusions in expected.items():
            text = (SOURCE / spec_name).read_text(encoding="utf-8")
            for exclusion in exclusions:
                self.assertIn(exclusion, text, spec_name)

    def test_pyinstaller_specs_are_valid_python(self) -> None:
        for spec_name in (
            "RemoteBridgeHub.spec",
            "XiaomiRemoteBridge.spec",
            "T1RemoteBridge.spec",
            "V60PenBridge.spec",
        ):
            text = (SOURCE / spec_name).read_text(encoding="utf-8")
            ast.parse(text, filename=spec_name)

    def test_specs_exclude_licensing_and_protection_modules(self) -> None:
        for spec_name in (
            "XiaomiRemoteBridge.spec",
            "T1RemoteBridge.spec",
            "V60PenBridge.spec",
        ):
            text = (SOURCE / spec_name).read_text(encoding="utf-8")
            self.assertIn('"licensing"', text, spec_name)
            self.assertIn('"customer_license"', text, spec_name)

        build_script = (ROOT / "delivery" / "build-standalone-packages.ps1").read_text(
            encoding="utf-8"
        )
        for marker in ("customer_(entry|license)", "licensing", "hardened", "nuitka"):
            self.assertIn(marker, build_script)

    @unittest.skipUnless(SETUP.is_dir(), "standalone installer sources are not staged")
    def test_only_xiaomi_installer_handles_vb_cable_without_bundling_it(self) -> None:
        common = (SETUP / "StandaloneBridgeSetup.common.iss").read_text(encoding="utf-8")
        self.assertIn('#if ProductKind == "xiaomi"', common)
        self.assertNotIn("VBCABLE_Driver_Pack45.zip", common)
        audio_setup = (
            SETUP / "configure-xiaomi-audio.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertIn(
            "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip",
            audio_setup,
        )
        self.assertIn("VB-CABLE download hash mismatch", audio_setup)
        fetch_script = (
            ROOT / "scripts" / "fetch-third-party.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertNotIn("VBCABLE_Driver_Pack45.zip", fetch_script)
        for name in ("readme-t1.txt", "readme-v60.txt"):
            text = (SETUP / name).read_text(encoding="utf-8")
            self.assertIn("不需要 VB-CABLE", text)

    @unittest.skipUnless(SETUP.is_dir(), "standalone installer sources are not staged")
    def test_customer_docs_explicitly_exclude_input_method_and_speech_recognition(self) -> None:
        for name in ("readme-xiaomi.txt", "readme-t1.txt", "readme-v60.txt"):
            text = (SETUP / name).read_text(encoding="utf-8")
            self.assertIn("不包含", text)
            self.assertIn("输入法", text)
            self.assertIn("语音识别", text)

    def test_v60_fix_filters_injected_keyboard_edges(self) -> None:
        text = (SOURCE / "bridges" / "physical_hotkey_monitor.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("LLKHF_INJECTED", text)
        self.assertIn("This monitor never suppresses", text)


if __name__ == "__main__":
    unittest.main()
