#!/bin/zsh
set -euo pipefail

ROOT="${0:A:h:h}"
OUTPUT="$ROOT/.build/self-test/RemoteMicSelfTest"

mkdir -p "${OUTPUT:h}"
xcrun swiftc \
  "$ROOT/Sources/RemoteMic/ATVVProtocol.swift" \
  "$ROOT/Sources/RemoteMic/BluetoothLifecycle.swift" \
  "$ROOT/Sources/RemoteMic/RemoteButtons.swift" \
  "$ROOT/Sources/RemoteMic/AppSettings.swift" \
  "$ROOT/Sources/RemoteMic/VoiceFunctionKeyLatch.swift" \
  "$ROOT/Sources/RemoteMic/RemoteKeyHardwareSuppressor.swift" \
  "$ROOT/Sources/RemoteMic/AppLogger.swift" \
  "$ROOT/Sources/RemoteMic/TestTone.swift" \
  "$ROOT/Tests/SelfTest/main.swift" \
  -o "$OUTPUT"
"$OUTPUT"

DEVELOPER_DIR="$(xcode-select -p)"
TESTING_FRAMEWORK_DIR="$DEVELOPER_DIR/Library/Developer/Frameworks"
TESTING_INTEROP_DIR="$DEVELOPER_DIR/Library/Developer/usr/lib"
SWIFT_TEST_ARGS=()

# The standalone Apple Command Line Tools ship Swift Testing outside SwiftPM's
# default framework and runtime search paths. Full Xcode usually adds these
# paths automatically, but passing them explicitly is harmless there as well.
if [[ -d "$TESTING_FRAMEWORK_DIR/Testing.framework" &&
      -f "$TESTING_INTEROP_DIR/lib_TestingInterop.dylib" ]]; then
  SWIFT_TEST_ARGS=(
    -Xswiftc -F
    -Xswiftc "$TESTING_FRAMEWORK_DIR"
    -Xlinker -F
    -Xlinker "$TESTING_FRAMEWORK_DIR"
    -Xlinker -rpath
    -Xlinker "$TESTING_FRAMEWORK_DIR"
    -Xlinker -rpath
    -Xlinker "$TESTING_INTEROP_DIR"
  )
fi

xcrun swift test "${SWIFT_TEST_ARGS[@]}"
