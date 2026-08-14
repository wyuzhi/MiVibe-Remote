"""Author and social-profile assets used by the Windows About window."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

AUTHOR_NAME = "起司"
WECHAT_ID = "wydyid"
AUTHOR_LINE = f"起司制作 · 微信 {WECHAT_ID}"


@dataclass(frozen=True)
class SocialProfile:
    platform: str
    handle: str
    account_id: str
    image_filename: str

    @property
    def accessible_text(self) -> str:
        return f"{self.platform} {self.handle}，账号 {self.account_id}"


SOCIAL_PROFILES = (
    SocialProfile("抖音", "@起司", "56257686125", "AuthorDouyin.jpg"),
    SocialProfile("小红书", "起司", "5668049267", "AuthorXiaohongshu.jpg"),
)
ABOUT_IMAGE_FILENAMES = frozenset(
    profile.image_filename for profile in SOCIAL_PROFILES
)


def about_resource_root() -> Path:
    """Resolve packaged resources without relying on the process working directory."""

    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root) / "about"
    return Path(__file__).resolve().parents[3] / "shared" / "about"


def about_image_path(filename: str) -> Path:
    if filename not in ABOUT_IMAGE_FILENAMES:
        raise ValueError(f"unsupported About image: {filename}")
    return about_resource_root() / filename


def load_about_image(filename: str, max_side: int) -> Image.Image:
    """Load and proportionally resize a display copy; never rewrite the source JPEG."""

    if max_side <= 0:
        raise ValueError("max_side must be positive")
    with Image.open(about_image_path(filename)) as source:
        display = ImageOps.exif_transpose(source).convert("RGB")
    display.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return display
