#!/usr/bin/env python3
"""Generate signed Sparkle 2 and WinSparkle appcasts.

The private Ed25519 key is read from a file and is never written to the output.
Both frameworks verify the same standard Ed25519 signature format, so a single
key pair can secure the two platform-specific feeds.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"
ET.register_namespace("sparkle", SPARKLE_NS)


@dataclass(frozen=True)
class UpdateAsset:
    platform: str
    path: Path
    display_version: str
    build_version: str
    minimum_system_version: str
    mime_type: str


def _sparkle(name: str) -> str:
    return f"{{{SPARKLE_NS}}}{name}"


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    material = path.read_bytes().strip()
    if not material:
        raise ValueError(f"private key file is empty: {path}")

    if material.startswith(b"-----BEGIN"):
        key = serialization.load_pem_private_key(material, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("private key is not an Ed25519 key")
        return key

    try:
        raw = base64.b64decode(material, validate=True)
    except ValueError as error:
        raise ValueError(
            "private key must be PKCS#8 PEM or a base64-encoded 32-byte seed"
        ) from error

    # Sparkle/WinSparkle exports may include the 32-byte public key after the seed.
    if len(raw) == 64:
        raw = raw[:32]
    if len(raw) != 32:
        raise ValueError(
            "base64 private key must decode to a 32-byte seed (or 64-byte keypair)"
        )
    return Ed25519PrivateKey.from_private_bytes(raw)


def _public_key_base64(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def _signature(private_key: Ed25519PrivateKey, path: Path) -> str:
    return base64.b64encode(private_key.sign(path.read_bytes())).decode("ascii")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _version_from_filename(path: Path, platform: str) -> str:
    patterns = {
        "macos": r"^MiVibe-Remote-(?P<version>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\.dmg$",
        "windows": r"^MiVibeRemoteSetup-(?P<version>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\.exe$",
    }
    match = re.fullmatch(patterns[platform], path.name)
    if match is None:
        raise ValueError(
            f"unexpected {platform} asset name {path.name!r}; cannot infer version"
        )
    return match.group("version")


def _https_base_url(value: str, *, allow_http: bool) -> str:
    value = value.rstrip("/")
    parsed = urlsplit(value)
    accepted_schemes = {"https"} | ({"http"} if allow_http else set())
    if parsed.scheme not in accepted_schemes or not parsed.netloc:
        expected = "HTTP(S)" if allow_http else "HTTPS"
        raise ValueError(f"base URL must be an absolute {expected} URL: {value!r}")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            "base URL must not contain credentials, a query string, or a fragment"
        )
    return value


def _asset_url(base_url: str, filename: str) -> str:
    parsed = urlsplit(base_url)
    path = f"{parsed.path.rstrip('/')}/{quote(filename)}"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _pub_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc).replace(microsecond=0)
    try:
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            result = parsedate_to_datetime(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid publication date: {value!r}") from error
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc).replace(microsecond=0)


def _make_feed(
    asset: UpdateAsset,
    *,
    base_url: str,
    signature: str,
    release_notes: str,
    published_at: datetime,
) -> ET.ElementTree:
    feed_name = f"{asset.platform}-appcast.xml"
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = (
        f"MiVibe Remote {asset.platform} updates"
    )
    ET.SubElement(channel, "link").text = _asset_url(base_url, feed_name)
    ET.SubElement(channel, "description").text = (
        f"Signed stable updates for MiVibe Remote on {asset.platform}."
    )
    ET.SubElement(channel, "language").text = "zh-CN"

    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = f"MiVibe Remote {asset.display_version}"
    ET.SubElement(item, "pubDate").text = format_datetime(published_at)
    if release_notes.strip():
        ET.SubElement(item, "description").text = release_notes.strip()
    ET.SubElement(item, _sparkle("version")).text = asset.build_version
    ET.SubElement(item, _sparkle("shortVersionString")).text = asset.display_version
    ET.SubElement(item, _sparkle("minimumSystemVersion")).text = (
        asset.minimum_system_version
    )

    # Keep version attributes on the enclosure as well as top-level elements.
    # This works with current Sparkle and with older WinSparkle parsers.
    enclosure_attributes = {
        "url": _asset_url(base_url, asset.path.name),
        "length": str(asset.path.stat().st_size),
        "type": asset.mime_type,
        _sparkle("version"): asset.build_version,
        _sparkle("shortVersionString"): asset.display_version,
        _sparkle("os"): (
            "windows-x64" if asset.platform == "windows" else asset.platform
        ),
        _sparkle("edSignature"): signature,
    }
    if asset.platform == "windows":
        enclosure_attributes[_sparkle("installerArguments")] = (
            "/SILENT /SP- /NOICONS /CLOSEAPPLICATIONS "
            "/RESTARTAPPLICATIONS /UPDATED"
        )
    ET.SubElement(item, "enclosure", enclosure_attributes)
    ET.indent(rss, space="  ")
    return ET.ElementTree(rss)


def _write_xml(tree: ET.ElementTree, path: Path) -> None:
    tree.write(path, encoding="utf-8", xml_declaration=True)
    with path.open("ab") as stream:
        stream.write(b"\n")


def generate(args: argparse.Namespace) -> dict[str, object]:
    base_url = _https_base_url(args.base_url, allow_http=args.allow_http)
    private_key = _load_private_key(args.private_key_file)
    public_key = _public_key_base64(private_key)
    if args.expected_public_key and not hmac.compare_digest(
        public_key, args.expected_public_key.strip()
    ):
        raise ValueError(
            "private key does not match UPDATE_ED25519_PUBLIC_KEY; refusing to publish"
        )

    mac_path = args.mac_asset.resolve(strict=True)
    windows_path = args.windows_asset.resolve(strict=True)
    assets = (
        UpdateAsset(
            platform="macos",
            path=mac_path,
            display_version=args.mac_version
            or _version_from_filename(mac_path, "macos"),
            build_version=args.mac_build_version,
            minimum_system_version=args.mac_minimum_system_version,
            mime_type="application/x-apple-diskimage",
        ),
        UpdateAsset(
            platform="windows",
            path=windows_path,
            display_version=args.windows_version
            or _version_from_filename(windows_path, "windows"),
            build_version=args.windows_build_version
            or args.windows_version
            or _version_from_filename(windows_path, "windows"),
            minimum_system_version=args.windows_minimum_system_version,
            mime_type="application/vnd.microsoft.portable-executable",
        ),
    )
    notes = (
        args.release_notes_file.read_text(encoding="utf-8")
        if args.release_notes_file
        else ""
    )
    published_at = _pub_date(args.published_at)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    manifest_assets: dict[str, object] = {}
    for asset in assets:
        signature = _signature(private_key, asset.path)
        feed_name = f"{asset.platform}-appcast.xml"
        _write_xml(
            _make_feed(
                asset,
                base_url=base_url,
                signature=signature,
                release_notes=notes,
                published_at=published_at,
            ),
            args.output_dir / feed_name,
        )
        manifest_assets[asset.platform] = {
            "version": asset.display_version,
            "buildVersion": asset.build_version,
            "feedURL": _asset_url(base_url, feed_name),
            "downloadURL": _asset_url(base_url, asset.path.name),
            "filename": asset.path.name,
            "length": asset.path.stat().st_size,
            "sha256": _sha256(asset.path),
            "edSignature": signature,
        }

    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "generatedAt": published_at.isoformat().replace("+00:00", "Z"),
        "baseURL": base_url,
        "ed25519PublicKey": public_key,
        "assets": manifest_assets,
    }
    (args.output_dir / "update-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mac-asset", type=Path, required=True)
    parser.add_argument("--windows-asset", type=Path, required=True)
    parser.add_argument("--private-key-file", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mac-version")
    parser.add_argument(
        "--mac-build-version",
        required=True,
        help="CFBundleVersion used by Sparkle for ordering macOS updates",
    )
    parser.add_argument("--windows-version")
    parser.add_argument(
        "--windows-build-version",
        help="optional WinSparkle build version; defaults to display version",
    )
    parser.add_argument("--mac-minimum-system-version", default="15.0")
    parser.add_argument("--windows-minimum-system-version", default="10.0.17763")
    parser.add_argument("--release-notes-file", type=Path)
    parser.add_argument("--published-at")
    parser.add_argument("--expected-public-key")
    parser.add_argument(
        "--allow-http",
        action="store_true",
        help="allow an HTTP base URL for local tests only",
    )
    return parser


def main() -> int:
    try:
        manifest = generate(build_parser().parse_args())
    except (OSError, ValueError) as error:
        print(f"generate_appcasts: {error}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
