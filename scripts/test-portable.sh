#!/bin/zsh
set -euo pipefail

ROOT="${0:A:h:h}"
PYTHON="${PYTHON:-python3}"

print "== macOS static checks =="
(
  cd "$ROOT/platforms/macos"
  swiftc -frontend -parse Sources/RemoteMic/*.swift
  plutil -lint Resources/Info.plist
  zsh -n scripts/*.sh script/*.sh
)

print "== Windows portable checks =="
(
  cd "$ROOT/platforms/windows"
  "$PYTHON" -m py_compile \
    source/standalone/xiaomi_main.py \
    source/standalone/environment_check.py \
    source/bridges/xiaomi/xiaomi_config.py \
    source/bridges/xiaomi/xiaomi_settings.py \
    source/bridges/xiaomi/atvv_live_bridge.py
  if "$PYTHON" -m ruff --version >/dev/null 2>&1; then
    "$PYTHON" -m ruff check \
      source/standalone/xiaomi_main.py \
      source/standalone/environment_check.py \
      source/bridges/xiaomi \
      --select F
  else
    print "ruff not installed; undefined-name lint covered by Windows CI"
  fi
  "$PYTHON" -m unittest \
    tests.test_environment_check \
    tests.test_xiaomi_config \
    tests.test_standalone_packages \
    -v
)

print "PORTABLE CHECKS PASS"
