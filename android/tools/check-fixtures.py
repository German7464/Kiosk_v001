"""Check provenance/byte identity only; this does not execute the Python package verifier."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_SHA = "ad1bc48b8c68edb78b1a9c0b147002848d2e24a04745f66703a1ed34a11f8aa5"
VIEWS = {"valid-kiosk": "contract/view-kiosk", "valid-tv": "contract/view-tv",
         "empty-kiosk": "empty-kiosk", "empty-tv": "empty-tv"}
PINS = {"events.js": "9dbea16811df97b75c2b3e4db25fd468bf9de4a9d2f9fc1b6b3740f4b4ce53fc",
        "events.css": "8662399cc92650fb31434a92240a7dda50f013d6be002de5c5d97d7d746ab37c"}
IDENTITIES = {"valid": "3658670566f16d0cb77e0f58facc10bcb2ec518100764421d3510ef1a604edfa",
              "empty": "bd6397715c21fb23d7d14a8052caa52fc8b6c53d83416db401e6b52ca6ccc7fd"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pc1", type=Path, help="PC1 evidence directory containing fixtures.zip and files/")
    args = parser.parse_args()
    archive = None
    if args.pc1:
        assert digest((args.pc1 / "fixtures.zip").read_bytes()) == ARCHIVE_SHA
        archive = zipfile.ZipFile(args.pc1 / "fixtures.zip")
        assert archive.testzip() is None
        for item in archive.infolist():
            assert not item.is_dir()
            assert archive.read(item) == (args.pc1 / "files" / item.filename).read_bytes(), item.filename
        for name, identity in IDENTITIES.items():
            manifest = json.loads((args.pc1 / "files/contract" / name / "manifest.json").read_bytes())
            assert digest(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()) == identity
        for filename in ("expected.json", "results.json"):
            evidence = json.loads((args.pc1 / "files/contract" / filename).read_bytes())
            assert len(evidence) == 9
        print("PC1 archive SHA/CRC/extracted bytes and package identities PASS; nine-case JSON is PC1 evidence only")
    for name, relative in VIEWS.items():
        view = ROOT / "android/app/src/main/assets/views" / name
        actual = {p.relative_to(view).as_posix() for p in view.rglob("*") if p.is_file()}
        descriptor = json.loads((view / "view.json").read_bytes())
        expected = {row["path"] for row in descriptor["files"]} | {"view.json"}
        assert actual == expected
        assert descriptor["package_sha256"] == IDENTITIES[name.split("-")[0]]
        assert descriptor["mode"] == name.split("-")[1]
        for path in view.rglob("*"):
            assert not path.is_symlink()
            if path.is_file() and archive:
                assert path.read_bytes() == archive.read(relative + "/" + path.relative_to(view).as_posix())
        for row in descriptor["files"]:
            content = (view / row["path"]).read_bytes()
            assert len(content) == row["size"] and digest(content) == row["sha256"]
        for asset, pin in PINS.items():
            content = (view / asset).read_bytes()
            # These immutable historical fixtures predate the unified PC1 renderer.
            # Their pins identify renderer bytes from Android checkpoint 73772b2;
            # the current branch HEAD is not the fixture's source identity.
            assert digest(content) == pin
        print(name, "inventory/hash/pinned fixture JS+CSS identity PASS")
    print("Fixture renderer pins refer to Android checkpoint 73772b2; current renderer parity is a separate check.")


if __name__ == "__main__":
    main()
