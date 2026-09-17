from __future__ import annotations

from pathlib import Path
import ast
import os
import shutil
import subprocess
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
        self.assertIn('REMOTE_BRIDGE_XIAOMI_CONTROL_PORT", str(CONTROL_PORT)', text)
        self.assertIn('child_environment["PYTHONUTF8"] = "1"', text)
        self.assertIn('child_environment["PYTHONIOENCODING"] = "utf-8"', text)
        self.assertNotIn("from bridges.t1", text)
        self.assertNotIn("from bridges.hanvon", text)

    def test_xiaomi_host_exposes_and_cleans_up_online_updates(self) -> None:
        text = (SOURCE / "standalone" / "xiaomi_main.py").read_text(encoding="utf-8")
        self.assertIn("WinSparkleUpdater", text)
        self.assertIn('("检查更新", self.check_updates)', text)
        self.assertIn('pystray.MenuItem("检查更新"', text)
        self.assertIn("self.root.after(1500, self._start_updater)", text)
        self.assertIn("self.updater.cleanup()", text)
        self.assertIn("self._request_update_shutdown", text)
        self.assertIn("MainThreadShutdownBridge", text)
        self.assertIn("self._update_shutdown.request_and_wait()", text)
        self.assertIn("self._update_shutdown.dispatch_one(", text)
        self.assertIn("if not for_update:", text)

    def test_xiaomi_host_exposes_environment_check_and_in_app_guide(self) -> None:
        text = (SOURCE / "standalone" / "xiaomi_main.py").read_text(encoding="utf-8")
        self.assertIn("EnvironmentCheckWindow", text)
        self.assertIn('text="环境检查"', text)
        self.assertIn('text="使用教程"', text)
        self.assertIn("def show_guide", text)
        self.assertIn('self.root.geometry("820x540")', text)

    def test_xiaomi_settings_restart_is_confirmed_by_both_windows_hosts(self) -> None:
        settings = (
            SOURCE / "bridges" / "xiaomi" / "xiaomi_settings.py"
        ).read_text(encoding="utf-8")
        standalone = (SOURCE / "standalone" / "xiaomi_main.py").read_text(
            encoding="utf-8"
        )
        legacy_hub = (SOURCE / "remote_bridge_hub.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('"request_id": request_id', settings)
        self.assertIn("client.recvfrom(4096)", settings)
        self.assertIn("settings restart confirmed", standalone)
        self.assertIn('"restart_sync"', legacy_hub)
        self.assertIn("done.wait(8.0)", legacy_hub)

    def test_xiaomi_settings_window_is_single_instance(self) -> None:
        text = (
            SOURCE / "bridges" / "xiaomi" / "xiaomi_settings.py"
        ).read_text(encoding="utf-8")

        self.assertIn("def claim_settings_instance", text)
        self.assertIn("notify_existing_settings(port)", text)
        self.assertIn('name="xiaomi-settings-single-instance"', text)

    def test_default_build_only_targets_mivibe_remote(self) -> None:
        text = (ROOT / "delivery" / "build-standalone-packages.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn('[string] $Version = "0.1.21"', text)
        self.assertIn('[string[]] $Product = @("xiaomi")', text)
        self.assertIn('Folder = "MiVibeRemote"', text)
        self.assertIn('Exe = "MiVibeRemote.exe"', text)
        self.assertIn('OutputPrefix = "MiVibeRemoteSetup"', text)
        self.assertIn('Checksum = $checksumPath', text)
        self.assertIn("source declares $declaredVersion", text)
        self.assertIn("$Version = $declaredVersion", text)

    def test_xiaomi_settings_has_redistributable_remote_fallback(self) -> None:
        text = (
            SOURCE / "bridges" / "xiaomi" / "xiaomi_settings.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def _draw_remote_silhouette", text)
        self.assertIn("self._draw_remote_silhouette()", text)
        self.assertIn("MiVibe Remote 2", text)
        self.assertIn('fill="#d7d9db"', text)
        self.assertIn('text="MiVibe"', text)
        self.assertNotIn('text="xiaomi"', text)

    def test_xiaomi_settings_scrolls_on_short_windows_and_draws_silver_remote(self) -> None:
        text = (
            SOURCE / "bridges" / "xiaomi" / "xiaomi_settings.py"
        ).read_text(encoding="utf-8")
        self.assertIn('orient="vertical", command=page.yview', text)
        self.assertIn('self.root.bind("<MouseWheel>"', text)
        self.assertNotIn('self.root.minsize(1235, 900)', text)
        self.assertIn('fill="#d7d9db"', text)
        self.assertIn('text="MiVibe"', text)
        self.assertIn('text="MiVibe Remote"', text)
        self.assertIn('"PresetActive.TButton"', text)

    def test_side_specific_hotkeys_have_scan_code_sender(self) -> None:
        text = (SOURCE / "bridges" / "raw_input_bridge.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("KEYEVENTF_SCANCODE = 0x0008", text)
        self.assertIn("def send_scan_code_hotkey", text)
        self.assertIn("KEYBDINPUT(0, scan, flags, 0, 0)", text)

    def test_xiaomi_settings_offer_native_mouse_wheel_actions(self) -> None:
        settings = (
            SOURCE / "bridges" / "xiaomi" / "xiaomi_settings.py"
        ).read_text(encoding="utf-8")
        bridge = (SOURCE / "bridges" / "raw_input_bridge.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('text="滚轮向上"', settings)
        self.assertIn('text="滚轮向下"', settings)
        self.assertIn("def set_selected_to_mouse_wheel", settings)
        self.assertIn("MOUSEEVENTF_WHEEL = 0x0800", bridge)
        self.assertIn("def send_mouse_wheel", bridge)

    def test_xiaomi_voice_shortcut_uses_checked_scan_code_sender(self) -> None:
        text = (
            SOURCE / "bridges" / "xiaomi" / "atvv_live_bridge.py"
        ).read_text(encoding="utf-8")
        voice_shortcut = text.split("class VoiceShortcut:", 1)[1].split(
            "class VoicePcmStats:", 1
        )[0]

        self.assertIn("send_scan_code_vk", voice_shortcut)
        self.assertNotIn("keybd_event", voice_shortcut)

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
        self.assertIn("Microsoft Windows Hardware Compatibility Publisher", text)
        self.assertIn("BUREL VINCENT", text)
        self.assertIn("function Get-Sha256", text)
        self.assertNotIn("Get-FileHash", text)
        self.assertIn("[IO.Compression.ZipFile]::ExtractToDirectory", text)
        self.assertNotIn("Expand-Archive", text)
        installer_body = text.split("function Invoke-OfficialInstaller", 1)[1].split(
            "function Wait-VBCable", 1
        )[0]
        self.assertIn("Start-Process -FilePath $setup -Verb RunAs", installer_body)
        self.assertNotIn("-PassThru", installer_body)
        self.assertNotIn("-Wait", installer_body)
        self.assertNotIn("ExitCode", installer_body)
        repair_body = text.split('"Repair" {', 1)[1].split('"Restore" {', 1)[0]
        self.assertIn("Wait-VBCable 180", repair_body)

    @unittest.skipUnless(os.name == "nt", "Authenticode validation requires Windows")
    def test_official_vb_cable_package_has_expected_signers(self) -> None:
        script = SETUP / "configure-xiaomi-audio.ps1"
        powershell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
        self.assertIsNotNone(powershell)
        powershell_environment = os.environ.copy()
        # Let the selected shell initialize its own module search path instead
        # of inheriting one from the parent GitHub Actions shell.
        powershell_environment.pop("PSModulePath", None)
        completed = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Mode",
                "ValidatePackage",
                "-AppPath",
                str(ROOT),
                "-NonInteractive",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
            env=powershell_environment,
        )
        self.assertEqual(
            completed.returncode,
            0,
            f"stdout={completed.stdout}\nstderr={completed.stderr}",
        )

    def test_xiaomi_package_declares_runtime_winrt_projections(self) -> None:
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        spec = (SOURCE / "XiaomiRemoteBridge.spec").read_text(encoding="utf-8")
        build = (ROOT / "delivery" / "build-standalone-packages.ps1").read_text(
            encoding="utf-8-sig"
        )
        for projection in (
            "winrt-Windows.Foundation==3.2.1",
            "winrt-Windows.Foundation.Collections==3.2.1",
        ):
            self.assertIn(projection, requirements)
        for module in (
            "winrt.windows.foundation",
            "winrt.windows.foundation.collections",
        ):
            self.assertIn(module, spec)
            self.assertIn(module, build)

    def test_xiaomi_package_pins_winsparkle_and_generated_public_config(self) -> None:
        fetch = (ROOT / "scripts" / "fetch-third-party.ps1").read_text(
            encoding="utf-8-sig"
        )
        spec = (SOURCE / "XiaomiRemoteBridge.spec").read_text(encoding="utf-8")
        build = (ROOT / "delivery" / "build-standalone-packages.ps1").read_text(
            encoding="utf-8-sig"
        )
        updater = (SOURCE / "standalone" / "windows_update.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("WinSparkle-0.9.4.zip", fetch)
        self.assertIn(
            "6037DF37FC263BD1650A1C4949681A9D40FFE991D01F35892A406CB5D103C976",
            fetch,
        )
        self.assertIn(
            "9B43B1C16EE39FB9A91B5BD75138767898779510E0836BE2919250607CDBE8AB",
            fetch,
        )
        self.assertIn('(str(winsparkle_dll), ".")', spec)
        self.assertIn('(str(update_config), "update")', spec)
        self.assertIn("MIVIBE_APPCAST_URL", build)
        self.assertIn("MIVIBE_UPDATE_ED25519_PUBLIC_KEY", build)
        self.assertIn("must decode to a 32-byte Ed25519 public key", build)
        self.assertIn("exactly one WinSparkle.dll", build)
        self.assertIn("unexpected WinSparkle.dll", build)
        self.assertIn("exactly one generated update_config.json", build)
        self.assertNotIn("win_sparkle_set_http_header", updater)

    def test_xiaomi_online_update_is_an_in_place_driver_safe_upgrade(self) -> None:
        product = (SETUP / "XiaomiRemoteBridgeSetup.iss").read_text(encoding="utf-8")
        common = (SETUP / "StandaloneBridgeSetup.common.iss").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '#define SetupAppId "{{C87B7439-E849-47B9-A3AC-B35AC7986CE4}"',
            product,
        )
        self.assertIn("UsePreviousAppDir=yes", common)
        self.assertIn("UsePreviousTasks=yes", common)
        self.assertIn("HasCommandLineSwitch('/UPDATED')", common)
        self.assertIn("Check: not IsOnlineUpdate", common)
        self.assertIn("ShouldLaunchApplication", common)

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
        self.assertIn("Local\\MiVibeRemoteAudioSetup", audio_setup)
        self.assertIn("NewGuid().ToString('N')", audio_setup)
        self.assertIn("等待文件解除占用超时", audio_setup)
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
