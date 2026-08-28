from __future__ import annotations

import plistlib
import tempfile
import unittest
from pathlib import Path

from scripts.validate_update_promotion import (
    expected_assets,
    validate_local_assets,
    validate_release_assets,
    validate_upgrade,
)

SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"


def write_appcast(path: Path, version: str) -> None:
    path.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="{SPARKLE_NS}">
  <channel><item>
    <sparkle:version>{version}</sparkle:version>
    <enclosure sparkle:version="{version}" url="https://updates.test/file" />
  </item></channel>
</rss>
""",
        encoding="utf-8",
    )


class ValidateUpdatePromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.plist = self.root / "Info.plist"
        with self.plist.open("wb") as stream:
            plistlib.dump(
                {
                    "CFBundleShortVersionString": "0.1.10",
                    "CFBundleVersion": "11",
                },
                stream,
            )
        self.windows_source = self.root / "xiaomi_main.py"
        self.windows_source.write_text('APP_VERSION = "0.1.19"\n', encoding="utf-8")
        self.metadata = expected_assets(
            "v0.1.20", self.plist, self.windows_source
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_expected_asset_names_follow_independent_platform_versions(self) -> None:
        self.assertEqual(self.metadata["releaseTag"], "v0.1.20")
        self.assertEqual(self.metadata["windowsVersion"], "0.1.19")
        self.assertEqual(
            self.metadata["windowsFilename"], "MiVibeRemoteSetup-0.1.19.exe"
        )
        self.assertEqual(self.metadata["macVersion"], "0.1.10")
        self.assertEqual(self.metadata["macBuildVersion"], "11")
        self.assertEqual(self.metadata["macFilename"], "MiVibe-Remote-0.1.10.dmg")

    def test_non_stable_or_malformed_tag_is_rejected(self) -> None:
        for tag in ("0.1.16", "v0.1", "v0.1.16-beta.1", "update-feed"):
            with self.subTest(tag=tag), self.assertRaisesRegex(ValueError, "tag"):
                expected_assets(tag, self.plist, self.windows_source)

    def test_release_assets_must_have_exact_expected_versions(self) -> None:
        self.assertTrue(
            validate_release_assets(
                self.metadata,
                [self.metadata["macFilename"], self.metadata["windowsFilename"]],
            )
        )
        self.assertFalse(validate_release_assets(self.metadata, []))
        with self.assertRaisesRegex(ValueError, "wrong version"):
            validate_release_assets(
                self.metadata,
                ["MiVibe-Remote-0.1.9.dmg", self.metadata["windowsFilename"]],
            )
        with self.assertRaisesRegex(ValueError, "wrong version"):
            validate_release_assets(
                self.metadata,
                [self.metadata["macFilename"], "MiVibeRemoteSetup-0.1.15.exe"],
            )

    def test_downloaded_directory_is_validated_again(self) -> None:
        download = self.root / "download"
        download.mkdir()
        (download / self.metadata["macFilename"]).write_bytes(b"dmg")
        (download / self.metadata["windowsFilename"]).write_bytes(b"exe")
        validate_local_assets(self.metadata, download)
        (download / self.metadata["windowsFilename"]).unlink()
        with self.assertRaisesRegex(ValueError, "both expected"):
            validate_local_assets(self.metadata, download)

    def test_first_promotion_without_current_feeds_is_allowed(self) -> None:
        new_mac = self.root / "new-mac.xml"
        new_windows = self.root / "new-windows.xml"
        write_appcast(new_mac, "11")
        write_appcast(new_windows, "0.1.16")
        validate_upgrade(
            new_macos_appcast=new_mac,
            new_windows_appcast=new_windows,
            current_macos_appcast=None,
            current_windows_appcast=None,
        )

    def test_platform_versions_may_advance_independently_but_never_rollback(self) -> None:
        paths = {
            name: self.root / f"{name}.xml"
            for name in ("new_mac", "new_windows", "old_mac", "old_windows")
        }
        write_appcast(paths["new_mac"], "11")
        write_appcast(paths["new_windows"], "0.1.16")
        write_appcast(paths["old_mac"], "10")
        write_appcast(paths["old_windows"], "0.1.15")
        validate_upgrade(
            new_macos_appcast=paths["new_mac"],
            new_windows_appcast=paths["new_windows"],
            current_macos_appcast=paths["old_mac"],
            current_windows_appcast=paths["old_windows"],
        )

        write_appcast(paths["old_mac"], "11")
        validate_upgrade(
            new_macos_appcast=paths["new_mac"],
            new_windows_appcast=paths["new_windows"],
            current_macos_appcast=paths["old_mac"],
            current_windows_appcast=paths["old_windows"],
        )
        write_appcast(paths["old_mac"], "10")
        write_appcast(paths["old_windows"], "0.1.16")
        validate_upgrade(
            new_macos_appcast=paths["new_mac"],
            new_windows_appcast=paths["new_windows"],
            current_macos_appcast=paths["old_mac"],
            current_windows_appcast=paths["old_windows"],
        )

        write_appcast(paths["old_mac"], "11")
        with self.assertRaisesRegex(ValueError, "at least one"):
            validate_upgrade(
                new_macos_appcast=paths["new_mac"],
                new_windows_appcast=paths["new_windows"],
                current_macos_appcast=paths["old_mac"],
                current_windows_appcast=paths["old_windows"],
            )

    def test_rollback_and_partial_existing_feed_are_rejected(self) -> None:
        new_mac = self.root / "new-mac.xml"
        new_windows = self.root / "new-windows.xml"
        old_mac = self.root / "old-mac.xml"
        old_windows = self.root / "old-windows.xml"
        write_appcast(new_mac, "10")
        write_appcast(new_windows, "0.1.15")
        write_appcast(old_mac, "11")
        write_appcast(old_windows, "0.1.16")
        with self.assertRaisesRegex(ValueError, "cannot go backwards"):
            validate_upgrade(
                new_macos_appcast=new_mac,
                new_windows_appcast=new_windows,
                current_macos_appcast=old_mac,
                current_windows_appcast=old_windows,
            )
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            validate_upgrade(
                new_macos_appcast=new_mac,
                new_windows_appcast=new_windows,
                current_macos_appcast=old_mac,
                current_windows_appcast=None,
            )


if __name__ == "__main__":
    unittest.main()
