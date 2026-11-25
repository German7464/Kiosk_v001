"""Promote one approved roaming publication into signed display assignments.

The server never signs and never invents a publisher proof. It validates the exact
approved target set and commits the assignment, history, cohort, configurations,
proofs and (when the trusted Maintenance side supplied one) the acceptance receipt
as one transaction; a mismatch leaves the previous distribution intact.
"""
from kiosk.delivery.protocol import DeliveryError, encode, sha


def promote(workspace, state, identity, now, *, receipt=None, acceptance_key=None):
    """Activate exactly one approved plan; every target must match its display."""
    from kiosk.delivery.protocol import digest
    digest(identity)
    document, proof = workspace.approved(identity)
    plan, metadata = document['plan'], document['publication']
    if sha(encode(metadata)) != plan['publication_sha256']:
        raise DeliveryError('publisher_publication_changed', 409)
    if metadata['renderer']['build_id'] != plan['renderer']:
        raise DeliveryError('publisher_publication_changed', 409)
    if not isinstance(plan['targets'], list) or not plan['targets']:
        raise DeliveryError('publisher_targets_changed', 409)
    return state.assign_publisher(metadata, proof, plan['targets'], now,
                                  receipt=receipt, plan_id=identity,
                                  acceptance_key=acceptance_key)


def promote_page(workspace, state, identity, approval, chain, receipt, acceptance_key, now):
    """Commit one exact v2 page plan across the Content workspace and delivery DBs.

    Ownership and recovery preconditions: both SQLite files are Content-owned
    local state under the same protected service account. They use rollback
    journals (``delete``/``truncate``/``persist``), never WAL, so one ``BEGIN
    IMMEDIATE`` transaction over an ATTACHed pair is atomic via SQLite's master
    journal. The public pointer (``plans.approval`` + ``heads``) and every
    per-device assignment/history/proof/receipt become visible together or not
    at all. Immutable catalog files are written and verified before this step;
    an interrupted commit leaves only unreferenced catalog directories, which
    are safe to retain. An exact retry of the same signed plan returns the
    original generation; a changed plan or target set aborts before any pointer
    changes and requires a fresh review and signature.
    """
    import sqlite3
    from pathlib import Path
    from kiosk.delivery.protocol import DeliveryError, decode
    from kiosk.publication import page_materialize

    workspace_path = Path(workspace.path)
    delivery_path = Path(state.root) / 'delivery.sqlite'
    if workspace_path.resolve() == delivery_path.resolve():
        raise DeliveryError('page_store_conflict', 503)
    db = sqlite3.connect(workspace_path, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('ATTACH DATABASE ? AS delivery', (str(delivery_path),))
        for name in ('main', 'delivery'):
            mode = db.execute(f'PRAGMA {name}.journal_mode').fetchone()[0]
            if str(mode).lower() not in ('delete', 'truncate', 'persist'):
                raise DeliveryError('page_journal_mode', 503)
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM plans WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise DeliveryError('plan_not_found', 404)
        document = decode(bytes(row['snapshot']))
        if document.get('version') != 2:
            raise DeliveryError('publisher_plan_version', 409)
        try:
            page_materialize.load_candidate_files(state, document)
        except page_materialize.PageMaterializeError as error:
            raise DeliveryError(error.code, 409) from None
        workspace._approve_page(db, row, document, approval, chain)
        proof_row = db.execute('SELECT approval FROM plans WHERE id=?', (identity,)).fetchone()
        if proof_row is None or proof_row['approval'] is None:
            raise DeliveryError('publisher_approval_missing', 409)
        proof = decode(bytes(proof_row['approval']))
        result = state.page_distribute(db, document, proof, receipt, acceptance_key, now,
                                       schema='delivery')
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
