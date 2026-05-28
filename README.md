# Kiosk_v001

Kiosk_v001 is a diploma project for a local client-server kiosk system that displays event cards on kiosks, Smart TV screens, preview screens, and an admin panel.

## Technology Stack

- Python
- Flask
- SQLite
- HTML
- CSS
- JavaScript
- Pillow
- Waitress
- PyInstaller

React is not used in the first version.

## MVP Goal

The MVP provides a local Flask application with event management, kiosk and TV display modes, preview mode, admin editing tools, image processing, translations, automatic client update checks, and an EXE build.

Only the MVP scope defined in [docs/MVP_SCOPE.md](docs/MVP_SCOPE.md) is allowed.

## Development Status

Initial documentation has been created. Application code, Flask structure, database files, templates, static assets, routes, services, and models have not been created yet.

## Working With This Project

Before future tasks, read:

1. [AGENTS.md](AGENTS.md)
2. [docs/MVP_SCOPE.md](docs/MVP_SCOPE.md)
3. The `README.md` inside the related major feature folder, when that feature exists

Do not analyze the whole repository for every task. Make the smallest useful change, stay inside the MVP, and update [docs/CHANGELOG.md](docs/CHANGELOG.md) after completed work.

## Developer Smoke Tests

Run the reusable MVP smoke tests before packaging:

```bash
python -m unittest discover -s tests
```

The tests use an isolated temporary SQLite database and temporary upload folders. They do not use `instance/kiosk.sqlite`.
