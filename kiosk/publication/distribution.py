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
