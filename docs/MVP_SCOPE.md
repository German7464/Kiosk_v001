# MVP Scope

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

## Post-MVP Usability And Security Additions

These items were added after the original MVP to make the local system easier and safer to operate. They should be treated as practical additions, not as original MVP requirements.

- LAN-accessible production startup by default with host `0.0.0.0`
- Optional external `ClientKiosk.exe` launcher
- Default browser fallback when the external client is unavailable
- `--no-client` startup mode
- `/kiosk` fullscreen button
- Admin-protected `/kiosk` fullscreen exit using current admin credentials
- `/tv` fullscreen button
- `/admin` link to `/preview`
- `/kiosk/events` inactivity warning with countdown
- Editable kiosk home label, heading, and description
- Persistent runtime Flask `SECRET_KEY` handling
- Strengthened regression smoke tests

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
