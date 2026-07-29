#!/bin/zsh
set -euo pipefail

ROOT="${0:A:h:h}"
CONFIGURATION="${CONFIGURATION:-release}"
APP_NAME="RemoteMic"
DISPLAY_NAME="MiVibe Remote"
OUTPUT_DIR="$ROOT/dist"
APP_DIR="$OUTPUT_DIR/$DISPLAY_NAME.app"
SIGNING_IDENTITY="${CODE_SIGN_IDENTITY:--}"

if [[ "$#" -ne 0 ]]; then
  print -u2 "usage: $0"
  exit 1
fi

cd "$ROOT"

xcrun swift build -c "$CONFIGURATION" --triple arm64-apple-macosx26.0
BIN_PATH="$(xcrun swift build -c "$CONFIGURATION" --triple arm64-apple-macosx26.0 --show-bin-path)/$APP_NAME"

case "$APP_DIR" in
  "$ROOT/dist/"*.app) ;;
  *) print -u2 "refusing to clean unexpected app path: $APP_DIR"; exit 1 ;;
esac
rm -rf -- "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"
ditto --norsrc --noextattr --noqtn --noacl \
  "$BIN_PATH" "$APP_DIR/Contents/MacOS/$APP_NAME"
strip -S -x "$APP_DIR/Contents/MacOS/$APP_NAME"
ditto --norsrc --noextattr --noqtn --noacl \
  "$ROOT/Resources/Info.plist" "$APP_DIR/Contents/Info.plist"
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
ditto --norsrc --noextattr --noqtn --noacl \
  "$ROOT/Resources/虚拟麦克风说明.md" \
  "$APP_DIR/Contents/Resources/虚拟麦克风说明.md"
if [[ "$SIGNING_IDENTITY" != "-" ]]; then
  codesign --force --deep --timestamp=none --sign "$SIGNING_IDENTITY" "$APP_DIR"
fi
if [[ "$SIGNING_IDENTITY" == "-" ]]; then
  BUNDLE_IDENTIFIER="$(plutil -extract CFBundleIdentifier raw -o - "$APP_DIR/Contents/Info.plist")"
  codesign \
    --force \
    --deep \
    --timestamp=none \
    --sign - \
    "$APP_DIR"
  codesign \
    --force \
    --timestamp=none \
    --sign - \
    --requirements "=designated => identifier \"$BUNDLE_IDENTIFIER\"" \
    "$APP_DIR"
fi
codesign --verify --deep --strict "$APP_DIR"

print "$APP_DIR"
print "SIGNING IDENTITY: $SIGNING_IDENTITY"
