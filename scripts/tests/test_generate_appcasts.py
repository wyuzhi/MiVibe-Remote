from __future__ import annotations

import base64
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from argparse import Namespace
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.generate_appcasts import SPARKLE_NS, generate


class GenerateAppcastsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.mac = self.root / "MiVibe-Remote-1.2.3.dmg"
        self.windows = self.root / "MiVibeRemoteSetup-4.5.6.exe"
        self.mac.write_bytes(b"mac update bytes")
        self.windows.write_bytes(b"windows update bytes")
        self.seed = bytes(range(1, 33))
        self.key_file = self.root / "private.key"
        self.key_file.write_text(base64.b64encode(self.seed).decode("ascii"))
        self.output = self.root / "output"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def args(self, **overrides: object) -> Namespace:
        values: dict[str, object] = {
            "mac_asset": self.mac,
            "windows_asset": self.windows,
            "private_key_file": self.key_file,
            "base_url": "https://updates.example.test/mivibe",
            "output_dir": self.output,
            "mac_version": None,
            "mac_build_version": "123",
            "windows_version": None,
            "windows_build_version": None,
            "mac_minimum_system_version": "15.0",
            "windows_minimum_system_version": "10.0.17763",
            "release_notes_file": None,
            "published_at": "2026-08-13T10:00:00Z",
            "expected_public_key": None,
            "allow_http": False,
        }
        values.update(overrides)
        return Namespace(**values)

    def test_generates_platform_feeds_and_verifiable_signatures(self) -> None:
        manifest = generate(self.args())
        public_key = Ed25519PrivateKey.from_private_bytes(self.seed).public_key()

        expected = {
            "macos": (self.mac, "123", "1.2.3"),
            "windows": (self.windows, "4.5.6", "4.5.6"),
        }
        namespace = {"sparkle": SPARKLE_NS}
        for platform, (asset, build_version, display_version) in expected.items():
            feed = ET.parse(self.output / f"{platform}-appcast.xml")
            enclosure = feed.find("./channel/item/enclosure")
            self.assertIsNotNone(enclosure)
            assert enclosure is not None
            signature = base64.b64decode(
                enclosure.attrib[f"{{{SPARKLE_NS}}}edSignature"]
            )
            public_key.verify(signature, asset.read_bytes())
            self.assertEqual(
                enclosure.attrib[f"{{{SPARKLE_NS}}}os"],
                "windows-x64" if platform == "windows" else platform,
            )
            self.assertEqual(
                feed.findtext("./channel/item/sparkle:version", namespaces=namespace),
                build_version,
            )
            self.assertEqual(
                feed.findtext(
                    "./channel/item/sparkle:shortVersionString",
                    namespaces=namespace,
                ),
                display_version,
            )
            self.assertEqual(
                enclosure.attrib[f"{{{SPARKLE_NS}}}version"], build_version
            )
            self.assertEqual(
                feed.findtext(
                    "./channel/item/sparkle:minimumSystemVersion",
                    namespaces=namespace,
                ),
                "10.0.17763" if platform == "windows" else "15.0",
            )
            if platform == "windows":
                self.assertEqual(
                    enclosure.attrib[f"{{{SPARKLE_NS}}}installerArguments"],
                    "/SILENT /SP- /NOICONS /CLOSEAPPLICATIONS "
                    "/RESTARTAPPLICATIONS /UPDATED",
                )
            else:
                self.assertNotIn(
                    f"{{{SPARKLE_NS}}}installerArguments", enclosure.attrib
                )
            self.assertTrue(enclosure.attrib["url"].startswith("https://"))

        serialized = "".join(
            path.read_text(encoding="utf-8") for path in self.output.iterdir()
        )
        self.assertNotIn(base64.b64encode(self.seed).decode("ascii"), serialized)
        disk_manifest = json.loads(
            (self.output / "update-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(disk_manifest, manifest)
        self.assertEqual(manifest["assets"]["macos"]["buildVersion"], "123")
        self.assertEqual(manifest["assets"]["macos"]["version"], "1.2.3")

    def test_rejects_insecure_download_origin(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            generate(self.args(base_url="http://updates.example.test"))

    def test_rejects_credentials_or_tokens_in_download_origin(self) -> None:
        for url in (
            "https://member:secret@updates.example.test/stable",
            "https://updates.example.test/stable?token=secret",
            "https://updates.example.test/stable#secret",
        ):
            with self.subTest(url=url), self.assertRaisesRegex(
                ValueError, "credentials"
            ):
                generate(self.args(base_url=url))

    def test_rejects_key_that_does_not_match_embedded_public_key(self) -> None:
        wrong_public_key = base64.b64encode(b"x" * 32).decode("ascii")
        with self.assertRaisesRegex(ValueError, "does not match"):
            generate(self.args(expected_public_key=wrong_public_key))

    def test_accepts_missing_publish_date_for_draft_release(self) -> None:
        manifest = generate(self.args(published_at=""))
        self.assertTrue(str(manifest["generatedAt"]).endswith("Z"))


if __name__ == "__main__":
    unittest.main()
