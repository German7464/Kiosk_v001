import argparse
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import uuid
import warnings


class CertificateError(Exception):
    pass


def crypto(action, **values):
    executable = shutil.which("pwsh")
    if os.name != "nt" or executable is None:
        raise CertificateError("Windows and PowerShell 7.6 with .NET 10 are required.")
    try:
        result = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-File", str(Path(__file__).with_name("certificate_crypto.ps1"))],
            input=json.dumps({"action": action, **values}), text=True, encoding="utf-8", capture_output=True, timeout=90,
        )
        if result.returncode:
            raise CertificateError("Certificate operation rejected; check inputs, identity, password and validity.")
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        raise CertificateError("Certificate engine unavailable or response invalid.") from error


def normalized_installation(value):
    try:
        result = str(uuid.UUID(value))
        if result != value:
            raise ValueError()
        return result
    except ValueError as error:
        raise CertificateError("Use a canonical lowercase installation UUID.") from error


def normalized_names(values):
    result = []
    for value in values:
        name = value.lower()
        if re.fullmatch(r"[0-9.]+", name):
            try:
                address = ipaddress.IPv4Address(name)
            except ipaddress.AddressValueError as error:
                raise CertificateError("Invalid IPv4 name.") from error
            if address.is_unspecified or address.is_multicast or address.is_reserved or int(str(address).split(".")[0]) == 0:
                raise CertificateError("Unicast IPv4 required.")
            name = str(address)
        elif len(name) > 253 or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in name.split(".")):
            raise CertificateError("Use explicit ASCII DNS names or unicast IPv4; wildcards are unsupported.")
        result.append(name)
    if not 1 <= len(result) <= 16 or len(set(result)) != len(result):
        raise CertificateError("Supply one to sixteen distinct names.")
    return sorted(result)


def checked_path(value):
    path = Path(os.path.abspath(value))
    for part in (path, *path.parents):
        if part.exists() and (part.is_symlink() or getattr(part.stat(follow_symlinks=False), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise CertificateError("Reparse points are unsupported for certificate files.")
    return path


def disjoint(first, second):
    if first.is_relative_to(second) or second.is_relative_to(first):
        raise CertificateError("Private storage and transfer directories must be separate.")


def read_text(path):
    path = checked_path(path)
    with path.open("rb") as stream:
        data = stream.read(65537)
    if len(data) > 65536:
        raise CertificateError("Certificate input is too large.")
    return data.decode("utf-8")


def write_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def private_directory(path):
    path.mkdir()
    crypto("secure", path=str(path))


def password(confirm=False):
    if not sys.stdin.isatty():
        raise CertificateError("Signing requires an interactive terminal with hidden password input.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        value = getpass.getpass("CA password: ")
        if confirm and value != getpass.getpass("Confirm CA password: "):
            raise CertificateError("Passwords differ.")
    if not 16 <= len(value) <= 1024:
        raise CertificateError("CA password must contain 16 to 1024 characters.")
    return value


def create_request(arguments):
    installation = normalized_installation(arguments.installation)
    state = checked_path(arguments.state)
    export = checked_path(arguments.export)
    names = normalized_names(arguments.name or [])
    disjoint(state, export)
    if state.exists() or export.exists() or not state.parent.is_dir() or not export.parent.is_dir():
        raise CertificateError("Request requires new directories with existing parents.")
    material = crypto("request", installation=installation, names=names)
    details = crypto("inspect", installation=installation, csr=material["csr"])
    private_directory(state)
    write_new(state / "server.key", material["key"])
    write_new(state / "request.pem", material["csr"])
    write_new(state / "request.json", json.dumps({"schema_version": 1, **details}, indent=2) + "\n")
    export.mkdir()
    write_new(export / "request.pem", material["csr"])
    print(json.dumps({"status": "request_created", **details}))


def inspect_request(path, installation):
    csr = read_text(path)
    return csr, crypto("inspect", installation=installation, csr=csr)


def sign_request(arguments):
    installation = normalized_installation(arguments.installation)
    authority = checked_path(arguments.authority)
    output = checked_path(arguments.output)
    request_path = checked_path(arguments.csr)
    disjoint(authority, output)
    disjoint(authority, request_path.parent)
    if output.exists() or not output.parent.is_dir():
        raise CertificateError("Signing output must be a new directory with an existing parent.")
    if arguments.initialize_authority:
        if authority.exists() or not authority.parent.is_dir():
            raise CertificateError("Authority initialization requires a new directory with an existing parent.")
    elif not authority.is_dir():
        raise CertificateError("Authority unavailable; renewal never creates a replacement automatically.")
    csr, details = inspect_request(request_path, installation)
    if not sys.stdin.isatty():
        raise CertificateError("Signing requires an interactive terminal.")
    print(json.dumps(details, indent=2))
    if arguments.initialize_authority:
        print("A NEW authority will be created on this administrative PC. Keep its encrypted key here and a protected independent recovery copy.")
    confirmation = "SIGN " + details["request_sha256"]
    if input("Verify installation, names and request digest independently. Type " + confirmation + ": ") != confirmation:
        raise CertificateError("Signing cancelled.")
    secret = password(confirm=arguments.initialize_authority)
    try:
        if arguments.initialize_authority:
            material = crypto("initialize", installation=installation, password=secret)
            private_directory(authority)
            write_new(authority / "authority.key", material["encrypted_key"])
            write_new(authority / "authority.pem", material["authority"])
        result = crypto("sign", installation=installation, csr=csr, password=secret,
                        authority=read_text(authority / "authority.pem"), encrypted_key=read_text(authority / "authority.key"))
    finally:
        secret = None
    output.mkdir()
    write_new(output / "server.pem", result["certificate"])
    write_new(output / "authority.pem", result["authority"])
    fingerprint = hashlib.sha256(pem_bytes(result["authority"])).hexdigest()
    print(json.dumps({"status": "signed", "installation": installation, "request_sha256": details["request_sha256"], "authority_sha256": fingerprint}))


def pem_bytes(value):
    import ssl
    return ssl.PEM_cert_to_DER_cert(value)


def receive_certificate(arguments):
    installation = normalized_installation(arguments.installation)
    state = checked_path(arguments.state)
    fingerprint = arguments.fingerprint or ""
    if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
        raise CertificateError("Supply the full independently verified CA SHA-256 fingerprint.")
    csr, details = inspect_request(state / "request.pem", installation)
    manifest = json.loads(read_text(state / "request.json"))
    if manifest != {"schema_version": 1, **details}:
        raise CertificateError("Pending request manifest mismatch.")
    certificate = read_text(arguments.certificate)
    authority = read_text(arguments.ca)
    verified = crypto("verify", installation=installation, csr=csr, key=read_text(state / "server.key"),
                      certificate=certificate, authority=authority, fingerprint=fingerprint)
    contents = {"server.pem": certificate, "authority.pem": authority,
                "verified.json": json.dumps({"schema_version": 1, "installation": installation, **verified}, indent=2) + "\n"}
    for name, value in contents.items():
        destination = checked_path(state / name)
        if destination.exists() and read_text(destination) != value:
            raise CertificateError("Existing returned certificate generation differs.")
    for name, value in contents.items():
        if not (state / name).exists():
            write_new(state / name, value)
    print(json.dumps({"status": "certificate_verified", **verified, "active_profile_changed": False}))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline server CSR and separate-PC certificate signing. No trust enrollment or active-profile replacement.")
    commands = parser.add_subparsers(dest="command", required=True)
    request = commands.add_parser("request", help="Create a server request, or verify its returned certificate.")
    request.add_argument("--installation", required=True)
    request.add_argument("--state", required=True)
    request.add_argument("--export")
    request.add_argument("--name", action="append")
    request.add_argument("--certificate")
    request.add_argument("--ca")
    request.add_argument("--fingerprint")
    sign = commands.add_parser("sign", help="Review and sign a request on the administrative PC.")
    sign.add_argument("--installation", required=True)
    sign.add_argument("--authority", required=True)
    sign.add_argument("--csr", required=True)
    sign.add_argument("--output", required=True)
    sign.add_argument("--initialize-authority", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "sign":
            sign_request(arguments)
        elif arguments.certificate:
            if not arguments.ca or not arguments.fingerprint or arguments.export or arguments.name:
                raise CertificateError("Returned-certificate mode needs --ca and --fingerprint; omit --export and --name.")
            receive_certificate(arguments)
        else:
            if not arguments.export or not arguments.name or arguments.ca or arguments.fingerprint:
                raise CertificateError("New request needs --export and --name; omit returned-certificate options.")
            create_request(arguments)
        return 0
    except CertificateError as error:
        print(str(error) + " No active HTTPS profile was changed.", file=sys.stderr)
        return 1
    except (OSError, ValueError, EOFError, getpass.GetPassWarning):
        print("Certificate operation failed or cancelled. No active HTTPS profile was changed.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Certificate operation cancelled. No active HTTPS profile was changed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
