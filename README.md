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

The MVP remains the compatibility baseline. Version 2 follows [the specification](docs/TZ.md) and the selected stage recorded in [progress](docs/TZ_PROGRESS.md).

## Development Status

The MVP baseline is preserved by the annotated Git tag `v1.0.0-mvp`. Version 2 development continues on branch `v2`; version 2 is not a completed release. See [Version 2 Plan](docs/V2_PLAN.md) for priorities, validation limits, and rollback instructions.

The MVP Flask application is implemented with SQLite storage, admin management flows, public display routes, public API endpoints, image processing, translations, responsive layouts, and reusable developer smoke tests.

## Working With This Project

Before future tasks, read:

1. [AGENTS.md](AGENTS.md)
2. [docs/TZ.md](docs/TZ.md), [progress](docs/TZ_PROGRESS.md), [current plan](docs/V2_PLAN.md), and [MVP baseline](docs/MVP_SCOPE.md)
3. The `README.md` inside the related major feature folder, when that feature exists

Do not analyze the whole repository for every task. Make the smallest useful change, stay inside the selected stage, and update progress and [docs/CHANGELOG.md](docs/CHANGELOG.md) after every stage.

## Verified Dependency Installation

The pinned dependency baseline is Windows x64, CPython 3.14.5, and pip 26.1.1. `requirements.txt` pins all 16 runtime and build packages, including transitive dependencies; pip is a separate bootstrap tool. Other Python versions, operating systems, and architectures are not verified by this checkpoint.

Create a new environment with an installed CPython 3.14.5 interpreter. Use a different environment directory if `.venv` already contains your working installation:

```powershell
py -3.14 -c "import sys; assert sys.version_info[:3] == (3, 14, 5), sys.version"
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install pip==26.1.1
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m compileall run.py kiosk
.\.venv\Scripts\python.exe -m PyInstaller --version
node tests/test_kiosk_request_security.js
```

Node is needed only for the JavaScript development check, not application startup. Package installation requires an available package index or a separately prepared local package source; everyday application operation does not require an index or Internet access. Do not recreate a working environment merely to run the application.

To update dependencies, select versions deliberately in a separate environment, keep all required transitive packages pinned, run `pip check`, compare installed package versions with `requirements.txt` (excluding the separately pinned pip), and repeat the complete Python/JavaScript and Flask route checks. Update the requirements and verification record together in one reviewed commit. Do not regenerate pins from an environment containing unrelated tools. Existing pins reproduce package versions, not artifact hashes or byte-identical executables. A successful PyInstaller version check does not verify an EXE build or a clean-machine installation.

## Running Locally

First create the administrator in a local interactive terminal (no default account is created):

```bash
python serve.py --setup-admin
Kiosk_v001.exe --setup-admin
```

Use only the command matching your installation. Enter and confirm a password of 12 to 128 characters. Input is hidden; do not supply passwords as command arguments or through a pipe. This command refuses to run when accounts already exist and does not launch the server or browser.

Development mode:

```bash
python run.py
```

Waitress mode for local production-style testing:

```bash
python serve.py
```

By default, `python serve.py` and the packaged `Kiosk_v001.exe` bind to `0.0.0.0`, start the server, and then try to launch `ClientKiosk.exe` from the same folder. If `ClientKiosk.exe` is missing or fails, the launcher falls back to the default browser and still keeps the server running.

Disable automatic client and browser launching when you only want the server:

```bash
python serve.py --no-client
Kiosk_v001.exe --no-client
```

Launcher mode for opening kiosk or TV after startup:

```bash
python serve.py --open-kiosk
python serve.py --open-tv
python serve.py --host 0.0.0.0 --open-kiosk
python serve.py --host 0.0.0.0 --open-tv
python serve.py --host 0.0.0.0 --port 5000 --open-kiosk
```

If a local server is already running on `http://127.0.0.1:<port>/api/version`, the launcher reuses it instead of starting a duplicate server.

The commands below currently serve plaintext HTTP, including administrative credentials and sessions when used over LAN. They do not implement protected LAN deployment. The approved [standalone LAN transport design and isolated HTTPS prototype](docs/LAN_TRANSPORT.md) specify HTTPS, client trust setup, and acceptance checks; protected normal startup remains pending. Use loopback for local development.

LAN startup for phones, tablets, kiosks, and Smart TV browsers:

```bash
python serve.py --host 0.0.0.0
```

You can also bind to a specific host or port:

```bash
python serve.py --host 127.0.0.1
python serve.py --host 192.168.1.117
python serve.py --port 5000
python serve.py --host 0.0.0.0 --port 5000
```

Use `python serve.py --host 127.0.0.1` when you need local-only startup.

Waitress mode prints active local URLs for:

```text
http://127.0.0.1:5000/kiosk
http://127.0.0.1:5000/kiosk/events
http://127.0.0.1:5000/tv
http://127.0.0.1:5000/preview
http://127.0.0.1:5000/admin/login
http://127.0.0.1:5000/api/version
```

When you start with `--host 0.0.0.0`, use the computer LAN IP address from another device, for example:

```text
http://192.168.1.117:5000/tv
```

If another device cannot connect, disable VPN, check that both devices are on the same Wi-Fi, and allow TCP port 5000 in Windows Firewall.

To reset the local admin password from the command line:

```bash
python serve.py --reset-admin-password
```

The packaged EXE supports the same reset mode:

```text
Kiosk_v001.exe --reset-admin-password
```

The reset command requires a local interactive terminal, asks for a new password twice with hidden input, updates only the existing `admin` password hash and timestamp, and exits without starting the server. It does not print the password. If no accounts exist, use `--setup-admin` instead. Passwords must contain 12 to 128 characters.

Existing `admin / admin` credentials are blocked for login, administrative actions, and kiosk fullscreen unlock until replaced locally. Startup does not replace existing hashes. Other existing credentials remain unchanged. Sessions from earlier releases require a new login; changing or resetting a password invalidates all previous sessions for that account. A valid session survives server restart when credentials and the installation key remain unchanged. Browser password changes return to login.

These commands are a temporary local setup path before the v2 Launcher. They require OS access to the installation and do not provide a web recovery endpoint. Administrative forms now require a session CSRF token, and password checks share per-source limits (10 per username and 40 total in 60 seconds). Errors return 403 or 429; reload stale forms or wait for the Retry-After interval. Counters reset on restart and are scoped to one server process. See the admin feature README for limits. LAN transport protection has a [verified isolated loopback prototype](docs/LAN_TRANSPORT.md); protected normal startup, browser trust, and physical LAN deployment remain pending.

To launch the packaged kiosk client automatically, place `ClientKiosk.exe` next to `Kiosk_v001.exe`. If it is not present, the launcher falls back to the default browser. If both launch attempts fail, the server still starts and prints the manual URLs.

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

## Request Security Checks

```powershell
.\.venv\Scripts\python.exe -m compileall run.py kiosk
.\.venv\Scripts\python.exe -m unittest discover -s tests
node tests/test_kiosk_request_security.js
git diff --check
git status --short --branch
```

The Node command is a standalone development check for kiosk request/error behavior; Node is not an application dependency. Automated Flask checks cover forms with rendered CSRF tokens and isolated runtime data. Use Chrome through Windows-MCP only when automated tests leave browser-specific behavior unresolved.

Image safety defaults: 20 MiB per request, 16 MiB per file, 25 million pixels; see the admin feature README for configuration and error behavior. Run `python -m unittest discover -s tests` to include upload boundary and isolated Waitress HTTP checks.

## Local MVP Baseline Measurement

On Windows, with the pinned dependencies installed:

```powershell
.\.venv\Scripts\python.exe -m tools.measure_mvp_baseline
```

The fixed profile starts its own four-thread Waitress process on a free loopback port and creates a disposable database, administrator, 100 events (80 active), 20 tags, 300 assignments, and 10 seeded synthetic images. It accepts no database path or external server address. It verifies HTTP authentication, API content, generated images, and content-version advancement before measuring seven public routes (three warmups and 50 sequential samples each), then 1000 requests with ten concurrent clients. Both client and server run on this computer. HTTP clients open connections through urllib; this is not a browser or 100-device simulation.

JSON reports are stored under ignored `logs/measurements/`. Nonzero exit means a request, validation, sampling, timeout, or cleanup error; inspect the sanitized error records and any completed metrics. Requests have a ten-second timeout, and a 180-second watchdog terminates the temporary server if the scenario overruns; shutdown/cleanup can take additional time. Temporary data is removed after stopping the server. No working server or account is used. Windows process working memory is sampled every 100 ms throughout dataset preparation and measurements; its observed maximum is not a guaranteed peak. Reports contain no test passwords, cookies, installation secrets, hostnames, or server addresses.

See [MVP Baseline](docs/MVP_BASELINE.md) for the measured checkpoint, metric definitions, and limitations. The command is an opt-in developer measurement, not part of normal application startup or a release acceptance threshold.


## Isolated HTTPS Prototype

The opt-in Windows developer check uses a pinned official Caddy 2.11.7 executable and PowerShell 7.6.6/.NET for disposable certificate generation. It creates its own loopback servers and temporary data, verifies real TLS with a private Python trust context, and removes the temporary installation. It does not change OS trust, firewall, existing servers, passwords, or normal application startup. No new Python dependency is needed. Read-only listener inspection must be permitted by the execution environment.

Prepare the binary with the verified download/checksum procedure in [LAN transport](docs/LAN_TRANSPORT.md#proxy-provenance), then run:

```powershell
.\.venv\Scripts\python.exe -m tools.check_https_prototype --caddy logs/https-tools/caddy/caddy.exe --pwsh (Get-Command pwsh).Source
.\.venv\Scripts\python.exe -m unittest tests.test_https_prototype
```

Reports and downloaded tools stay in ignored logs directories. This checks loopback HTTPS, not Chrome trust, physical LAN/Android TV, installation, or production certificate maintenance. Public APIs and database formats are unchanged.
