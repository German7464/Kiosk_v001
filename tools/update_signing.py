"""Update-signing key management and manifest signing (build machine only).

The Ed25519 update-signing key is a dedicated, separate key retained only on the
build machine and never reused for HTTPS/group/credential purposes. The private
key lives outside the repository (default ``C:\\KioskUpdateKeys``) with an
Administrators-only ACL; only the public verification key is ever shipped.
"""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from kiosk.core.update import DATA_SCHEMA_VERSION
from kiosk.core.update_crypto import ALGORITHM, generate_key, public_key_id, sign, verify_signature

DEFAULT_KEYS = Path(os.environ.get("KIOSK_UPDATE_KEYS", r"C:\KioskUpdateKeys"))
PRIVATE_NAME = "update-signing-key.pem"
PUBLIC_NAME = "update-verification-key.pem"


def _digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _restrict(path):
    # Administrators + SYSTEM only; inherited access removed. The key is never
    # readable by ordinary users and never enters the repository.
    subprocess.run(["icacls.exe", str(path), "/inheritance:r",
                    "/grant:r", "*S-1-5-32-544:F", "*S-1-5-18:F"],
                   capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)


def keygen(directory=DEFAULT_KEYS, force=False):
    directory = Path(directory)
    private = directory / PRIVATE_NAME
    public = directory / PUBLIC_NAME
    if (private.exists() or public.exists()) and not force:
        raise ValueError("An update signing key already exists; reusing it avoids a new trust anchor.")
    directory.mkdir(parents=True, exist_ok=True)
    private_pem, public_pem = generate_key()
    private.write_text(private_pem, encoding="ascii")
    public.write_text(public_pem, encoding="ascii")
    _restrict(private)
    _restrict(public)
    return {"private": str(private), "public": str(public), "key_id": public_key_id(public_pem)}


def sign_manifest(private_pem, manifest_path, signature_path):
    data = Path(manifest_path).read_bytes()
    signature = sign(private_pem, data)
    Path(signature_path).write_bytes(signature)
    return signature


def verify_manifest(public_pem, manifest_path, signature_path):
    verify_signature(public_pem, Path(manifest_path).read_bytes(), Path(signature_path).read_bytes())
    return True


def make_manifest(product, version, installer, min_compatible, key_id, built_at):
    return {
        "schema_version": 1,
        "product": product,
        "platform": "win-x64",
        "version": version,
        "min_compatible": min_compatible,
        "data_schema": DATA_SCHEMA_VERSION,
        "key_id": key_id,
        "signature_algorithm": ALGORITHM,
        "built_at": built_at,
        "files": {Path(installer).name: _digest(installer)},
    }


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    keygen_p = sub.add_parser("keygen")
    keygen_p.add_argument("--directory", type=Path, default=DEFAULT_KEYS)
    keygen_p.add_argument("--force", action="store_true")
    sign_p = sub.add_parser("sign")
    sign_p.add_argument("--key", required=True)
    sign_p.add_argument("--manifest", required=True)
    sign_p.add_argument("--out", required=True)
    verify_p = sub.add_parser("verify")
    verify_p.add_argument("--key", required=True)
    verify_p.add_argument("--manifest", required=True)
    verify_p.add_argument("--signature", required=True)
    args = parser.parse_args()
    if args.command == "keygen":
        print(json.dumps(keygen(args.directory, args.force)))
    elif args.command == "sign":
        sign_manifest(Path(args.key).read_text(encoding="ascii"), args.manifest, args.out)
        print(json.dumps({"signed": args.out, "sha256": _digest(args.out)}))
    elif args.command == "verify":
        verify_manifest(Path(args.key).read_text(encoding="ascii"), args.manifest, args.signature)
        print(json.dumps({"verified": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
