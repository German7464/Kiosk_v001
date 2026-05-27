# Project Instructions for Codex

## Project goal

Build a local client-server kiosk system for displaying event cards on kiosks, Smart TV, preview screens, and an admin panel.

The project must follow the MVP scope only. Do not add features outside the MVP unless explicitly requested.

## Technology stack

Use:
- Python
- Flask
- SQLite
- HTML
- CSS
- JavaScript
- Pillow
- Waitress
- PyInstaller

Do not use React in the first version.

## Code style

Do not write comments inside code files.

Use clear names for functions, classes, variables, modules, and files instead of comments.

Do not create one large app.py file.

Do not mix HTML, business logic, and database logic.

Do not place CSS inside HTML.

Do not place JavaScript inside HTML unless it is absolutely minimal.

Do not duplicate logic between kiosk, TV, preview, and admin modes.

Do not hardcode absolute paths.

## Documentation rule

For every major feature module, create or update one README.md file in the related feature folder.

Do not create separate README.md files for individual functions, small helpers, minor internal changes, or bug fixes.

If a change affects an existing feature module, update that module's README.md instead of creating a new documentation file.

Documentation must be written in English.

Each feature README.md must include:
- Purpose
- Related files
- Related database tables
- Related routes
- Related API endpoints
- How the feature updates content version
- How the feature is shown in kiosk mode
- How the feature is shown in TV mode
- How the feature is managed in admin panel

Update docs/CHANGELOG.md after every completed task.

## Token-saving workflow

Before editing code:
1. Read AGENTS.md.
2. Read docs/MVP_SCOPE.md.
3. Read only the README.md of the feature being changed.
4. Do not analyze the whole repository unless explicitly asked.

For each task:
1. State the files that will be changed.
2. Make the smallest possible change.
3. Do not refactor unrelated code.
4. Do not add new dependencies unless necessary.
5. Update related README.md files only for major feature module changes.
6. Update docs/CHANGELOG.md.
7. Provide commands to run and test the change.

## MVP boundaries

The first version must include:
- local server startup
- /kiosk
- /kiosk/events
- /tv
- /preview
- /admin
- event CRUD
- tag management
- system title editing
- icon editing
- image upload
- image compression with Pillow
- SQLite database
- /api/version auto-update
- random delay protection against simultaneous client refresh
- interface translations
- visual style based on the prototype
- EXE build

Do not implement in MVP:
- automatic event translation
- separate event cards per language
- complex user roles
- cloud server
- internet publishing
- mobile app
- React frontend
- mandatory WebSocket
- view statistics
- backup system
- QR codes
- weather
- gallery
- news
- schedule
- ticker

## Communication language

When communicating with the user, answer in Russian.

Project documentation, file names, code identifiers, commit messages, and README files must remain in English.