"""Trusted Maintenance side: accounts, sessions, scoped grants and signed review.

This package is a separate service from the Events content service. It owns its
database, secrets and origin; the content service is reached only through an
authenticated HTTPS contract. See ``README.md`` for the security boundary and
for the Combined/Separated placement contract.
"""
from .store import MaintenanceStore, MaintenanceError
from .permissions import BUNDLES, PERMISSIONS, permissions_for, require
from .service import create_maintenance_app

__all__ = ['MaintenanceStore', 'MaintenanceError', 'BUNDLES', 'PERMISSIONS',
           'permissions_for', 'require', 'create_maintenance_app']
