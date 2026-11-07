# Architecture

## Approach

Kiosk_v001 provides a modular Flask web application backed by SQLite. Public display routes and the admin/API blueprints share content storage, image processing, translations and content-version helpers. Feature packages are part of this application, not isolated module processes.

Source/MVP startup uses `run.py` for Flask development or `serve.py` for Waitress. The stage 3 Windows package adds a separate SCM service and a Tk/ttk Launcher. Managed HTTPS supervises Caddy in front of loopback Waitress. See the [Launcher](../kiosk/launcher/README.md) and [transport](../kiosk/transport/README.md) documentation for deployment details.

The distributed architecture in [the approved specification](TZ_RECONCILED.md) remains the target. Existing Events package preparation/store and the shared local renderer are implemented in `publication/`; the bounded Windows WebView2 shell/coordinator is in `display/`. Opt-in `delivery/` adds isolated enrollment, assignment/artifact transport, ready receipts and the operator publication UI. Its presence does not enable delivery in default installed startup. Android implementation lives in PC2's separate checkout; PC1's preparation-only Android README is not a current implementation inventory.

Persistent offline Events and bounded server/Android delivery have evidence in [the sole ledger](TZ_PROGRESS.md), with exact platform/build limitations. Full discovery, device/profile administration and trust lifecycle remain incomplete. Page/draft authoring and Events module extraction belong to stage 6; replication, signed updates and complete independent recovery remain later-stage targets. Package organization is not evidence of process isolation or release readiness.

## Evidence boundary

This describes the supplied implemented baseline, not an independent current source audit. Target contracts and stage allocation belong to the approved specification; actual checks and blockers belong to the progress ledger. Existing package organization does not prove process fault isolation. Use the [documentation index](README.md) for related operational documents.

## Current Folder Structure

```text
kiosk/
  app.py
  config.py
  extensions.py
  database.py
  server.py
  core/
  features/
  launcher/
  transport/
  publication/
  display/
  delivery/
  templates/
  static/
  translations/
instance/
logs/
docs/
requirements.txt
run.py
serve.py
launcher.py
launcher_service.py
```

## Separation Rules

- `app.py`, `config.py` and `server.py` provide application setup, configuration and source server startup.
- `core` contains shared credentials, session/request security, images, translations and content helpers.
- `features` contains the admin and public API blueprints. Each major feature module has one `README.md`.
- `launcher` contains installed storage, Windows installation/service control, runtime supervision and the desktop interface.
- `transport` contains managed HTTPS configuration, runtime and Windows helpers.
- `publication` contains Events export/verification, local persistent package storage and the shared client-owned renderer.
- `display` contains Windows native hosting, local view/cache coordination and runtime resource guards.
- `delivery` contains opt-in server-side device authorization, revision transport, receipt persistence and operator accounting; its SQLite database is separate from working Events storage.
- `templates` contains HTML templates only.
- `static` contains CSS, JavaScript, uploaded public assets, and interface assets.
- `database.py` contains database connection and initialization helpers.
- `instance` contains source/MVP runtime data, including the SQLite database, session key and original uploads. Installed machine data is separated under ProgramData as described in the Launcher documentation.
- `logs` contains ignored local development evidence and test reports; installed service logs use their separate machine-data directory.
- `translations` contains interface translation files.
- Business logic must not be placed inside templates.
- Database logic must not be mixed with routes.
- Kiosk, TV, preview, and admin modes should reuse shared logic where possible.
