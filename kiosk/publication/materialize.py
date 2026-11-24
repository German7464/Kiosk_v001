"""Server-side preparation of an exact frozen workspace snapshot.

The delivery catalog receives a package whose public data are derived only from
the frozen draft rows, never from the mutable Events database. The browser
cannot substitute bytes: the native reviewer recomputes this mapping from the
candidate document before signing.
"""
from pathlib import Path
import tempfile
import shutil

from . import mapping
from .exporter import export_events_package
from kiosk.delivery.publication import publish


def prepare_publication(workspace, secret, selected, targets, parents, delivery_state,
                        uploads_dir, resource_dir):
    stage = workspace.freeze(secret, selected)
    folder = Path(tempfile.mkdtemp(prefix='.roaming-export-', dir=delivery_state.root))
    try:
        package = folder / 'package'
        data = mapping.derive(stage['objects'], stage['settings'], stage['content_version'])
        export_events_package(None, uploads_dir, resource_dir, package, data=data)
        metadata = publish(delivery_state, package)
        return workspace.prepare(secret, selected, metadata, targets, parents, stage=stage['stage'])
    finally:
        workspace.discard(stage['stage'])
        shutil.rmtree(folder, ignore_errors=True)
