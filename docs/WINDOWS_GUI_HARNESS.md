# VM GUI harness — required method (AI install and usage guide)

This is the authoritative repository copy of the guide that is also installed on
both lab VMs as `C:\KioskLab-20261111\gui\AI_INSTALL.md`.

- Required by `AGENTS.md` for GUI work on the lab VMs.
- If the harness is missing, installation is a prerequisite: ask the owner first,
  then install from the offline payload.
- Offline payload: `dist\gui-harness\payload` (PC1, gitignored) and
  `C:\KioskLab-20261111\gui\payload` (both VMs).
- Accepted-run evidence: `logs\windows-gui-automation-20261112\`.
- Do not change the `RemoteDebuggingAllowed` policy, install the lab CA, or bypass
  TLS without the owner's explicit decision.

---

# GUI test harness — offline install and use (for an AI executor)

This is the required method for GUI work on the Kiosk lab VMs. It uses Microsoft
UI Automation for native windows, Playwright over CDP for browser/WebView2 HTML,
and the existing Win32 helpers only for Tkinter. It returns small JSON facts, not
screenshots.

If a VM does not have the harness, installing it is a prerequisite: ask the owner
for permission, then follow this file. Do not fall back to screenshot-per-click
loops as the primary method.

## 1. Prerequisites

- Windows 10/11 VM with an active interactive console session (UIA needs a desktop).
- SSH access from PC1 with strict host keys.
- PowerShell 5.1 (built in); no policy change is required (`LocalMachine`
  `Unrestricted` on both lab VMs).
- The offline payload on PC1: `dist\gui-harness\payload` (gitignored), or the copy
  already on the VM at `C:\KioskLab-20261111\gui\payload`.
- No Internet is needed on the VM.

## 2. Install

```powershell
# from PC1, repository root
scp -r dist\gui-harness\payload WorkPc4@192.168.1.124:C:/KioskLab-20261111/gui/payload
ssh WorkPc4@192.168.1.124 "powershell -NoProfile -NonInteractive -File C:\KioskLab-20261111\gui\payload\scripts\install-harness.ps1 -Source C:\KioskLab-20261111\gui\payload"
```

The installer verifies the Node archive SHA-256, extracts the portable runtime,
copies `playwright-core` and the scripts, writes `installed.json`, and runs
`selfcheck.ps1`. It is idempotent. Use the same command on PC5 with `WorkPc5`.

Expected self-check: `ok=True`, Node `v24.22.3`, Playwright `1.65.0`, UIA loaded,
all files present, and `remote_debugging` matching the VM policy (PC5
`blocked_by_policy`, PC4 `allowed`; see §4). On PowerShell 5.1 always invoke
scripts with `-File`; a native command inside `powershell -Command -` consumes the
rest of the script from stdin.

## 3. Verify the two engines

### UI Automation (interactive session)

```powershell
ssh WorkPc4@192.168.1.124 "powershell -NoProfile -NonInteractive -File C:\KioskLab-20261111\gui\run-helper.ps1 -ScriptPath C:\KioskLab-20261111\gui\uia-smoke.ps1"
```

`uia-smoke.ps1` launches Notepad, inventories it with UIA, closes it with
`WindowPattern`. Expected: `ok=True`, named controls present, `close=Window.Close`.

On PC5 the product path additionally works:

```powershell
ssh WorkPc5@192.168.1.125 "powershell -NoProfile -NonInteractive -File C:\KioskLab-20261111\gui\run-helper.ps1 -ScriptPath C:\KioskLab-20261111\gui\journey.ps1"
```

The journey needs the administrator password in `.admin-pw` (see §5) and the
installed client running. It returns one `journey.json` with `ok=true`.

### Playwright over CDP (Chrome; on a VM where browser debugging is allowed, e.g. PC4)

```powershell
# launch a real Chrome with a disposable profile, loopback DevTools only
ssh WorkPc4@192.168.1.124 "powershell -NoProfile -NonInteractive -File C:\KioskLab-20261111\gui\run-helper.ps1 -ScriptPath C:\KioskLab-20261111\gui\launch-chrome.ps1 -ScriptArguments @('-Chrome','C:\Program Files\Google\Chrome\Application\chrome.exe','-Url','file:///C:/KioskLab-20261111/gui/selftest/index.html','-Port','9334','-Profile','C:\KioskLab-20261111\gui\chrome-profile','-Out','C:\KioskLab-20261111\gui\chrome-launch.json')"
# drive it from a normal SSH session (CDP is loopback TCP)
ssh WorkPc4@192.168.1.124 "& 'C:\KioskLab-20261111\gui\runtime\node\node-v24.22.3-win-x64\node.exe' 'C:\KioskLab-20261111\gui\runtime\selftest.mjs' --port 9334 --out C:\KioskLab-20261111\gui\selftest-result.json"
```

Expected `ok=true` and `result = "hello agent"`. Stop Chrome by its PID from
`chrome-launch.json`, then delete `chrome-profile`.

## 4. Product-specific notes

- **PC5 client:** `journey.ps1` launches the real admin WebView2 shell with
  `--diagnostic-port 9333` (explicit harness launch; the product connection window
  always passes 0). Chromium binds 127.0.0.1 only; TLS and authorization are
  untouched and never bypassed.
- **WinForms admin buttons** appear to UIA as `Pane` with a name and no managed
  pattern. `uia.ps1 -Action invoke` sends `BM_CLICK` to the named native button
  (no coordinates).
- **Tkinter** exposes only unnamed panes (42/42 in the client). Use the existing
  `action.ps1` relative-click helper for Tk, and verify the effect through the
  product's JSON status, not a screenshot.
- **Browser debugging policy.** The lab images ship with
  `RemoteDebuggingAllowed=0` for Google Chrome, Chromium and Microsoft Edge
  (`HKLM\SOFTWARE\Policies\...`). On **PC4** it was set to `1` on 2026-11-12 with
  the owner's explicit permission, so Chrome/Edge/Chromium and Playwright can use
  a loopback DevTools endpoint. Revert by setting it back to `0` under
  `HKLM\SOFTWARE\Policies\Google\Chrome`, `...\Chromium` and
  `HKLM\SOFTWARE\Policies\Microsoft\Edge`. Ask the owner before changing it on any
  other VM. PC5 remains at `0` and uses WebView2, which is not governed by that
  policy.
- **PC4 server:** the disposable lab CA is already in `LocalMachine\Root`
  (thumbprint `5E96AF2A7C3DBB8156CF66C12CFE8A2565A6917D`), Chrome accepts the
  served certificate, and the full login/devices/logout journey passes
  (`evidence\pc4\pc4-web-journey.json`, 2 261 ms). `curl`/Schannel still refuses
  revocation checking while the VM is offline; Chrome tolerates it. Do not bypass
  TLS.
- **PC5** trusts the lab CA and hosts the client; it is the reference machine for
  the WebView2 journey.

## 5. Administrator password

The password is read from the server's private file and passed over stdin; it is
never printed, never placed on a command line, and never written to evidence.
Playwright reads `.admin-pw` and deletes it before acting.

```powershell
$pw = (& ssh WorkPc4@192.168.1.124 "type C:\KioskLab-20261109\server\private\admin-password.txt") -join "`n"
$pw = $pw.Trim()
$pw | ssh WorkPc5@192.168.1.125 "powershell -NoProfile -NonInteractive -File C:\KioskLab-20261111\gui\putpw.ps1"
```

If a quoting error exposes the password, stop and ask the owner to rotate it.

## 6. Rules

- One-shot interactive tasks only; never leave a scheduled task running.
- DevTools only on loopback, only for an explicit diagnostic launch.
- No TLS bypass, no `-ExecutionPolicy Bypass`, no product source changes.
- Delete only harness-created profiles/temp files; `cleanup.ps1` does this.
- Keep evidence in `gui\evidence\`; secrets never go there.
- Report actual HTTP/URL/JSON facts, not screenshots, unless a visual check is
  explicitly required.

## 7. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `window_not_found` from a normal SSH call | Session 0 has no desktop; run UIA through `run-helper.ps1`. |
| Helper reports `started=True` but nothing happened | Old runner unregistered before start; current `run-helper.ps1` waits for the instance. |
| `admin_policy_refused` / exit 2 | The admin profile was pre-created with an inherited writer ACE; let the shell create it (`launch-admin.ps1` deletes it first). |
| Admin launch waits 45 s | Port busy or shell policy failure; read `admin-launch.json` and `admin-status.json`. |
| Playwright `page.fill` timeout on login | The initial pair page is public; navigate to `/admin/login` first (`webview.mjs` does). |
| Close reports `cleanup=not_attempted` | Closed before the shell finished post-logout cleanup; wait for `logout_cleared` (journey does). |
| UIA sees buttons but cannot invoke | WinForms panes have no managed pattern; `uia.ps1` falls back to `BM_CLICK` by name. |
| Chrome launch times out, no `127.0.0.1:port` | `RemoteDebuggingAllowed=0`. PC4 is set to 1 (owner permission); PC5 stays 0 and uses WebView2. Do not change another VM without the owner. |
| `curl` fails with `CRYPT_E_NO_REVOCATION_CHECK` | The offline VM cannot check revocation. Chrome still loads the page because the lab CA is a local root; do not disable TLS checks. |

## 8. Stored artifacts

- Harness on the VM: `C:\KioskLab-20261111\gui` (scripts, runtime, payload, evidence).
- Offline payload and this guide: `dist\gui-harness\` on PC1 and
  `gui\payload` on both VMs.
- Policy: `AGENTS.md` and `docs\WINDOWS_GUI_HARNESS.md`.

## PC4 clock maintenance note - 2026-11-15

During profile acceptance, unstable guest UTC slew prevented native time confirmation. PC4 VBoxService intentionally retains --disable-timesync; other Guest Additions and W32Time configuration remain unchanged. Original service configuration: C:/KioskLab-DeviceProfiles-20261115/time-configuration-before.json. Forward-only correction from independently verified host UTC yielded840s bounded stability; this is not permanent LAN time provisioning. Before time-sensitive acceptance compare exact UTC/timezone and monotonic progress; never edit client floors or bypass guards. Evidence: logs/device-profiles-integration-20261115/time-diagnosis.json. Do not silently restore the observed unstable synchronization setting.
