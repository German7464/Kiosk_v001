# Events Feature

## Purpose

This is the first internal Kiosk feature module. It owns the immutable public
Events mapping, the Events draft-payload validator and static compatibility
metadata. It is imported directly; there is no plugin discovery, virtual module
loading or third-party installation path.

## Metadata

| Field | Value |
| --- | --- |
| ID | `events` |
| Feature version | `1` |
| Publication contract | `1` |
| Events data version | `1` |
| Core versions | `>=3.0.17,<4.0.0` |
| Capabilities | draft payload v1, public data v1, snapshot mapping v1 |
| Dependencies | none |
| Resources | `data/events.json` and the allowlisted Events renderer assets |
| Health check | `kiosk.features.events.health` |

`METADATA` is static data, including the declared health-check name. There is no
loader for that name. `health()` performs a side-effect-free consistency check
and returns `status: ok`. A Core or contract change must update this metadata
and the module version explicitly; it is not inferred at runtime.

## APIs

- `mapping.derive(objects, settings, content_version)` returns the canonical
  public Events document for one frozen snapshot.
- `mapping.public_bytes(...)` returns the exact `data/events.json` bytes used by
  package export and native review.
- `mapping.verify(...)` refuses substituted public data.
- `payload.validate_payload(value, error=PayloadError)` validates one draft
  payload with the current workspace codes and statuses. A caller with its own
  coded exception can pass that class as `error`; the workspace integrator can
  therefore retain its existing `WorkspaceError` contract.

The existing `kiosk.publication.mapping` module remains a compatibility facade
for all current callers. Moving code into this feature module does not change
mapping output bytes, legacy routes or publication contracts.

## Fixture Seed

`kiosk.publication.baseline.seed` remains the explicit disposable-only Stage 5
transition. It verifies the complete package and expected package identity,
preserves nullable dates, all three image variants and Tags, and never rewrites
the legacy Events database or package. Repeating the exact same seed against
the unchanged baseline is idempotent and returns the original result. A changed
workspace, a different package or a corrupted package is refused without
changing rows or publication versions.

## Checks

Run the focused source checks from the repository root:

```powershell
python -m unittest tests.test_stage6_events tests.test_roaming_mapping tests.test_roaming_baseline
git diff --check
```
