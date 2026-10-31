# MVP Scope — historical compatibility baseline

This records the original MVP boundary, not the current v2 feature exclusions. Preserve its implemented behavior on supported migrations. The [approved v2 specification](TZ_RECONCILED.md) and [current ledger](TZ_PROGRESS.md) govern present scope and acceptance: Android clients, product roles and backups are v2 targets even though excluded from the original MVP. Optional additions still require owner selection. [Measured baseline](MVP_BASELINE.md); [development recovery](DEVELOPMENT_RECOVERY.md); [documentation index](README.md).

## Included

- Local server startup
- `/kiosk`
- `/kiosk/events`
- `/tv`
- `/preview`
- `/admin`
- Event CRUD
- Tag management
- System title editing
- Icon editing
- Image upload
- Image compression with Pillow
- SQLite database
- `/api/version` auto-update support
- Random delay protection against simultaneous client refresh
- Interface translations
- Visual style based on the prototype
- EXE build

## Excluded

- Automatic event translation
- Separate event cards per language
- Complex user roles
- Cloud server
- Internet publishing
- Mobile app
- React frontend
- Mandatory WebSocket
- View statistics
- Backup system
- QR codes
- Weather
- Gallery
- News
- Schedule
- Ticker
