# Project Context

## Purpose

Kiosk_v001 is a local event display system for a diploma project. It lets administrators manage event cards and display them on kiosk screens, Smart TV/browser screens, preview screens, and admin workstations.

## Target Environment

The intended environment is a local Windows kiosk/server computer. The server runs locally and is reachable on the same LAN for phones, tablets, kiosk browsers, and Smart TV browsers.

Normal production startup through `python serve.py` or the packaged `Kiosk_v001.exe` binds to `0.0.0.0` by default. Local-only mode remains available with `--host 127.0.0.1`.

## Target Devices

- Main kiosk touch screen on the server computer
- Smart TV or browser display on the LAN
- Admin PC or browser
- Phones and tablets on the LAN for checks and manual operation

## Main Routes

- `/kiosk` for kiosk home display mode
- `/kiosk/events` for kiosk event cards
- `/tv` for TV display mode
- `/preview` for preview display mode
- `/admin` for administration
- `/api/version` for client update checks

## Runtime Data

Runtime data remains external and should not be committed:

- SQLite database in `instance/kiosk.sqlite`
- Private uploaded originals in `instance/uploads/`
- Runtime Flask session secret in `instance/secret_key.txt`
- Public optimized uploaded assets in `kiosk/static/uploads/` during development
- Equivalent external folders beside the packaged EXE

## Current Branch

The `audit-cleanup` branch is for regression tests, read-only audit findings, small cleanup stages, and documentation updates. It should avoid new user-facing features unless explicitly requested.

## System Idea

The system runs on a local server. Display clients open routes in a browser or optional external kiosk client and periodically check the content version. Admin changes update stored content and version so kiosk, TV, and preview clients can refresh without cloud services.
