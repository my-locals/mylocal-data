#!/usr/bin/env -S python3 -I
"""Signs a file in minisign's format, with the key in the environment (`SIGNING_KEY`: 32 bytes,
base64). The app holds the public key and checks every file it downloads against it.

  SIGNING_KEY=… ./sign.py data/support.json out/support.json.minisig
  ./sign.py --new-key      a new key: the private one to stdout, the public one to stderr
"""

import base64
import hashlib
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

RAW = {"encoding": serialization.Encoding.Raw, "format": serialization.PublicFormat.Raw}


def key_id(public):
    """Eight bytes that tie a signature to its key, taken from the public key."""
    return hashlib.blake2b(public, digest_size=8).digest()


def public_line(public):
    return base64.b64encode(b"Ed" + key_id(public) + public).decode()


def signature_text(key, data, comment):
    """The four lines of a minisign signature: `ED` signs the file's BLAKE2b-512 hash, and
    the global signature covers that and the trusted comment."""
    public = key.public_key().public_bytes(**RAW)
    prehashed = key.sign(hashlib.blake2b(data, digest_size=64).digest())
    line = b"ED" + key_id(public) + prehashed
    trusted = comment.encode()
    global_signature = key.sign(prehashed + trusted)
    return (
        "untrusted comment: signature from the mylocal-data key\n"
        f"{base64.b64encode(line).decode()}\n"
        f"trusted comment: {comment}\n"
        f"{base64.b64encode(global_signature).decode()}\n"
    )


def main():
    if sys.argv[1:] == ["--new-key"]:
        key = Ed25519PrivateKey.generate()
        seed = key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        print(base64.b64encode(seed).decode())
        print(public_line(key.public_key().public_bytes(**RAW)), file=sys.stderr)
        return 0
    source, target = sys.argv[1:]
    seed = base64.b64decode(os.environ["SIGNING_KEY"], validate=True)
    key = Ed25519PrivateKey.from_private_bytes(seed)
    with open(source, "rb") as f:
        data = f.read()
    with open(target, "w", encoding="ascii") as f:
        f.write(signature_text(key, data, os.path.basename(source)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
