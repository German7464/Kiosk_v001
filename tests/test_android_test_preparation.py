import json
import hashlib
import io
import unittest

from PIL import Image
from kiosk.publication.exporter import PackageError, _json
from tests import test_publication_export as fixtures
from tools.prepare_android_test_publication import prepare, verify_preparation


class AndroidTestPreparationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExportTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.export()
        self.output = self.fixture.root / 'android-preparation'

    def test_full_package_and_two_views_reverify(self):
        digest, report = prepare(self.fixture.destination, self.output)
        self.assertEqual(verify_preparation(self.output, digest), report)
        self.assertEqual(set(report['views']), {'kiosk', 'tv'})
        self.assertIn('not_source_authentication', report['limitations'])

    def test_independent_confirmation_and_artifact_mutation(self):
        digest, report = prepare(self.fixture.destination, self.output)
        with self.assertRaises(PackageError):
            verify_preparation(self.output, '0' * 64)
        view = self.output / report['views']['kiosk']['path'] / 'index.html'
        view.write_bytes(view.read_bytes() + b'changed')
        with self.assertRaises(PackageError):
            verify_preparation(self.output, digest)

    def test_existing_destination_and_bad_source_preserve_data(self):
        self.output.mkdir()
        sentinel = self.output / 'owner.txt'
        sentinel.write_text('preserve')
        with self.assertRaises(FileExistsError):
            prepare(self.fixture.destination, self.output)
        self.assertEqual(sentinel.read_text(), 'preserve')
        data = self.fixture.destination / 'data/events.json'
        data.write_bytes(data.read_bytes() + b'bad')
        untouched = self.fixture.root / 'must-not-exist'
        with self.assertRaises(PackageError):
            prepare(self.fixture.destination, untouched)
        self.assertFalse(untouched.exists())

    def test_changed_receipt_is_not_accepted(self):
        digest, report = prepare(self.fixture.destination, self.output)
        report['scope'] = 'pretend_authorization'
        (self.output / 'preparation.json').write_text(json.dumps(report))
        with self.assertRaises(PackageError):
            verify_preparation(self.output, digest)

    def test_rehashed_invalid_image_does_not_get_preparation_evidence(self):
        buffer = io.BytesIO()
        Image.new('RGB', (3, 2), 'blue').save(buffer, 'PNG')
        image = self.fixture.destination / 'static/uploads/card.jpg'
        image.write_bytes(buffer.getvalue()[:-12])
        manifest_path = self.fixture.destination / 'manifest.json'
        manifest = json.loads(manifest_path.read_bytes())
        for entry in manifest['files']:
            if entry['path'] == 'static/uploads/card.jpg':
                entry.update(size=image.stat().st_size,
                             sha256=hashlib.sha256(image.read_bytes()).hexdigest())
        manifest_path.write_bytes(_json(manifest))
        with self.assertRaisesRegex(PackageError, 'invalid_image'):
            prepare(self.fixture.destination, self.output)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
