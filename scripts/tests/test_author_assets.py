from __future__ import annotations

import hashlib
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = ROOT / "platforms" / "shared" / "about"


class AuthorAssetTests(unittest.TestCase):
    def test_original_social_qr_images_are_preserved_byte_for_byte(self) -> None:
        expected = {
            "AuthorDouyin.jpg": (
                "eb0e45a8ea2fc32e2787e9017ed27490d37412feedf17dde02248e53814df4e4"
            ),
            "AuthorXiaohongshu.jpg": (
                "620bc64208bb5e8e62e8c32245c11ab77dedebbeab70cae402f69da07000e727"
            ),
        }

        for filename, expected_digest in expected.items():
            payload = (ASSET_ROOT / filename).read_bytes()
            self.assertTrue(payload.startswith(b"\xff\xd8\xff"), filename)
            self.assertEqual(hashlib.sha256(payload).hexdigest(), expected_digest)


if __name__ == "__main__":
    unittest.main()
