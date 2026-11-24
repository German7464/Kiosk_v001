"""Standard-library checks for the test-only corpus tool; no image decoder claims."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

TOOL = Path(__file__).with_name('generate-image-corpus.py')
spec = importlib.util.spec_from_file_location('corpus', TOOL)
corpus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(corpus)


class CorpusTest(unittest.TestCase):
    def test_constructed_png_chunks_and_pixels(self):
        for w, h, alpha in [(1, 1, False), (3, 2, False), (2, 3, True), (7, 5, True)]:
            data = corpus.png(w, h, alpha)
            pos = 8
            kinds = []
            while pos < len(data):
                length = int.from_bytes(data[pos:pos+4], 'big')
                kind = data[pos+4:pos+8]
                payload = data[pos+8:pos+8+length]
                crc = int.from_bytes(data[pos+8+length:pos+12+length], 'big')
                self.assertEqual(crc, zlib.crc32(kind+payload))
                if kind == b'IDAT':
                    raw = zlib.decompress(payload)
                    self.assertEqual(len(raw), h*(1+w*(4 if alpha else 3)))
                    self.assertEqual(raw[0], 0)
                kinds.append(kind)
                pos += length+12
            self.assertEqual(kinds, [b'IHDR', b'IDAT', b'IEND'])
            self.assertEqual(pos, len(data))

    def test_generation_and_refusal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def run(*args):
                return subprocess.run([sys.executable, str(TOOL), *map(str, args)], cwd=root, capture_output=True)
            self.assertEqual(run('--output', 'one', '--png-only').returncode, 0)
            self.assertEqual(run('--output', 'two', '--png-only').returncode, 0)
            one = {p.relative_to(root/'one').as_posix(): p.read_bytes() for p in (root/'one').rglob('*') if p.is_file()}
            two = {p.relative_to(root/'two').as_posix(): p.read_bytes() for p in (root/'two').rglob('*') if p.is_file()}
            self.assertEqual(one, two)
            manifest = json.loads(one['manifest.json'])
            paths, ids = set(), set()
            for vector in manifest['vectors']:
                path = vector['path']
                self.assertNotIn(path, paths)
                self.assertNotIn(vector['id'], ids)
                self.assertEqual(Path(path).parts[0], 'vectors')
                self.assertNotIn('..', Path(path).parts)
                paths.add(path); ids.add(vector['id'])
                self.assertEqual(vector['size_bytes'], len(one[path]))
                self.assertEqual(vector['sha256'], hashlib.sha256(one[path]).hexdigest())
                self.assertEqual(set(vector['measurements'].values()), {'not_measured'})
            self.assertEqual(paths | {'manifest.json'}, set(one))
            self.assertNotEqual(run('--output', 'one', '--png-only').returncode, 0)
            self.assertEqual(one, {p.relative_to(root/'one').as_posix(): p.read_bytes() for p in (root/'one').rglob('*') if p.is_file()})
            self.assertNotEqual(run('--output', 'none').returncode, 0)
            self.assertFalse((root/'none').exists())
            (root/'fake.jpg').write_bytes(b'not JPEG')
            self.assertNotEqual(run('--output', 'bad', '--jpeg-source', 'fake.jpg', '--jpeg-sha256', '0'*64).returncode, 0)
            self.assertFalse((root/'bad').exists())

    def test_jpeg_marker_inspection(self):
        # Artificial marker-only input tests parser boundaries, NOT an image vector.
        frame = b'\xff\xd8\xff\xc2'+struct.pack('>HBHHB', 8, 8, 2, 3, 3)
        data = frame+b'\xff\xda\x00\x02'+b'abc'+b'\xff\xd9'
        known, scan = corpus.jpeg_parameters(data)
        self.assertEqual((known['width'], known['height']), (3, 2))
        self.assertEqual(data[scan:scan+3], b'abc')
        with self.assertRaises(ValueError):
            corpus.jpeg_parameters(b'not JPEG')


if __name__ == '__main__':
    unittest.main()
