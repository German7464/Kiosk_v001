# Events package v1 — documentation edition 1

## Existing implementation

Reference: [manifest validation](../../kiosk/publication/__init__.py),
[export and independent verification](../../kiosk/publication/exporter.py),
[exact capabilities](../../kiosk/publication/compatibility.py).
This is a directory format, not an archive/extraction or network protocol.
No signature, pairing, download, replication or application update is defined.

`manifest.json` is UTF-8 JSON. The exporter emits these fields:

| Field | Existing constraint |
| --- | --- |
| schema_version | Integer 1, excluding boolean/float |
| kind | `events` |
| revision | Nonempty string, at most128 characters; verifier requires decimal representation of public content_version |
| renderer | `events-v1` |
| resource_contract | Integer 1, excluding boolean/float |
| entrypoints | Exactly `["data/events.json"]` |
| files | Nonempty list, at most10,000 entries; each has path, size, sha256 |

Each size is an integer from0 through256MiB, excluding boolean/float.
SHA256 is64 lowercase hexadecimal characters over raw file bytes. Inventory
contains every regular file except manifest.json itself; extra/missing files
fail. The exporter sorts paths and serializes JSON with sorted keys, compact
separators and UTF-8 non-ASCII characters. The verifier does not require JSON
key order, inventory order or canonical whitespace. Unknown manifest/entry
properties are currently tolerated; do not describe them as rejected.
Windows store identity is SHA256 of canonical manifest JSON, distinct from
hashing arbitrary manifest file bytes; see [store](../../kiosk/publication/store.py).

Paths are relative POSIX paths, length1–240. No empty/dot/dot-dot component,
absolute path, backslash, colon, `< > " | ? * % #`, control character below32,
trailing dot/space or Windows reserved device basename (CON/PRN/AUX/NUL,
COM1–9/LPT1–9). Casefold duplicates are refused. Symlinks/reparse points,
including ancestors, are refused. These are portable-package rules even on
Android; do not relax them to match a more permissive filesystem.

## Public payload and resource closure

`data/events.json` has exactly content_version, events, tags, settings.
content_version is a positive integer (not boolean/float).

An event has exactly: id (unique positive integer), title, short_description,
full_description, place (strings), event_date, image_kiosk, image_tv, image_thumb
(string or null), sort_order (integer), tag_ids (list of unique existing integer
tag IDs). No date syntax/length bound is imposed here. Tags have exactly id
(unique positive integer) and name (string). Empty event/tag arrays are valid.
Exporter selects active events ordered by sort_order,event_date,id; tag IDs are
sorted. Hidden records, original image fields, DB and credentials are excluded.

Settings are a subset of site_title, interface_language, site_icon,
tv_slide_duration, kiosk_label, kiosk_heading, kiosk_description; all values
are strings. No arbitrary server settings are allowed.

Nonempty image references and site_icon must start `/static/uploads/` and pass
portable path rules. Their inventory paths omit the leading slash; referenced
images must pass Pillow image verification. No external media URL is allowed.
Inventory closure is exactly public JSON + referenced media + these13 resources
under `resources/`:

```text
static/css/base.css
static/js/kiosk_home.js
static/js/kiosk_events.js
static/js/tv.js
static/js/admin_flash.js
static/img/site_icon.png
templates/base.html
templates/kiosk_home.html
templates/kiosk_events.html
templates/tv.html
translations/en.json
translations/ru.json
translations/de.json
```

Translation resources are string-to-string JSON dictionaries. Site icon must be
a valid image. CSS imports/url dependencies and JS import/require dependencies
are refused by current regex checks. Template extends/include and static-file
dependencies must close within the resources. This is not proof of arbitrary
script safety: clients never execute package-supplied code.

## Limits and errors

Existing internal safety limits: manifest2MiB; inventory payload sum64MiB;
individual file256MiB;10,000 files. These are implementation bounds, not approved
product quotas or measured Android capacity. JSON/resources are buffered;
hashing/copying uses256KiB blocks. Hashes prove integrity, not authenticity.

Stable safe `PackageError` strings from package verification:

| Codes | Meaning |
| --- | --- |
| invalid_package | Malformed manifest/JSON, missing file or other wrapped validation/I/O failure |
| unsupported_client_contract, unsupported_package_contract | Unsupported capability tuple or entrypoints |
| manifest_too_large, file_too_large, package_too_large | Bound exceeded |
| unsafe_path, unsafe_source, unsafe_package_tree, not_regular_file | Unsafe path/tree/file |
| source_changed, integrity_failure, inventory_mismatch | Unstable bytes, size/hash mismatch, file-set mismatch |
| invalid_public_data, revision_mismatch | Public schema or revision mismatch |
| unsupported_media_reference, invalid_image, reference_closure_failure | Invalid/missing media or resource closure |
| invalid_translation_resource, unsupported_css_dependency, unsupported_script_dependency | Invalid resource/dependency |
| missing_display_template, missing_display_resource | Unclosed template/static reference |

Exporter-only codes additionally include invalid_content_version, missing_tag,
destination_exists, unsafe_destination, export_failed, staging_cleanup_failed.
Store/view/native errors have separate scopes, not this package error namespace.
Malformed manifest path generally becomes invalid_package through
validate_manifest; do not infer unsafe_path for every malformed path. For
multiple simultaneous defects first-error order is implementation-dependent;
cross-platform fixtures intentionally isolate defects. Diagnostics must not
include private paths, raw content or secrets.

## Shared rendering, existing versus proposed

The actual offline renderer is [renderer.py](../../kiosk/publication/renderer.py)
and client-owned [events.html](../../kiosk/publication/renderer_assets/events.html),
[events.css](../../kiosk/publication/renderer_assets/events.css),
[events.js](../../kiosk/publication/renderer_assets/events.js), with shipped
EN/RU/DE dictionaries in kiosk/translations (English fallback). Python/Jinja2
builds escaped HTML/bootstrap JSON; Pillow validates images. Browser JS/CSS
uses local DOM/resources without Flask, polling or network dependencies.
Package resources are verified legacy export resources, not this executable
client renderer. `view.json` is a separate generated artifact descriptor;
do not confuse it with the package manifest or invent another Events format.

Reuse the existing generated view and JS/CSS for initial Android experiments.
Python/Jinja2 are build-time tools, not an assumed Android runtime. A production
Android view-preparation adapter, distribution of trusted renderer assets,
storage/atomic activation, origin mapping, readiness and engine policy require
a bounded design and tests; Windows msvcrt/C#/WebView2 cannot be reused as Android
platform code. No second display implementation or template fork is approved.
Android WebView/version/device selection and all physical acceptance remain open.
