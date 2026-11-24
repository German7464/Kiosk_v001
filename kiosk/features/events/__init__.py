"""Internal Events feature module with versioned publication metadata."""
from .mapping import (EVENT_TEXT, IMAGE_FIELDS, MAX_EVENT_ID, MappingError, SETTINGS_LIMIT,
                      derive, digest, public_bytes, settings, verify)
from .payload import PayloadError, validate, validate_payload

FEATURE_VERSION = 1
CONTRACT_VERSION = 1
DATA_VERSION = 1
CORE_VERSION = {'min': '3.0.17', 'max_exclusive': '4.0.0'}
CAPABILITIES = (
    'events.draft-payload-v1',
    'events.public-data-v1',
    'events.snapshot-mapping-v1',
)
DEPENDENCIES = ()
RESOURCES = (
    'data/events.json',
    'resources/static/css/base.css',
    'resources/static/js/admin_flash.js',
    'resources/static/js/kiosk_events.js',
    'resources/static/js/kiosk_home.js',
    'resources/static/js/tv.js',
    'resources/static/img/site_icon.png',
    'resources/templates/base.html',
    'resources/templates/kiosk_events.html',
    'resources/templates/kiosk_home.html',
    'resources/templates/tv.html',
    'resources/translations/de.json',
    'resources/translations/en.json',
    'resources/translations/ru.json',
)

METADATA = {
    'id': 'events',
    'version': FEATURE_VERSION,
    'contract_version': CONTRACT_VERSION,
    'data_version': DATA_VERSION,
    'core_version': CORE_VERSION,
    'publication': {'schema_version': 1, 'renderer': 'events-v1', 'resource_contract': 1},
    'capabilities': CAPABILITIES,
    'permissions': ('edit', 'publish'),
    'configuration_role': 'administrator',
    'dependencies': DEPENDENCIES,
    'resources': RESOURCES,
    'health_check': 'kiosk.features.events.health',
}


def health():
    """Return a small, side-effect-free readiness record for module discovery."""
    valid = (METADATA['id'] == 'events' and METADATA['version'] == FEATURE_VERSION
             and METADATA['contract_version'] == CONTRACT_VERSION
             and METADATA['data_version'] == DATA_VERSION)
    return {
        'id': 'events',
        'status': 'ok' if valid else 'failed',
        'version': FEATURE_VERSION,
        'contract_version': CONTRACT_VERSION,
        'data_version': DATA_VERSION,
    }
