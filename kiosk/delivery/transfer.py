"""Verified, bounded artifact responses with strong-validator byte resumption."""
import hashlib
import re
import threading
import time

from flask import Response, request

from .protocol import DeliveryError

MAX_STREAMS = 2
BYTES_PER_SECOND = 2 * 1024 * 1024
CHUNK_BYTES = 64 * 1024


class ArtifactTransfers:
    def __init__(self):
        self.slots = threading.BoundedSemaphore(MAX_STREAMS)

    def response(self, path, entry):
        if not self.slots.acquire(blocking=False):
            raise DeliveryError('transfer_busy', 429)
        stream = None
        released = False
        release_lock = threading.Lock()

        def close():
            nonlocal released
            with release_lock:
                if not released:
                    released = True
                    if stream is not None:
                        stream.close()
                    self.slots.release()

        try:
            stream = path.open('rb')
            total, witness = 0, hashlib.sha256()
            while chunk := stream.read(CHUNK_BYTES):
                total += len(chunk)
                if total > entry['size']:
                    raise DeliveryError('publication_integrity', 503)
                witness.update(chunk)
            if total != entry['size'] or witness.hexdigest() != entry['sha256']:
                raise DeliveryError('publication_integrity', 503)
            validator = '"' + entry['sha256'] + '"'
            start, end, status = 0, total - 1, 200
            requested = request.headers.get('Range')
            # A mismatching validator means a FULL replacement, never an append.
            if requested and request.headers.get('If-Range') == validator:
                match = re.fullmatch(r'bytes=([0-9]{1,20})-([0-9]{1,20})?', requested)
                if match:
                    start = int(match[1])
                    end = min(int(match[2]), total - 1) if match[2] else total - 1
                if match is None or start >= total or end < start:
                    close()
                    return Response(status=416, headers={
                        'Content-Range': f'bytes */{total}', 'ETag': validator,
                        'Accept-Ranges': 'bytes', 'Content-Length': '0',
                    })
                status = 206
            stream.seek(start)
            length = max(0, end - start + 1)

            def chunks():
                remaining, sent = length, 0
                began = time.monotonic()
                try:
                    while remaining:
                        chunk = stream.read(min(CHUNK_BYTES, remaining))
                        if not chunk:
                            raise OSError('artifact truncated during transfer')
                        # Per-stream cap plus two slots bounds aggregate payload rate.
                        delay = (sent + len(chunk)) / BYTES_PER_SECOND - (time.monotonic() - began)
                        if delay > 0:
                            time.sleep(delay)
                        remaining -= len(chunk)
                        sent += len(chunk)
                        yield chunk
                finally:
                    close()

            headers = {'Content-Length': str(length), 'ETag': validator,
                       'Accept-Ranges': 'bytes', 'Cache-Control': 'no-store, no-transform'}
            if status == 206:
                headers['Content-Range'] = f'bytes {start}-{end}/{total}'
            response = Response(chunks(), status=status, headers=headers,
                                content_type='application/octet-stream')
            # Also handles a response closed before the generator's first iteration.
            response.call_on_close(close)
            return response
        except BaseException:
            close()
            raise
