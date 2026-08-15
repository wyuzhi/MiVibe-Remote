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
SPARKLE="$APP/Contents/Frameworks/Sparkle.framework"
SHARED_ABOUT_DIR="$ROOT/../shared/about"

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
test -f "$APP/Contents/Resources/AuthorDouyin.jpg"
test -f "$APP/Contents/Resources/AuthorXiaohongshu.jpg"
cmp -s \
  "$SHARED_ABOUT_DIR/AuthorDouyin.jpg" \
  "$APP/Contents/Resources/AuthorDouyin.jpg"
cmp -s \
  "$SHARED_ABOUT_DIR/AuthorXiaohongshu.jpg" \
  "$APP/Contents/Resources/AuthorXiaohongshu.jpg"
test -f "$APP/Contents/Resources/虚拟麦克风说明.md"
test -d "$SPARKLE"
test -x "$SPARKLE/Versions/B/Sparkle"
test -x "$SPARKLE/Versions/B/Autoupdate"
test -x "$SPARKLE/Versions/B/Updater.app/Contents/MacOS/Updater"
test -x "$SPARKLE/Versions/B/XPCServices/Installer.xpc/Contents/MacOS/Installer"
test -x "$SPARKLE/Versions/B/XPCServices/Downloader.xpc/Contents/MacOS/Downloader"

test "$(plutil -extract CFBundleIdentifier raw -o - "$PLIST")" = \
  "com.mivibe.remote"
test "$(plutil -extract LSUIElement raw -o - "$PLIST")" = "false"
test "$(plutil -extract LSMinimumSystemVersion raw -o - "$PLIST")" = "26.0"
test "$(plutil -extract CFBundleIconFile raw -o - "$PLIST")" = "AppIcon"
test -n "$(plutil -extract NSBluetoothAlwaysUsageDescription raw -o - "$PLIST")"
test "$(plutil -extract SUEnableAutomaticChecks raw -o - "$PLIST")" = "true"
test "$(plutil -extract SUAllowsAutomaticUpdates raw -o - "$PLIST")" = "false"
test "$(plutil -extract SUAutomaticallyUpdate raw -o - "$PLIST")" = "false"
test "$(plutil -extract SUScheduledCheckInterval raw -o - "$PLIST")" = "86400"

FEED_URL="$(plutil -extract SUFeedURL raw -o - "$PLIST" 2>/dev/null || true)"
PUBLIC_KEY="$(plutil -extract SUPublicEDKey raw -o - "$PLIST" 2>/dev/null || true)"
if [[ -n "$FEED_URL" || -n "$PUBLIC_KEY" ]]; then
  test -n "$FEED_URL"
  test -n "$PUBLIC_KEY"
  [[ "$FEED_URL" == https://* ]]
  test "$(
    print -rn -- "$PUBLIC_KEY" \
      | base64 --decode \
      | wc -c \
      | tr -d '[:space:]'
  )" = "32"
fi

codesign --verify --deep --strict "$APP"
codesign --verify --strict "$SPARKLE/Versions/B/XPCServices/Installer.xpc"
codesign --verify --strict "$SPARKLE/Versions/B/XPCServices/Downloader.xpc"
codesign --verify --strict "$SPARKLE/Versions/B/Autoupdate"
codesign --verify --strict "$SPARKLE/Versions/B/Updater.app"
codesign --verify --strict "$SPARKLE"
if codesign -d --entitlements :- "$SPARKLE/Versions/B/Autoupdate" 2>/dev/null \
  | rg -q 'org\.sparkle-project\.Sparkle\.Autoupdate'; then
  print -u2 "Autoupdate retained Sparkle's upstream application identifier"
  exit 1
fi
file "$BINARY" | rg -q 'Mach-O 64-bit executable'
ARCHS="$(lipo -archs "$BINARY")"
test "$ARCHS" = "arm64"
xcrun vtool -show-build "$BINARY" | rg -q 'minos 26\.0'
otool -L "$BINARY" | rg -q '@rpath/Sparkle\.framework/Versions/B/Sparkle'
otool -l "$BINARY" | rg -q '@executable_path/\.\./Frameworks'

EXPECTED_APP_FILES=$'Contents/Frameworks/Sparkle.framework/Versions/B/Autoupdate\nContents/Frameworks/Sparkle.framework/Versions/B/Sparkle\nContents/Frameworks/Sparkle.framework/Versions/B/Updater.app/Contents/MacOS/Updater\nContents/Frameworks/Sparkle.framework/Versions/B/XPCServices/Downloader.xpc/Contents/MacOS/Downloader\nContents/Frameworks/Sparkle.framework/Versions/B/XPCServices/Installer.xpc/Contents/MacOS/Installer\nContents/Info.plist\nContents/MacOS/RemoteMic\nContents/Resources/AppIcon.icns\nContents/Resources/AuthorDouyin.jpg\nContents/Resources/AuthorXiaohongshu.jpg\nContents/Resources/COPYRIGHT.md\nContents/Resources/LICENSE.md\nContents/Resources/README.md\nContents/Resources/RemoteProduct.png\nContents/Resources/StatusIconActiveTemplate.png\nContents/Resources/StatusIconActiveTemplate@2x.png\nContents/Resources/StatusIconTemplate.png\nContents/Resources/StatusIconTemplate@2x.png\nContents/Resources/THIRD_PARTY_NOTICES.md\nContents/Resources/虚拟麦克风说明.md\nContents/_CodeSignature/CodeResources'
while IFS= read -r expected_file; do
  test -f "$APP/$expected_file"
done <<< "$EXPECTED_APP_FILES"

if rg -a -q '/Users/[^/[:space:]]+|/tmp/remote-bridge|AA:BB:CC:DD:EE:FF' "$APP/Contents"; then
  print -u2 "bundle contains a forbidden local path or example device address"
  exit 1
fi

print "APP VERIFY PASS: $APP"
