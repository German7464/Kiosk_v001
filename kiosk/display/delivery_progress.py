"""Best-effort single-slot telemetry; never a receipt queue or display dependency."""
import copy
import threading
import time

from kiosk.delivery.protocol import decode, encode, fields, digest
from kiosk.publication.store import _atomic_write
from .delivery_transport import TransportError
from .cache import renderer_identity
from kiosk.delivery.protocol import PROFILE
from urllib.parse import urlencode


class Reporter:
    def __init__(self, path):
        self.path = path
        self.condition = threading.Condition()
        self.pending = None
        self.closed = False
        self.thread = None
        self.counter = 0
        try:
            self.counter = decode(path.read_bytes())['sequence']
            if type(self.counter) is not int or not 0 <= self.counter < 2**63:
                self.counter = 0
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.last_offer = 0
        self.last_signature = None
        self.next_attempt = 0

    def begin(self):
        with self.condition:
            self.counter = max(self.counter + 1, time.time_ns())
            return self.counter

    def offer(self, transport, target, attempt, state, completed=0, total=0, error='none'):
        signature = (target.get('generation'), target.get('package_id'), attempt, state, completed, total, error)
        with self.condition:
            if self.closed or signature == self.last_signature:
                return
            # Download byte updates at most once per 5 seconds; state transitions
            # coalesce immediately into the same one-element slot.
            now = time.monotonic()
            if state == 'downloading' and self.last_signature and self.last_signature[3] == state and now - self.last_offer < 5:
                return
            self.counter = max(self.counter + 1, time.time_ns())
            body = {**target, 'attempt': attempt, 'sequence': self.counter, 'state': state,
                    'completed_bytes': completed, 'total_bytes': total, 'error': error}
            self.pending = (copy.copy(transport), body)
            self.last_offer, self.last_signature = now, signature
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, daemon=True, name='delivery-progress')
                self.thread.start()
            self.condition.notify_all()

    def _run(self):
        delay = 5
        while True:
            with self.condition:
                while self.pending is None and not self.closed:
                    self.condition.wait()
                if self.closed:
                    return
                remaining = self.next_attempt - time.monotonic()
                if remaining > 0:
                    self.condition.wait(timeout=remaining)
                    continue
                item = self.pending
            transport, body = item
            try:
                if 'generation' not in body:
                    target = transport.json('/api/v2/client/progress')
                    fields(target, 'version device_id group_id generation package_id')
                    digest(target['package_id'])
                    if (target['version'] != 1 or type(target['generation']) is not int or target['generation'] <= 0 or
                            target['device_id'] != body['device_id'] or target['group_id'] != body['group_id']):
                        raise ValueError('progress_target_refused')
                    body.update(target)
                    # The failed renderer request and target discovery can race
                    # a publication. Recheck compatibility AFTER the target hint;
                    # a now-compatible assignment must never be marked incompatible.
                    query = urlencode({'renderer': renderer_identity(), 'resource_profile': PROFILE})
                    try:
                        transport.json('/api/v2/client/assignment?' + query)
                    except TransportError as exc:
                        if exc.status != 409:
                            raise
                    else:
                        raise TransportError('no_longer_incompatible', 409)
                # Persist only a high-water sequence, never a durable telemetry
                # queue. A restart may lose intermediate status, not content.
                _atomic_write(self.path, encode({'sequence': body['sequence']}))
                result = transport.json('/api/v2/client/progress', body=body)
                if (result.get('version') != 1 or result.get('sequence') != body['sequence'] or
                        result.get('state') not in ('recorded', 'duplicate', 'superseded')):
                    raise ValueError('progress_ack_refused')
                retry = False
                delay = 5
            except Exception as exc:
                retry = not isinstance(exc, TransportError) or exc.status in (0, 429, 500, 502, 503, 504)
                delay = min(3600, max(min(300, delay * 2), getattr(exc, 'retry_after', 5)))
            with self.condition:
                self.next_attempt = time.monotonic() + delay if retry else 0
                if self.pending is item:
                    if not retry:
                        self.pending = None

    def close(self):
        # No network join on the native display thread; owned daemon exits after
        # its bounded transport returns. No new worker is started after close.
        with self.condition:
            self.closed = True
            self.pending = None
            self.condition.notify_all()
