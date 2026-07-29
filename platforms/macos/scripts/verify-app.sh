#!/bin/zsh
set -euo pipefail

ROOT="${0:A:h:h}"
if [[ "$#" -gt 1 ]]; then
  print -u2 "usage: $0 [APP]"
  exit 1
fi
APP="${1:-$ROOT/dist/MiVibe Remote.app}"
PLIST="$APP/Contents/Info.plist"
BINARY="$APP/Contents/MacOS/RemoteMic"

test -d "$APP"
test -f "$PLIST"
test -x "$BINARY"
test -f "$APP/Contents/Resources/LICENSE.md"
test -f "$APP/Contents/Resources/README.md"
test -f "$APP/Contents/Resources/THIRD_PARTY_NOTICES.md"
test -f "$APP/Contents/Resources/COPYRIGHT.md"
test -f "$APP/Contents/Resources/AppIcon.icns"
test -f "$APP/Contents/Resources/StatusIconTemplate.png"
test -f "$APP/Contents/Resources/StatusIconTemplate@2x.png"
test -f "$APP/Contents/Resources/StatusIconActiveTemplate.png"
test -f "$APP/Contents/Resources/StatusIconActiveTemplate@2x.png"
test -f "$APP/Contents/Resources/RemoteProduct.png"
test -f "$APP/Contents/Resources/虚拟麦克风说明.md"

test "$(plutil -extract CFBundleIdentifier raw -o - "$PLIST")" = \
  "com.mivibe.remote"
test "$(plutil -extract LSUIElement raw -o - "$PLIST")" = "false"
test "$(plutil -extract LSMinimumSystemVersion raw -o - "$PLIST")" = "26.0"
test "$(plutil -extract CFBundleIconFile raw -o - "$PLIST")" = "AppIcon"
test -n "$(plutil -extract NSBluetoothAlwaysUsageDescription raw -o - "$PLIST")"

codesign --verify --deep --strict "$APP"
file "$BINARY" | rg -q 'Mach-O 64-bit executable'
ARCHS="$(lipo -archs "$BINARY")"
test "$ARCHS" = "arm64"
xcrun vtool -show-build "$BINARY" | rg -q 'minos 26\.0'

EXPECTED_APP_FILES=$'Contents/Info.plist\nContents/MacOS/RemoteMic\nContents/Resources/AppIcon.icns\nContents/Resources/COPYRIGHT.md\nContents/Resources/LICENSE.md\nContents/Resources/README.md\nContents/Resources/RemoteProduct.png\nContents/Resources/StatusIconActiveTemplate.png\nContents/Resources/StatusIconActiveTemplate@2x.png\nContents/Resources/StatusIconTemplate.png\nContents/Resources/StatusIconTemplate@2x.png\nContents/Resources/THIRD_PARTY_NOTICES.md\nContents/Resources/虚拟麦克风说明.md\nContents/_CodeSignature/CodeResources'
while IFS= read -r expected_file; do
  test -f "$APP/$expected_file"
done <<< "$EXPECTED_APP_FILES"

if rg -a -q '/Users/[^/[:space:]]+|/tmp/remote-bridge|AA:BB:CC:DD:EE:FF' "$APP/Contents"; then
  print -u2 "bundle contains a forbidden local path or example device address"
  exit 1
fi

print "APP VERIFY PASS: $APP"
