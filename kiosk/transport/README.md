# Managed HTTPS Transport

## Purpose

Provide opt-in Windows source startup with a supervised Caddy TLS proxy, loopback-only Waitress, explicit certificate trust, and bounded cleanup. Existing HTTP startup remains separate. Local integration and a bounded Windows Chrome trust lifecycle are verified; physical LAN/Android acceptance and a packaged service remain pending.

## Related Files

- `serve.py`: `--https-config` selection and argument conflicts.
- `kiosk/transport/profile.py`: strict versioned JSON profile, input validation, explicit CA trust, and generated proxy JSON.
- `kiosk/transport/runtime.py`: readiness, supervision, shutdown, and sanitized failures.
- `kiosk/transport/windows.py`: owned Windows Job Object.
- `tests/test_managed_https.py`: isolated profile, CLI, ownership, and failure checks.
- `tools/check_managed_https.py`: disposable real HTTPS and CLI verification.
- `tools/check_browser_https.py` and `tools/browser_trust.ps1`: explicit, operator-observed disposable Chrome trust lifecycle, requiring permission to modify CurrentUser root trust.
- `tests/test_browser_https.py`: ownership, failure cleanup, and observation/command checks without real trust-store writes.
- `docs/LAN_TRANSPORT.md`: configuration, provenance, trust boundaries, and pending acceptance.

## Related Database Tables

No transport table or migration. The existing application uses `users`, `events`, `tags`, `event_tags`, `settings`, and `content_versions`. Startup retains its normal initialization behavior. Transport configuration, proxy files, and shutdown do not replace existing passwords, installation keys, or content.

## Related Routes

All existing routes and static/media requests use the configured HTTPS origin. No Flask diagnostic or transport-management route is added. Caddy has a separate ephemeral administrative API restricted to IPv4 loopback with Host/Origin checks; it is inside the trusted local-process boundary.

## Related API Endpoints

Existing `/api/version`, `/api/events`, and `/api/tags` retain their JSON formats. Managed `/api/version` responses include a nonsecret, per-start `X-Kiosk-Instance` header so readiness cannot accept an unrelated backend. Caddy configuration identity is checked independently through its local administrative API.

## How the Feature Updates Content Version

Transport startup, certificate selection, and shutdown do not advance content version. Existing admin content writes retain their current version behavior.

## How the Feature Is Shown in Kiosk Mode

The launcher prints HTTPS addresses and opens `/kiosk` after verified readiness. `--no-client` prints addresses without opening a browser. Legacy `ClientKiosk.exe` is not launched in this profile until its HTTPS/trust behavior is independently verified.

## How the Feature Is Shown in TV Mode

`--open-tv` selects `/tv` at the same origin. Display code, polling, fullscreen authorization, and media formats are unchanged. Browser trust must already be enrolled; startup does not install roots or bypass certificate warnings.

## How the Feature Is Managed in Admin Panel

Existing administration runs over the same HTTPS origin with Secure, HttpOnly, SameSite=Lax cookies, current CSRF protection, and single-process authentication limits. Transport configuration and certificate operations are local operator actions, not admin-panel features.

## Run and Verify

Prepare the pinned Caddy binary and a valid server key/certificate/CA as described in `docs/LAN_TRANSPORT.md`, then run:

```powershell
.\.venv\Scripts\python.exe serve.py --https-config instance/https.json --no-client
.\.venv\Scripts\python.exe -m unittest tests.test_managed_https
.\.venv\Scripts\python.exe -m tools.check_managed_https --caddy logs/https-tools/caddy/caddy.exe --pwsh (Get-Command pwsh).Source
```

The developer check creates its own installations, credentials, certificate fixtures, and listeners; it never opens OS certificate stores or user databases. A copied source-only installation verifies the real CLI. It requires read-only Windows TCP/process inspection. Reports under ignored `logs/https/` contain fixed results, codes, and cleanup state, not credentials, cookies, bodies, keys, or runtime paths.

The separate opt-in browser helper **does** access `CurrentUser\\Root` after an explicit `trust` command. Use only with operator authorization; normal startup and the managed automated check do not enroll trust. It uses separate Chrome profiles, exact public-certificate digests, and owned-process cleanup. Windows may show enrollment/removal confirmation dialogs. See [browser verification](../../docs/LAN_TRANSPORT.md#controlled-windows-chrome-verification) for commands, observations, and recovery limits.
