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

The MVP Flask application is implemented with SQLite storage, admin management flows, public display routes, public API endpoints, image processing, translations, responsive layouts, and reusable developer smoke tests.

## Working With This Project

Before future tasks, read:

1. [AGENTS.md](AGENTS.md)
2. [docs/MVP_SCOPE.md](docs/MVP_SCOPE.md)
3. The `README.md` inside the related major feature folder, when that feature exists

Do not analyze the whole repository for every task. Make the smallest useful change, stay inside the MVP, and update [docs/CHANGELOG.md](docs/CHANGELOG.md) after completed work.

## Running Locally

Development mode:

```bash
python run.py
```

Waitress mode for local production-style testing:

```bash
python serve.py
```

The default local kiosk URL is:

```text
http://127.0.0.1:5000/kiosk
```

## Building The Windows EXE

Build the local Waitress server executable with PyInstaller:

```bash
python -m PyInstaller --clean --noconfirm Kiosk_v001.spec
```

The output folder is:

```text
dist/Kiosk_v001/
```

Start the packaged app with:

```text
dist/Kiosk_v001/Kiosk_v001.exe
```

The EXE starts the Waitress server and prints the kiosk URL. Runtime data stays outside the executable in the output folder, including `instance/kiosk.sqlite`, `instance/uploads/`, and `kiosk/static/uploads/`.

Do not commit generated packaging or runtime data:

```text
build/
dist/
instance/
logs/
kiosk/static/uploads/
```

## Developer Smoke Tests

Run the reusable MVP smoke tests before packaging:

```bash
python -m unittest discover -s tests
```

The tests use an isolated temporary SQLite database and temporary upload folders. They do not use `instance/kiosk.sqlite`.
