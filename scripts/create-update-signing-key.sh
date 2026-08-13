#!/bin/zsh
set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  print -u2 "usage: $0 /absolute/private/backup/directory"
  exit 2
fi

OUTPUT_DIR="${1:A}"
PRIVATE_KEY="$OUTPUT_DIR/mivibe-update-private.pem"
PRIVATE_KEY_BASE64="$OUTPUT_DIR/mivibe-update-private.pem.base64"
PUBLIC_KEY="$OUTPUT_DIR/mivibe-update-public.base64"

if [[ -e "$PRIVATE_KEY" || -e "$PRIVATE_KEY_BASE64" || -e "$PUBLIC_KEY" ]]; then
  print -u2 "refusing to overwrite an existing update key in $OUTPUT_DIR"
  exit 2
fi

PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import cryptography' >/dev/null 2>&1; then
  print -u2 "Python cryptography is required. Install it with:"
  print -u2 "  $PYTHON -m pip install -r scripts/requirements-updates.txt"
  exit 2
fi

umask 077
mkdir -p "$OUTPUT_DIR"
"$PYTHON" - "$PRIVATE_KEY" "$PRIVATE_KEY_BASE64" "$PUBLIC_KEY" <<'PY'
import base64
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

private_path, secret_path, public_path = map(Path, sys.argv[1:])
private_key = Ed25519PrivateKey.generate()
private_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)
public_raw = private_key.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)
private_path.write_bytes(private_pem)
secret_path.write_text(base64.b64encode(private_pem).decode("ascii"), encoding="ascii")
public_path.write_text(base64.b64encode(public_raw).decode("ascii"), encoding="ascii")
for path in (private_path, secret_path, public_path):
    os.chmod(path, 0o600)
PY
chmod 600 "$PRIVATE_KEY" "$PRIVATE_KEY_BASE64" "$PUBLIC_KEY"

print "Update signing key generated. Back up this directory securely:"
print "  $OUTPUT_DIR"
print
print "Configure GitHub without printing the private key:"
print "  gh secret set UPDATE_ED25519_PRIVATE_KEY_BASE64 < $PRIVATE_KEY_BASE64"
print "  gh variable set UPDATE_ED25519_PUBLIC_KEY --body \"\$(< $PUBLIC_KEY)\""
print
print "Pass this public value to both application builds:"
print "  MIVIBE_UPDATE_ED25519_PUBLIC_KEY=\$(< $PUBLIC_KEY)"
