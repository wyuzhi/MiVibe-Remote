from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

WINDOWS = Path(__file__).resolve().parents[1]
SOURCE = WINDOWS / "source"
ABOUT_ASSETS = WINDOWS.parent / "shared" / "about"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from standalone.about_info import (
    ABOUT_IMAGE_FILENAMES,
    SOCIAL_PROFILES,
    WECHAT_ID,
    about_image_path,
    about_resource_root,
    load_about_image,
)
from standalone.about_window import (
    AboutWindow,
    about_window_size,
    detail_window_size,
)


class AboutResourceTests(unittest.TestCase):
    def test_author_images_are_valid_original_jpegs(self) -> None:
        expected_sizes = {
            "AuthorDouyin.jpg": (1125, 1125),
            "AuthorXiaohongshu.jpg": (987, 987),
        }
        self.assertEqual(ABOUT_IMAGE_FILENAMES, frozenset(expected_sizes))
        for filename, expected_size in expected_sizes.items():
            path = ABOUT_ASSETS / filename
            self.assertTrue(path.is_file(), filename)
            with Image.open(path) as image:
                self.assertEqual(image.format, "JPEG")
                self.assertEqual(image.size, expected_size)
                image.verify()

    def test_display_loader_resizes_without_rewriting_source(self) -> None:
        for profile in SOCIAL_PROFILES:
            source = ABOUT_ASSETS / profile.image_filename
            before = hashlib.sha256(source.read_bytes()).digest()
            display = load_about_image(profile.image_filename, 220)
            detail = load_about_image(profile.image_filename, 680)
            after = hashlib.sha256(source.read_bytes()).digest()
            self.assertLessEqual(max(display.size), 220)
            self.assertEqual(max(detail.size), 680)
            self.assertEqual(display.mode, "RGB")
            self.assertEqual(before, after)

    def test_resource_resolver_handles_source_and_pyinstaller_layouts(self) -> None:
        with mock.patch.object(sys, "_MEIPASS", None, create=True):
            self.assertEqual(about_resource_root(), ABOUT_ASSETS)
            self.assertEqual(
                about_image_path("AuthorDouyin.jpg"),
                ABOUT_ASSETS / "AuthorDouyin.jpg",
            )
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            mock.patch.object(sys, "_MEIPASS", temp_dir, create=True),
        ):
            self.assertEqual(
                about_resource_root(),
                Path(temp_dir) / "about",
            )

    def test_resource_resolver_rejects_unexpected_paths(self) -> None:
        with self.assertRaises(ValueError):
            about_image_path("../private.txt")
        with self.assertRaises(ValueError):
            load_about_image("AuthorDouyin.jpg", 0)


class AboutWindowTests(unittest.TestCase):
    def test_repeated_show_activates_existing_toplevel(self) -> None:
        existing = mock.Mock()
        existing.winfo_exists.return_value = 1
        about = AboutWindow(
            mock.Mock(),
            "MiVibe Remote",
            "0.1.16",
            mock.Mock(),
            mock.Mock(),
        )
        about.window = existing
        with mock.patch.object(about, "_build") as build:
            about.show()
        build.assert_not_called()
        existing.deiconify.assert_called_once_with()
        existing.lift.assert_called_once_with()
        existing.focus_force.assert_called_once_with()

    def test_copy_wechat_updates_clipboard_and_feedback(self) -> None:
        owner = mock.Mock()
        about = AboutWindow(
            owner,
            "MiVibe Remote",
            "0.1.16",
            mock.Mock(),
            mock.Mock(),
        )
        feedback = mock.Mock()
        about.feedback = feedback
        about.copy_wechat()
        owner.clipboard_clear.assert_called_once_with()
        owner.clipboard_append.assert_called_once_with(WECHAT_ID)
        feedback.set.assert_called_once_with("已复制微信号 wydyid")

    def test_preferred_size_is_constrained_to_the_screen(self) -> None:
        self.assertEqual(about_window_size(1920, 1080), (680, 700))
        self.assertEqual(about_window_size(640, 480), (592, 384))
        self.assertEqual(about_window_size(300, 300), (300, 300))
        self.assertEqual(detail_window_size(1920, 1080), (760, 820))
        self.assertEqual(detail_window_size(640, 480), (592, 400))
        self.assertEqual(detail_window_size(300, 300), (300, 300))
        with self.assertRaises(ValueError):
            about_window_size(0, 1080)
        with self.assertRaises(ValueError):
            detail_window_size(1920, 0)

    def test_repeated_detail_show_reuses_window_and_replaces_content(self) -> None:
        existing = mock.Mock()
        existing.winfo_exists.return_value = 1
        about = AboutWindow(
            mock.Mock(),
            "MiVibe Remote",
            "0.1.16",
            mock.Mock(),
            mock.Mock(),
        )
        about.detail_window = existing
        about.detail_content = mock.Mock()
        about.detail_canvas = mock.Mock()
        with (
            mock.patch.object(about, "_render_social_detail") as render,
            mock.patch.object(about, "_build_social_detail") as build,
        ):
            about.show_social_detail(SOCIAL_PROFILES[1])
        render.assert_called_once_with(SOCIAL_PROFILES[1])
        build.assert_not_called()
        existing.deiconify.assert_called_once_with()
        existing.lift.assert_called_once_with()
        existing.focus_force.assert_called_once_with()

    def test_windows_host_and_spec_expose_about_entry_and_assets(self) -> None:
        host = (SOURCE / "standalone" / "xiaomi_main.py").read_text(
            encoding="utf-8"
        )
        about = (SOURCE / "standalone" / "about_window.py").read_text(
            encoding="utf-8"
        )
        spec = (SOURCE / "XiaomiRemoteBridge.spec").read_text(encoding="utf-8")
        self.assertIn('text="关于"', host)
        self.assertIn('"关于 MiVibe Remote"', host)
        self.assertIn("AUTHOR_LINE", host)
        self.assertIn("self.about.show()", host)
        self.assertIn('text="检查更新"', about)
        self.assertIn('text="复制微信号"', about)
        self.assertIn('text="查看大图"', about)
        self.assertIn('text="关闭"', about)
        self.assertIn('detail.bind("<Escape>"', about)
        self.assertIn("detail_button.bind(", about)
        self.assertIn("self.photos.append(photo)", about)
        self.assertIn("self.detail_photo = photo", about)
        self.assertIn("AuthorDouyin.jpg", spec)
        self.assertIn("AuthorXiaohongshu.jpg", spec)
        self.assertIn('(str(author_douyin), "about")', spec)
        self.assertIn('(str(author_xiaohongshu), "about")', spec)


if __name__ == "__main__":
    unittest.main()
