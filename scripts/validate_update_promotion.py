#!/usr/bin/env python3
"""Fail-closed validation for promoting MiVibe stable update feeds."""

from __future__ import annotations

import argparse
import json
import plistlib
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"
STABLE_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){2}$")
BUILD_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*$")
MAC_ASSET_RE = re.compile(r"^MiVibe-Remote-.*\.dmg$")
WINDOWS_ASSET_RE = re.compile(r"^MiVibeRemoteSetup-.*\.exe$")
NOT_READY_EXIT_CODE = 3


def _numeric_version(value: str, *, label: str) -> tuple[int, ...]:
    value = value.strip()
    if not BUILD_VERSION_RE.fullmatch(value):
        raise ValueError(f"{label} must be a dot-separated numeric version: {value!r}")
    return tuple(int(component) for component in value.split("."))


def _compare_numeric_versions(left: str, right: str, *, label: str) -> int:
    left_parts = _numeric_version(left, label=f"new {label}")
    right_parts = _numeric_version(right, label=f"current {label}")
    width = max(len(left_parts), len(right_parts))
    normalized_left = left_parts + (0,) * (width - len(left_parts))
    normalized_right = right_parts + (0,) * (width - len(right_parts))
    return (normalized_left > normalized_right) - (
        normalized_left < normalized_right
    )


def _windows_version(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION\s*=\s*"(?P<version>[^"]+)"', text, re.MULTILINE)
    if match is None or not STABLE_VERSION_RE.fullmatch(match.group("version")):
        raise ValueError("Windows APP_VERSION must be a stable numeric version")
    return match.group("version")


def expected_assets(
    release_tag: str, mac_plist: Path, windows_source: Path
) -> dict[str, str]:
    tag_match = re.fullmatch(r"v(?P<version>[0-9]+(?:\.[0-9]+){2})", release_tag)
    if tag_match is None:
        raise ValueError(
            "stable release tag must be vMAJOR.MINOR.PATCH with numeric components"
        )
    windows_version = _windows_version(windows_source)

    with mac_plist.open("rb") as stream:
        plist = plistlib.load(stream)
    mac_version = str(plist.get("CFBundleShortVersionString", "")).strip()
    mac_build_version = str(plist.get("CFBundleVersion", "")).strip()
    if not STABLE_VERSION_RE.fullmatch(mac_version):
        raise ValueError(
            "CFBundleShortVersionString must be MAJOR.MINOR.PATCH for stable updates"
        )
    _numeric_version(mac_build_version, label="CFBundleVersion")

    return {
        "releaseTag": release_tag,
        "windowsVersion": windows_version,
        "windowsFilename": f"MiVibeRemoteSetup-{windows_version}.exe",
        "macVersion": mac_version,
        "macBuildVersion": mac_build_version,
        "macFilename": f"MiVibe-Remote-{mac_version}.dmg",
    }


def _read_metadata(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "releaseTag",
        "windowsVersion",
        "windowsFilename",
        "macVersion",
        "macBuildVersion",
        "macFilename",
    }
    if not isinstance(payload, dict) or not required.issubset(payload):
        raise ValueError("promotion metadata is missing required fields")
    if not all(isinstance(payload[key], str) for key in required):
        raise ValueError("promotion metadata fields must be strings")
    return payload


def validate_release_assets(
    metadata: dict[str, str], asset_names: list[str]
) -> bool:
    mac_candidates = [name for name in asset_names if MAC_ASSET_RE.fullmatch(name)]
    windows_candidates = [
        name for name in asset_names if WINDOWS_ASSET_RE.fullmatch(name)
    ]
    unexpected = [
        name
        for name in (*mac_candidates, *windows_candidates)
        if name not in {metadata["macFilename"], metadata["windowsFilename"]}
    ]
    if unexpected:
        raise ValueError(
            "release contains installer assets for the wrong version: "
            + ", ".join(sorted(unexpected))
        )
    return (
        mac_candidates == [metadata["macFilename"]]
        and windows_candidates == [metadata["windowsFilename"]]
    )


def validate_local_assets(metadata: dict[str, str], directory: Path) -> None:
    asset_names = sorted(path.name for path in directory.iterdir() if path.is_file())
    if not validate_release_assets(metadata, asset_names):
        raise ValueError("downloaded release does not contain both expected installers")


def _appcast_version(path: Path, *, platform: str) -> str:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise ValueError(f"invalid {platform} appcast XML: {path}") from error
    item = root.find("./channel/item")
    if item is None:
        raise ValueError(f"{platform} appcast has no update item")
    version = item.findtext(f"{{{SPARKLE_NS}}}version")
    enclosure = item.find("enclosure")
    enclosure_version = (
        enclosure.attrib.get(f"{{{SPARKLE_NS}}}version")
        if enclosure is not None
        else None
    )
    if not version or not enclosure_version or version != enclosure_version:
        raise ValueError(
            f"{platform} appcast version is missing or inconsistent with enclosure"
        )
    return version.strip()


def validate_upgrade(
    *,
    new_macos_appcast: Path,
    new_windows_appcast: Path,
    current_macos_appcast: Path | None,
    current_windows_appcast: Path | None,
) -> None:
    current_paths = (current_macos_appcast, current_windows_appcast)
    if (current_paths[0] is None) != (current_paths[1] is None):
        raise ValueError(
            "stable update origin is inconsistent: exactly one current feed is missing"
        )
    if current_paths[0] is None:
        return

    new_mac = _appcast_version(new_macos_appcast, platform="macOS")
    new_windows = _appcast_version(new_windows_appcast, platform="Windows")
    current_mac = _appcast_version(current_paths[0], platform="current macOS")
    current_windows = _appcast_version(
        current_paths[1], platform="current Windows"
    )
    comparisons = (
        ("macOS CFBundleVersion", new_mac, current_mac),
        ("Windows version", new_windows, current_windows),
    )
    increased = False
    for label, new_version, current_version in comparisons:
        comparison = _compare_numeric_versions(new_version, current_version, label=label)
        if comparison < 0:
            raise ValueError(
                f"{label} cannot go backwards: current={current_version}, "
                f"new={new_version}"
            )
        increased = increased or comparison > 0
    if not increased:
        raise ValueError("at least one platform version must strictly increase")


def _write_json(payload: dict[str, str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    expected = subparsers.add_parser("expected-assets")
    expected.add_argument("--release-tag", required=True)
    expected.add_argument("--mac-plist", type=Path, required=True)
    expected.add_argument("--windows-source", type=Path, required=True)
    expected.add_argument("--output", type=Path, required=True)

    release_assets = subparsers.add_parser("check-release-assets")
    release_assets.add_argument("--metadata", type=Path, required=True)
    release_assets.add_argument("--asset-names", type=Path, required=True)

    local_assets = subparsers.add_parser("check-local-assets")
    local_assets.add_argument("--metadata", type=Path, required=True)
    local_assets.add_argument("--directory", type=Path, required=True)

    upgrade = subparsers.add_parser("check-upgrade")
    upgrade.add_argument("--new-macos-appcast", type=Path, required=True)
    upgrade.add_argument("--new-windows-appcast", type=Path, required=True)
    upgrade.add_argument("--current-macos-appcast", type=Path)
    upgrade.add_argument("--current-windows-appcast", type=Path)
    return parser


def run(args: argparse.Namespace) -> int:
    if args.command == "expected-assets":
        _write_json(
            expected_assets(args.release_tag, args.mac_plist, args.windows_source),
            args.output,
        )
        return 0
    if args.command == "check-release-assets":
        metadata = _read_metadata(args.metadata)
        names = args.asset_names.read_text(encoding="utf-8").splitlines()
        return 0 if validate_release_assets(metadata, names) else NOT_READY_EXIT_CODE
    if args.command == "check-local-assets":
        validate_local_assets(_read_metadata(args.metadata), args.directory)
        return 0
    if args.command == "check-upgrade":
        validate_upgrade(
            new_macos_appcast=args.new_macos_appcast,
            new_windows_appcast=args.new_windows_appcast,
            current_macos_appcast=args.current_macos_appcast,
            current_windows_appcast=args.current_windows_appcast,
        )
        return 0
    raise AssertionError(f"unexpected command: {args.command}")


def main() -> int:
    try:
        return run(build_parser().parse_args())
    except (OSError, ValueError, json.JSONDecodeError, plistlib.InvalidFileException) as error:
        print(f"validate_update_promotion: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
