"""Durable public-authority delivery; no signing keys cross the service boundary."""
from kiosk.delivery.protocol import decode


def pending(store):
    with store.connection(write=False) as db:
        return db.execute('SELECT 1 FROM authority_delivery').fetchone() is not None


def flush(store, client):
    if store.placement() is not None and store.fenced():
        return False
    with store.connection(write=False) as db:
        row = db.execute('SELECT body FROM authority_delivery WHERE singleton=1').fetchone()
    if row is None:
        return True
    raw = bytes(row['body'])
    client._request('POST', '/service/v1/authority', decode(raw))
    # A concurrent administrator may already have queued a newer signed bundle.
    with store.connection() as db:
        db.execute('DELETE FROM authority_delivery WHERE singleton=1 AND body=?', (raw,))
    return not pending(store)
