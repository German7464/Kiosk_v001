# Chat handoff — 2026-10-21

## Scope and current state

Continue the selected V2 stage 2 disposable two-PC HTTPS LAN verification. Preserve the MVP. Stage 2 and security remain Partial; physical acceptance remains Pending. Do not start stage 3, the product Launcher, packaging, or unrelated requirements without owner selection.

Read [../AGENTS.md](../AGENTS.md), [TZ.md](TZ.md), [TZ_PROGRESS.md](TZ_PROGRESS.md), [V2_PLAN.md](V2_PLAN.md), [MVP_SCOPE.md](MVP_SCOPE.md), [LAN_TRANSPORT.md](LAN_TRANSPORT.md), and the relevant [transport README](../kiosk/transport/README.md) before implementation. Communicate in Russian; documentation/code remain English. Keep exploration targeted and changes minimal.

## Environment and delivered helpers

- Repository: `C:\Users\admin\PycharmProjects\Kiosk_v001`, Windows PowerShell, branch `v2`, Python `.venv\Scripts\python.exe`.
- Server: `192.168.1.165`; second Windows PC: `192.168.1.117`; HTTPS port: `8443`. Reconfirm if addresses change.
- The owner needs short numbered instructions and double-click launchers. Avoid manual command construction or fingerprint placeholders.
- `LAN_Server.cmd` runs `tools.lan_wizard`, prompting for addresses/disposable passwords and creating `logs/https/wizard-<timestamp>/Kiosk-LAN-Client.zip`.
- ZIP contents: `LAN_Client.cmd`, `LAN_Diagnose.cmd`, `check_lan_https.ps1`, `browser_trust.ps1`, `lan_wizard.ps1`, `session.json`, `wizard.json`, `authority.pem`, `fixture.png`.
- `LAN_Client.cmd` guides automatic HTTPS checks, server restart, authentication-budget coordination, operator Chrome observations, temporary root trust and cleanup. `LAN_Diagnose.cmd` performs offline manifest/local-address checks only.
- `tools/check_lan_https.py` owns disposable fixtures and strict completion gates; `tools/lan_wizard.py` adds fixture-only authenticated control. Production routes/API/schema are unchanged.
- PowerShell 7 and pinned Caddy are used; existing binary: `logs/https-tools/caddy/caddy.exe`.
- The ZIP contains a temporary test capability: transfer privately. Never publish passwords, tokens, or the whole bundle. No server private keys or working application data are included.
- Client folder previously used: `C:\Users\admin\Desktop\Desk\Kiosk-LAN-Client` on the second PC, inaccessible from this repository.
- Do not alter working credentials/data, kill unrelated processes, disable firewall/VPN, or automatically install trust. Optional exact-scope firewall changes require wizard consent/elevation. Root/profile ownership and interrupted-run recovery are documented in LAN_TRANSPORT.md.

## Last failure and correction

Owner report session `339a623d33720d9aa68dd713d8a044ce` completed eight groups: `unknown_authority`, `routes`, `csrf_cookie_login`, `upload_images_version_fullscreen`, `password_revocation`, `internal_ports_closed`, `plaintext_rejected`, `restart_session`.

The subsequent `forwarding` stage failed with MethodInvocationException at the old SendAsync line 74. HTTP counts: 27 x 200, 6 x 302, 1 x 403, 1 x 400. Diagnostic HTTP 200 belonged to the preceding completed request.

Actual .NET reproduction confirmed that HttpClient's hostile Host override changed TLS identity, causing RemoteCertificateNameMismatch before HTTP. Commit **`fa9668e` — `fix: preserve TLS identity in LAN Host rejection probe`** fixes this with a bounded credential-free SslStream probe: validate the configured origin using the existing explicit CA/name/validity/server-usage checks, send hostile HTTP Host, require actual HTTP 400. Unknown CA, wrong name and expired certificates still fail TLS. Diagnostics clear stale HTTP status before sending.

Earlier commits: `b008a3a` fixes strict-mode enumeration of addressless network adapters and adds sanitized stage/reason diagnostics; `7064b85` adds guided launchers; `265e438` prepares disposable LAN verification.

**Stopping point: the correction is implemented, tested and locally committed. No corrected fresh physical run has yet been supplied by the owner.** Earlier partial results do not complete physical acceptance.

## Next steps

The owner was instructed to stop the prior test server normally with Ctrl+C if running, start `LAN_Server.cmd`, transfer the newly generated ZIP, extract into a new folder on the second PC and run its `LAN_Client.cmd`. Preserve old reports and complete any old client cleanup/recovery before discarding its folder. Never mix session files or reuse an old archive.

Process the owner's next corrected-run result. If it fails, obtain sanitized diagnostics/report and relevant server output, reproduce that precise path, and make the smallest fix. Remaining physical gates include corrected forwarding/Host rejection, independent-source authentication budgets, actual Chrome trust/display/update observations, and final owned-root/profile/firewall/server cleanup. Do not mark section 18 or stage 2 Verified from partial evidence. User-operated test processes may remain running; inspect ownership before action.

## Verification checkpoint

At `fa9668e`: **117 Python tests passed in 90.727 seconds, no skips**. Real PowerShell/.NET checks cover Host HTTP 400 and unknown-CA/wrong-name/expired TLS rejection; the managed Caddy scenario passed the corrected probe and subsequent restart.

Compilation, both kiosk/TV JavaScript checks, PowerShell parsing, UTF-8/local documentation links and whitespace checks passed. Independent disposable Flask checks: `/kiosk`, `/kiosk/events`, `/tv`, `/preview`, `/admin/login`, `/api/version`, `/api/events`, `/api/tags` returned 200; unauthenticated `/admin` 302; missing-CSRF login 403; valid login 302; authenticated admin 200. These are prior implementation results, not tests rerun for this document.

Development tests changed no system trust/firewall or working installation. Full physical second-PC/browser/UAC/firewall/cleanup acceptance remains Pending.

Before this handoff edit: branch `v2` clean, ahead of `origin/v2` by 19, HEAD `fa9668e`. This documentation task adds a later commit; inspect current git state. No push was performed. MVP tag is unchanged.

After implementation changes, run appropriate tests and independent disposable Flask checks:

```powershell
./.venv/Scripts/python.exe -m compileall run.py kiosk
./.venv/Scripts/python.exe -m unittest tests.test_lan_wizard tests.test_lan_https
./.venv/Scripts/python.exe -m unittest discover -s tests
git diff --check
git status --short --branch
```

Real Windows socket/Schannel tests may need approved execution outside the sandbox; do not silently skip them. No IAB checks. Manual URLs during a fresh wizard session: `https://192.168.1.165:8443/kiosk`, `/tv`, `/preview`, `/admin/login`, `/api/version`. Browser trust must follow the wizard sequence.

## Ready-to-paste prompt for a new chat

```text
Continue in C:\Users\admin\PycharmProjects\Kiosk_v001. Read AGENTS.md and docs/CHAT_HANDOFF.md, then its referenced scope/progress/transport documents. Answer in Russian with simple steps.

We are finishing the selected V2 stage 2 disposable two-PC HTTPS LAN check, not starting later stages. Server: 192.168.1.165; second PC: 192.168.1.117; port 8443. Use LAN_Server.cmd and the fresh generated ZIP's LAN_Client.cmd.

Last implementation commit: fa9668e, fix: preserve TLS identity in LAN Host rejection probe. The previous client passed eight groups then failed at forwarding because HttpClient coupled hostile Host to TLS identity. The corrected probe retains certificate validation and requires HTTP 400. All 117 automated tests passed. A corrected fresh physical run has not yet been reported; read the handoff for evidence and pending gates.

Check current git state and process my new result, or guide me to stop the old test normally, create a fresh server session, transfer its new ZIP, and run the client from a new folder. Preserve reports and cleanup recovery; do not mix sessions. Reproduce any new error before a minimal fix, test and update documentation. Do not weaken TLS, treat partial evidence as full acceptance, change working data/credentials, or start stage 3. Keep my instructions short and handle technical investigation yourself.
```
