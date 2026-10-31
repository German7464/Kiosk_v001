# Architecture

## Approach

Kiosk_v001 provides a modular Flask web application backed by SQLite. Public display routes and the admin/API blueprints share content storage, image processing, translations and content-version helpers. Feature packages are part of this application, not isolated module processes.

Source/MVP startup uses `run.py` for Flask development or `serve.py` for Waitress. The stage 3 Windows package adds a separate SCM service and a Tk/ttk Launcher. Managed HTTPS supervises Caddy in front of loopback Waitress. See the [Launcher](../kiosk/launcher/README.md) and [transport](../kiosk/transport/README.md) documentation for deployment details.

The distributed architecture in [approved specification](TZ_RECONCILED.md) remains the target. Persistent client snapshots, groups, replication, versioned module contracts with selective process isolation, and signed updates are future stage work; current acceptance is recorded in [TZ Progress](TZ_PROGRESS.md).

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
- `templates` contains HTML templates only.
- `static` contains CSS, JavaScript, uploaded public assets, and interface assets.
- `database.py` contains database connection and initialization helpers.
- `instance` contains source/MVP runtime data, including the SQLite database, session key and original uploads. Installed machine data is separated under ProgramData as described in the Launcher documentation.
- `logs` contains ignored local development evidence and test reports; installed service logs use their separate machine-data directory.
- `translations` contains interface translation files.
- Business logic must not be placed inside templates.
- Database logic must not be mixed with routes.
- Kiosk, TV, preview, and admin modes should reuse shared logic where possible.
