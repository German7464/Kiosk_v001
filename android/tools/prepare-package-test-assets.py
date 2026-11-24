"""Copy immutable PC1 oracle cases into the test APK only; never alter source fixtures."""
import hashlib
import json
import pathlib
import shutil

root=pathlib.Path(__file__).resolve().parents[2]
source=root/'logs/pc1-harness-fixtures-20261031/files/contract'
archive=root/'logs/pc1-harness-fixtures-20261031/fixtures.zip'
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='ad1bc48b8c68edb78b1a9c0b147002848d2e24a04745f66703a1ed34a11f8aa5'
expected=json.loads((source/'expected.json').read_text())
assert len(expected)==9 and expected==json.loads((source/'results.json').read_text())
target=root/'android/app/src/androidTest/assets/package-cases'
target.mkdir(parents=True,exist_ok=True)
for name in expected:
    shutil.copytree(source/name,target/name,dirs_exist_ok=True)
    before={p.relative_to(source/name).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (source/name).rglob('*') if p.is_file()}
    after={p.relative_to(target/name).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (target/name).rglob('*') if p.is_file()}
    assert before==after
shutil.copyfile(source/'expected.json',target/'pc1-expected.json')
print('PASS archive SHA256, nine unchanged test-APK case copies; PC1 results are oracle only')
