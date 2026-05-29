# Architecture

## Overview

Kiosk_v001 is a local modular Flask monolith. It is deployed as one application, but keeps startup, configuration, database access, feature routes, templates, static assets, translations, image processing, and tests separated.

The normal production entrypoint is `serve.py`, which starts the Flask app with Waitress. `run.py` remains the local Flask development entrypoint.

## Main Components

- `kiosk/app.py` contains the application factory, blueprint registration, template helpers, static upload route handling, and database initialization hookup.
- `kiosk/config.py` defines project paths, runtime paths, server defaults, upload paths, and persistent runtime secret key handling.
- `kiosk/database.py` owns SQLite connection, schema initialization, default data, content version updates, and small database helpers.
- `kiosk/server.py` owns Waitress startup helpers, startup URL output, LAN URL detection, local duplicate-server checks, optional client/browser launching, and CLI admin password reset support.
- `serve.py` parses production CLI arguments and starts Waitress or CLI reset mode.
- `run.py` starts Flask development mode.
- `Kiosk_v001.spec` defines the PyInstaller bundle inputs.

## Runtime Data

Runtime data stays outside bundled application code:

- `instance/kiosk.sqlite` stores SQLite data.
- `instance/uploads/` stores private uploaded originals.
- `instance/secret_key.txt` stores the persistent Flask session secret unless `KIOSK_SECRET_KEY` is set.
- `kiosk/static/uploads/` stores optimized public image outputs during development.
- In the packaged EXE, equivalent runtime folders live beside `Kiosk_v001.exe`.

Generated runtime and packaging folders must not be committed.

## Features

The admin feature module lives in `kiosk/features/admin/` and manages authentication, events, tags, event-tag assignment, settings, image uploads, icon uploads, password changes, admin preview UI, and kiosk fullscreen unlock validation.

The public API feature module lives in `kiosk/features/api/` and exposes read-only JSON endpoints:

- `GET /api/version`
- `GET /api/events`
- `GET /api/events/<id>`
- `GET /api/tags`

Public display templates live in `kiosk/templates/`:

- `kiosk_home.html`
- `kiosk_events.html`
- `tv.html`
- `preview.html`

Admin templates also live in `kiosk/templates/`, including shared admin event preview partials.

## Static Assets And Translations

- `kiosk/static/css/base.css` contains shared CSS for kiosk, TV, preview, and admin screens.
- `kiosk/static/js/` contains page-specific JavaScript for kiosk home, kiosk events, TV, preview, admin event previews, event tag assignment, and admin flash messages.
- `kiosk/translations/ru.json`, `en.json`, and `de.json` contain interface translation strings.
- Event titles, event descriptions, places, and admin-entered tag names are not automatically translated.

## Image Processing

Image processing is implemented in `kiosk/core/images.py` with Pillow.

Event image uploads keep a private original and create optimized public variants for kiosk, TV, and thumbnail usage. System icon upload creates an optimized public icon. Private originals are not served publicly.

## Startup And Packaging

`serve.py` starts Waitress on `0.0.0.0` by default so phones, tablets, kiosks, and Smart TV browsers can connect over the LAN. Local-only mode is available with `--host 127.0.0.1`.

Startup prints local URLs, LAN URLs when available, and firewall/VPN/Wi-Fi hints. It can optionally reuse an existing local server, launch an external `ClientKiosk.exe`, or fall back to the default browser. `--no-client` disables client and browser launching.

The PyInstaller spec bundles templates, static CSS, static JavaScript, static images, and translation JSON files. Runtime data remains external beside the EXE.

## Tests

Regression smoke tests live in `tests/test_mvp_smoke.py`. They use temporary SQLite databases and temporary upload folders. They cover public routes, admin authentication, startup helper behavior, optional client/browser launch helpers, runtime secret handling, kiosk fullscreen unlock validation, event/tag/image flows, settings/content version behavior, API visibility, translations, and icon output.
