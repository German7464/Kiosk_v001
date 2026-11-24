"""Verify PC1 archive/extraction and exact bundled runtime views; no package validation claim."""
import hashlib
import json
import pathlib
import zipfile

root = pathlib.Path(__file__).resolve().parents[2]
source = root / "logs/pc1-tv-runtime-fixtures-20261031"
sha = lambda data: hashlib.sha256(data).hexdigest()
archive = source / "fixtures.zip"
assert sha(archive.read_bytes()) == "7b4fc5f24e71ea0676de33d21eff1d70d27257dbe4283bc9935713b771b942d3"
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    entries = {n: z.read(n) for n in z.namelist() if not n.endswith("/")}
    extracted = {p.relative_to(source / "files").as_posix(): p.read_bytes()
                 for p in (source / "files").rglob("*") if p.is_file()}
    assert entries == extracted
for name in ("two-card-tv", "two-card-kiosk"):
    original = {p.relative_to(source / "files" / name).as_posix(): p.read_bytes()
                for p in (source / "files" / name).rglob("*") if p.is_file()}
    target = root / "android/app/src/main/assets/views" / name
    bundled = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    assert original == bundled
    for asset, digest in (("events.js", "9dbea16811df97b75c2b3e4db25fd468bf9de4a9d2f9fc1b6b3740f4b4ce53fc"),
                          ("events.css", "8662399cc92650fb31434a92240a7dda50f013d6be002de5c5d97d7d746ab37c")):
        assert sha(bundled[asset]) == digest
    descriptor = json.loads(bundled["view.json"])
    assert descriptor["package_sha256"] == "0d027e264096337f7f37f3ca6dd128ed3e6622aa2491ee404f742bb7f5cd1d18"
    print(name, "PASS", {n: sha(b) for n, b in bundled.items()})
print("Archive SHA256, CRC, exact extracted tree and bundled bytes PASS", len(entries))
