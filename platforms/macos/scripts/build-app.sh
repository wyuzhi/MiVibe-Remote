#!/bin/zsh
set -euo pipefail

ROOT="${0:A:h:h}"
CONFIGURATION="${CONFIGURATION:-release}"
APP_NAME="RemoteMic"
DISPLAY_NAME="MiVibe Remote"
OUTPUT_DIR="$ROOT/dist"
APP_DIR="$OUTPUT_DIR/$DISPLAY_NAME.app"
SIGNING_IDENTITY="${CODE_SIGN_IDENTITY:--}"
SHARED_ABOUT_DIR="$ROOT/../shared/about"

if [[ "$#" -ne 0 ]]; then
  print -u2 "usage: $0"
  exit 1
fi

cd "$ROOT"

xcrun swift build -c "$CONFIGURATION" --triple arm64-apple-macosx15.0
BIN_PATH="$(xcrun swift build -c "$CONFIGURATION" --triple arm64-apple-macosx15.0 --show-bin-path)/$APP_NAME"
SPARKLE_FRAMEWORK="$ROOT/.build/artifacts/sparkle/Sparkle/Sparkle.xcframework/macos-arm64_x86_64/Sparkle.framework"

if [[ ! -d "$SPARKLE_FRAMEWORK" ]]; then
  print -u2 "Sparkle.framework not found after SwiftPM build: $SPARKLE_FRAMEWORK"
  exit 1
fi

case "$APP_DIR" in
  "$ROOT/dist/"*.app) ;;
  *) print -u2 "refusing to clean unexpected app path: $APP_DIR"; exit 1 ;;
esac
rm -rf -- "$APP_DIR"
mkdir -p \
  "$APP_DIR/Contents/MacOS" \
  "$APP_DIR/Contents/Resources" \
  "$APP_DIR/Contents/Frameworks"
ditto --norsrc --noextattr --noqtn --noacl \
  "$BIN_PATH" "$APP_DIR/Contents/MacOS/$APP_NAME"
strip -S -x "$APP_DIR/Contents/MacOS/$APP_NAME"
install_name_tool \
  -add_rpath "@executable_path/../Frameworks" \
  "$APP_DIR/Contents/MacOS/$APP_NAME"
ditto --norsrc --noextattr --noqtn --noacl \
  "$ROOT/Resources/Info.plist" "$APP_DIR/Contents/Info.plist"
if [[ -n "${MIVIBE_APPCAST_URL:-}" || -n "${MIVIBE_UPDATE_ED25519_PUBLIC_KEY:-}" ]]; then
  if [[ -z "${MIVIBE_APPCAST_URL:-}" || -z "${MIVIBE_UPDATE_ED25519_PUBLIC_KEY:-}" ]]; then
    print -u2 "MIVIBE_APPCAST_URL and MIVIBE_UPDATE_ED25519_PUBLIC_KEY must be set together"
    exit 1
  fi
  if [[ "$MIVIBE_APPCAST_URL" != https://* ]]; then
    print -u2 "MIVIBE_APPCAST_URL must use HTTPS"
    exit 1
  fi
  if ! python3 - "$MIVIBE_APPCAST_URL" <<'PY'
import sys
from urllib.parse import urlsplit

parsed = urlsplit(sys.argv[1])
if (
    not parsed.netloc
    or parsed.username
    or parsed.password
    or parsed.query
    or parsed.fragment
):
    raise SystemExit(1)
PY
  then
    print -u2 "MIVIBE_APPCAST_URL must not contain credentials, a query string, or a fragment"
    exit 1
  fi
  if ! DECODED_KEY_LENGTH="$(
    print -rn -- "$MIVIBE_UPDATE_ED25519_PUBLIC_KEY" \
      | base64 --decode 2>/dev/null \
      | wc -c \
      | tr -d '[:space:]'
  )" || [[ "$DECODED_KEY_LENGTH" != "32" ]]; then
    print -u2 "MIVIBE_UPDATE_ED25519_PUBLIC_KEY must be a 32-byte base64 Ed25519 public key"
    exit 1
  fi
  plutil -replace SUFeedURL -string "$MIVIBE_APPCAST_URL" \
    "$APP_DIR/Contents/Info.plist"
  plutil -replace SUPublicEDKey -string "$MIVIBE_UPDATE_ED25519_PUBLIC_KEY" \
    "$APP_DIR/Contents/Info.plist"
fi
ditto --norsrc --noextattr --noqtn --noacl \
  "$SPARKLE_FRAMEWORK" \
  "$APP_DIR/Contents/Frameworks/Sparkle.framework"
ditto --norsrc --noextattr --noqtn --noacl \
  "$ROOT/LICENSE.md" "$APP_DIR/Contents/Resources/LICENSE.md"
ditto --norsrc --noextattr --noqtn --noacl \
  "$ROOT/README.md" "$APP_DIR/Contents/Resources/README.md"
ditto --norsrc --noextattr --noqtn --noacl \
  "$ROOT/THIRD_PARTY_NOTICES.md" "$APP_DIR/Contents/Resources/THIRD_PARTY_NOTICES.md"
ditto --norsrc --noextattr --noqtn --noacl \
  "$ROOT/COPYRIGHT.md" "$APP_DIR/Contents/Resources/COPYRIGHT.md"
for icon_resource in \
  AppIcon.icns \
  RemoteProduct.png \
  StatusIconTemplate.png \
  StatusIconTemplate@2x.png \
  StatusIconActiveTemplate.png \
  StatusIconActiveTemplate@2x.png; do
  ditto --norsrc --noextattr --noqtn --noacl \
    "$ROOT/Resources/$icon_resource" \
    "$APP_DIR/Contents/Resources/$icon_resource"
done
for about_resource in AuthorDouyin.jpg AuthorXiaohongshu.jpg; do
  if [[ ! -f "$SHARED_ABOUT_DIR/$about_resource" ]]; then
    print -u2 "missing shared About resource: $SHARED_ABOUT_DIR/$about_resource"
    exit 1
  fi
  ditto --norsrc --noextattr --noqtn --noacl \
    "$SHARED_ABOUT_DIR/$about_resource" \
    "$APP_DIR/Contents/Resources/$about_resource"
done
ditto --norsrc --noextattr --noqtn --noacl \
  "$ROOT/Resources/虚拟麦克风说明.md" \
  "$APP_DIR/Contents/Resources/虚拟麦克风说明.md"
EMBEDDED_SPARKLE="$APP_DIR/Contents/Frameworks/Sparkle.framework"
SPARKLE_VERSION_DIR="$EMBEDDED_SPARKLE/Versions/B"
if [[ "$SIGNING_IDENTITY" == "-" ]]; then
  SIGN_TIMESTAMP=(--timestamp=none)
  # Hardened Runtime library validation requires every loaded framework to
  # carry the same real Developer ID team. An ad-hoc signature has no team,
  # so enabling runtime here makes dyld reject Sparkle at launch.
  # Local builds remain fully code-signed, but Hardened Runtime is reserved
  # for production builds signed with a Developer ID identity.
  SIGN_OPTIONS=()
else
  SIGN_TIMESTAMP=(--timestamp)
  SIGN_OPTIONS=(--options runtime)
fi

sign_sparkle_component() {
  local component="$1"
  shift
  codesign \
    --force \
    "${SIGN_OPTIONS[@]}" \
    "$@" \
    "${SIGN_TIMESTAMP[@]}" \
    --sign "$SIGNING_IDENTITY" \
    "$component"
}

# Sparkle 2.9.4's manual signing recipe preserves entitlements only on
# Downloader.xpc. In particular, do not carry Sparkle's upstream Autoupdate
# application identifier into a Developer ID signed release.
sign_sparkle_component \
  "$SPARKLE_VERSION_DIR/XPCServices/Installer.xpc"
sign_sparkle_component \
  "$SPARKLE_VERSION_DIR/XPCServices/Downloader.xpc" \
  --preserve-metadata=entitlements
sign_sparkle_component \
  "$SPARKLE_VERSION_DIR/Autoupdate"
sign_sparkle_component \
  "$SPARKLE_VERSION_DIR/Updater.app"
sign_sparkle_component \
  "$EMBEDDED_SPARKLE"
if [[ "$SIGNING_IDENTITY" == "-" ]]; then
  BUNDLE_IDENTIFIER="$(plutil -extract CFBundleIdentifier raw -o - "$APP_DIR/Contents/Info.plist")"
  codesign \
    --force \
    --timestamp=none \
    --sign - \
    "$APP_DIR/Contents/MacOS/$APP_NAME"
  codesign \
    --force \
    --timestamp=none \
    --sign - \
    --requirements "=designated => identifier \"$BUNDLE_IDENTIFIER\"" \
    "$APP_DIR"
else
  codesign \
    --force \
    --options runtime \
    --timestamp \
    --sign "$SIGNING_IDENTITY" \
    "$APP_DIR/Contents/MacOS/$APP_NAME"
  codesign \
    --force \
    --options runtime \
    --timestamp \
    --sign "$SIGNING_IDENTITY" \
    "$APP_DIR"
fi
codesign --verify --deep --strict "$APP_DIR"

print "$APP_DIR"
print "SIGNING IDENTITY: $SIGNING_IDENTITY"
