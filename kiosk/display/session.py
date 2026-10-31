"""Prepare a native-shell input from the last verified local publication."""
from pathlib import Path

from .cache import DEFAULT_CACHE_BYTES, prepare_package_view
from kiosk.publication.exporter import PackageError
from kiosk.publication.renderer import build_view
from kiosk.publication.store import PublicationStore


def prepare_active_view(store_root, destination, *, mode='kiosk'):
    """No server connection or active-pointer change; destination must be new."""
    package = PublicationStore(store_root).active()
    if package is None:
        raise PackageError('no_publication')
    return build_view(package, destination, mode=mode)


def install_for_display(source, store_root, cache_root, *, mode='kiosk', max_cache_bytes=DEFAULT_CACHE_BYTES):
    """Prepare a local view before publication commit; do not switch a running shell."""
    store_root, cache_root = Path(store_root).absolute(), Path(cache_root).absolute()
    if store_root == cache_root or store_root in cache_root.parents or cache_root in store_root.parents:
        raise PackageError('overlapping_display_storage')
    prepared = []
    def preflight(package):
        prepared.append(prepare_package_view(package, cache_root, mode=mode, max_bytes=max_cache_bytes))
    PublicationStore(store_root).install(source, pre_activate=preflight)
    return prepared[0]
