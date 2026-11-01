"""Deterministic test-only image vectors. Standard library; never decodes images."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parents[2]
PNG_SOURCE = 'logs/pc1-harness-fixtures-20261031/files/contract/valid/static/uploads/card.png'
PNG_SHA = '4b02621a1639a302da7e368db30b5b96f931f6be98b1154b2e0d787986227a46'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def chunk(kind, payload):
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))


def png(width, height, alpha):
    channels = 4 if alpha else 3
    rows = b''.join(b'\0' + bytes(v for x in range(width) for v in
        ((x * 31 % 256, y * 47 % 256, 123, (x + y) * 63 % 256) if alpha else
         (x * 31 % 256, y * 47 % 256, 123))) for y in range(height))
    assert len(rows) == height * (1 + width * channels)
    # Explicit stored DEFLATE block: byte identity does not depend on zlib compressor version.
    n = len(rows)
    compressed = b'\x78\x01\x01' + struct.pack('<HH', n, n ^ 65535) + rows + struct.pack('>I', zlib.adler32(rows))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6 if alpha else 2, 0, 0, 0)) + chunk(b'IDAT', compressed) + chunk(b'IEND', b'')


def jpeg_parameters(data):
    """Read marker structure only; not a decoder or image-validity claim."""
    if not data.startswith(b'\xff\xd8') or not data.endswith(b'\xff\xd9'):
        raise ValueError('JPEG source must have SOI/EOI')
    pos = 2
    frame = None
    while pos < len(data):
        if data[pos] != 255:
            raise ValueError('invalid JPEG marker boundary')
        while data[pos] == 255:
            pos += 1
        marker = data[pos]
        pos += 1
        length = int.from_bytes(data[pos:pos + 2], 'big')
        if length < 2 or pos + length > len(data):
            raise ValueError('invalid JPEG segment length')
        if marker == 0xC2:
            precision, height, width, components = struct.unpack('>BHHB', data[pos + 2:pos + 8])
            frame = dict(width=width, height=height, components=components, precision=precision, frame_marker='SOF2')
        if marker == 0xDA:
            if frame is None:
                raise ValueError('progressive SOF2 required before SOS')
            return frame, pos + length
        pos += length
    raise ValueError('JPEG SOS missing')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='new directory only, relative to caller cwd')
    parser.add_argument('--png-only', action='store_true', help='explicit partial corpus; JPEG remains pending')
    parser.add_argument('--jpeg-source', type=Path, help='existing synthetic progressive JPEG, relative to caller cwd')
    parser.add_argument('--jpeg-sha256', help='independently supplied source SHA256')
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error('output already exists')
    if args.png_only == bool(args.jpeg_source or args.jpeg_sha256):
        parser.error('choose --png-only OR both --jpeg-source and --jpeg-sha256')
    # Keep the historical provenance label in manifest, read the pinned vendored copy.
    source = (ROOT / 'android/testdata/image-sources/pc1-card.png').read_bytes()
    if sha(source) != PNG_SHA:
        parser.error('pinned PNG source mismatch')
    sources = [dict(id='pc1-card-png', path=PNG_SOURCE, sha256=PNG_SHA, size_bytes=len(source))]
    vectors = []
    payloads = {}

    def add(name, data, method, origin, purpose, **known):
        payloads[name] = data
        vectors.append(dict(id=name.replace('.', '-'), path='vectors/' + name,
            derivation=method, source_identity=origin, sha256=sha(data), size_bytes=len(data),
            purpose=purpose, known_parameters=known,
            measurements=dict(pillow='not_measured', android_decoder='not_measured', webview='not_measured')))

    add('pc1-card.png', source, 'exact copy of pinned PC1 synthetic fixture', 'pc1-card-png', 'existing PNG baseline')
    for w, h, a in [(1, 1, False), (3, 2, False), (2, 3, True), (7, 5, True)]:
        add(f'generated-{w}x{h}-'+('rgba' if a else 'rgb')+'.png', png(w, h, a),
            'deterministic formula pixels; filter0; stored DEFLATE; CRC32 chunks', 'generator-v1',
            'small constructed PNG baseline', width=w, height=h, bit_depth=8, color_type=6 if a else 2,
            alpha_pattern='(x+y)*63 mod256' if a else 'none')
    base = png(3, 2, False)
    origin = dict(id='generated-3x2-rgb-png', sha256=sha(base))
    corrupt = bytearray(base)
    corrupt[29] ^= 1  # IHDR CRC only, no pixel/header mutation.
    add('png-bad-ihdr-crc.png', bytes(corrupt), 'xor bit0 at byte29 (IHDR CRC)', origin, 'measure CRC handling', changed_offset=29)
    for label, cut in [('signature', 4), ('ihdr', 20), ('idat', 45), ('before-iend', len(base)-12)]:
        add('png-truncated-'+label+'.png', base[:cut], 'prefix truncation only', origin, 'measure truncation handling', cut_offset=cut, boundary=label)
    add('png-trailing.png', base+b'TEST-TRAILER\n', 'append ASCII TEST-TRAILER newline after IEND', origin, 'measure trailing-data tolerance', original_end=len(base))
    add('empty.png', b'', 'zero bytes', 'generator-v1', 'measure empty input')
    add('not-image.png', b'Synthetic non-image payload\n', 'literal ASCII text', 'generator-v1', 'measure non-image input with image suffix')
    if not args.png_only:
        if not args.jpeg_source or not args.jpeg_sha256:
            parser.error('both JPEG source and SHA256 required')
        if args.jpeg_source.stat().st_size > 2 * 1024 * 1024:
            parser.error('JPEG source exceeds test cap2MiB')
        with args.jpeg_source.open('rb') as stream:
            data = stream.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024 or sha(data) != args.jpeg_sha256:
            parser.error('JPEG source hash/size mismatch (test cap2MiB)')
        known, scan = jpeg_parameters(data)
        if not 0 < known['width'] <= 2048 or not 0 < known['height'] <= 2048:
            parser.error('JPEG source dimensions exceed small-vector scope')
        sources.append(dict(id='supplied-progressive-jpeg', sha256=sha(data), size_bytes=len(data), known_parameters=known))
        for name in ['progressive.jpg', 'progressive-wrong.png', 'progressive-no-extension']:
            add(name, data, 'exact copy, filename only varies', 'supplied-progressive-jpeg', 'progressive baseline / suffix behavior', **known)
        for label, cut in [('soi', 1), ('scan-header', scan-1), ('scan-data', scan+(len(data)-scan-2)//2), ('before-eoi', len(data)-2)]:
            add('jpeg-truncated-'+label+'.jpg', data[:cut], 'prefix truncation only', 'supplied-progressive-jpeg', 'measure truncation handling', cut_offset=cut, boundary=label)
        add('jpeg-trailing.jpg', data+b'TEST-TRAILER\n', 'append literal after EOI', 'supplied-progressive-jpeg', 'measure trailing-data tolerance', original_end=len(data))
    manifest = dict(schema_version=1, corpus='image-parity-test-only-v1',
        scope='small synthetic vectors; no decoder expectations or admission result',
        jpeg_status='pending_source' if args.png_only else 'included', sources=sources, vectors=vectors)
    # mkdir is atomic against a competing creator; all inputs validated before any output.
    args.output.mkdir(parents=False, exist_ok=False)
    (args.output/'vectors').mkdir()
    for name, data in payloads.items():
        with (args.output/'vectors'/name).open('xb') as output:
            output.write(data)
    with (args.output/'manifest.json').open('x', encoding='utf-8', newline='\n') as output:
        output.write(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True)+'\n')
    print(f'Created {len(vectors)} vectors; JPEG: {manifest["jpeg_status"]}')


if __name__ == '__main__':
    main()
