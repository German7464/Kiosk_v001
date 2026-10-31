import hashlib
import unittest
from kiosk.publication import validate_manifest, verify_payload


class ManifestTests(unittest.TestCase):
    def manifest(self, path="data/events.json"):
        return {"schema_version": 1, "revision": "1", "renderer": "events-v1", "files": [{"path": path, "size": 2, "sha256": hashlib.sha256(b"{}").hexdigest()}]}

    def test_valid_and_corrupt_payload(self):
        entry = validate_manifest(self.manifest())["files"][0]
        verify_payload(entry, b"{}")
        with self.assertRaises(ValueError):
            verify_payload(entry, b"[]")

    def test_unsafe_and_nonportable_names(self):
        for name in ("../x", "/x", "a//b", "a\\b", "C:x", "NUL.json", "x. /b", "a/./b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_manifest(self.manifest(name))

    def test_duplicate_and_incompatible(self):
        value = self.manifest()
        value["files"].append(dict(value["files"][0], path="DATA/events.json"))
        with self.assertRaises(ValueError):
            validate_manifest(value)
        value = self.manifest()
        value["renderer"] = "future"
        with self.assertRaises(ValueError):
            validate_manifest(value)
