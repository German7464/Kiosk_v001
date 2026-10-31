"""Client-owned package compatibility; never execute code supplied by a package."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ClientRuntime:
    """Exact supported (schema, kind, renderer, resource contract) combinations."""

    contracts: frozenset[tuple[int, str, str, int]]

    def accepts(self, manifest):
        schema = manifest.get('schema_version')
        resources = manifest.get('resource_contract')
        kind = manifest.get('kind')
        renderer = manifest.get('renderer')
        if type(schema) is not int or type(resources) is not int:
            return False
        if not isinstance(kind, str) or not isinstance(renderer, str):
            return False
        return (schema, kind, renderer, resources) in self.contracts


EVENTS_RUNTIME = ClientRuntime(frozenset({(1, 'events', 'events-v1', 1)}))
