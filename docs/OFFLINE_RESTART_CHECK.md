# Controlled Windows offline restart check

This is a stage4 test procedure, not a deployment or autologin policy. Requirements: R§10.5/R§11/R§22 of `TZ_RECONCILED.md`. Record actual results and authorization only in `TZ_PROGRESS.md`. A prepared procedure is not acceptance evidence.

## Boundary and prerequisites

Use the persistent Windows test VM and public-only disposable fixture. The owner's 2026-10-30 authorization recorded in `TZ_PROGRESS.md` covers necessary VM testing, OS changes and restarts; no repeated permission is required for this procedure. Notify the owner before restarting and request reconnection if needed. Preserve its clone, working services/data, credentials, trust configuration and remote recovery. This procedure does not require disabling adapters, stopping RustDesk/SSH, enabling autologin or force-closing unrelated applications. If sign-in is required and no authorized interactive sign-in is available, record that gate; do not retrieve saved passwords.

Before changing anything, record OS build/boot time, enabled Firewall profiles, running `MpsSvc`, active network profiles, exact shell/runtime paths and hashes, current publication/cache/receipt identities and absence of owned fixture processes. Confirm the fixture shell matches its build inventory and the runtime is already installed. Refuse to reuse an existing test-rule name. Refuse network isolation when any applicable Firewall profile is disabled, local rules are disallowed, the active policy cannot be inspected, or runtime path/version changes during the check.

The fixture runner that waits for version-switch steps must not be restarted as a reboot test: it intentionally mutates publications. Use a separate bounded runner opening the existing verified store/cache with a fresh launch token, retaining the confirmed receipt. Its lifetime must be bounded and it must stop only its owned native process. A direct shell run can establish native view restart only; do not substitute it for coordinator/store recovery.

## Isolation and recovery

Create exactly two uniquely named outbound Block rules, one for the absolute fixture shell executable and one for its exact installed `msedgewebview2.exe`, all profiles, protocols, remote addresses and ports. Do not block the entire runtime directory, a generic executable name, PowerShell, RustDesk or SSH. Record rule names and full filters in a local evidence file before reboot. Confirm both rules in `ActiveStore`, including enabled/direction/action/profile, program, address and port filters, and that no matching runtime is already running.

These rules isolate the display processes from server and Internet; the VM network remains available for recovery. This is **program-scoped offline operation**, not a disconnected adapter or power-loss test. The runtime executable can serve other WebView2 applications: inspect interactive applications first and defer if an unrelated application depends on this runtime. Do not install another runtime or alter servicing policy for this test.

Rollback removes only these two exact rule names. Keep their names and removal commands accessible over SSH and in the evidence directory. A host-side `finally` must attempt removal on failure, timeout, cancellation and success; if reconnection fails, report the residual rule names as a recovery action rather than claiming cleanup. Persistent blocks affect only the two specified programs and must not be left as product configuration. Do not remove a preexisting rule or reset Firewall.

## Execution and evidence

1. Record pre-restart publication pointer, confirmed receipt and hashes; keep the prior successful evidence intact. Confirm SSH recovery, then apply and verify the scoped isolation above. Run the bounded coordinator fixture once before restarting to distinguish an isolation failure from a reboot failure. Close it and confirm owned processes are zero.
2. Perform one ordinary Windows restart without `Force`. Do not change startup, sign-in or service settings. Reconnect over strict-host-verified SSH with bounded retries and record a changed OS boot time. If normal restart is blocked by an application or update, record the blocker; do not force it.
3. Recheck runtime identity, `MpsSvc`, applicable Firewall profiles and both effective rules after reboot. Complete authorized Windows sign-in if required, then start the fixture in the interactive user session, not SSH session0. No package transfer, server fetch or publication regeneration is allowed between reboot and this launch.
4. Record fresh PID/session, verified package/cache identities, navigation and renderer readiness, and last-confirmed receipt. Observe the expected Events text/image through RustDesk/Windows MCP. For TV use a valid two-card fixture and bounded numeric diagnostics to establish rotation. Record actual elapsed/sample counts without inventing endurance coverage. Verify no partial or deliberately broken revision was selected.
5. Close the fixture normally, confirm owned processes are zero and publication identity remains unchanged. Remove only the test rules and verify absence in both persistent and active policy stores. Reconfirm SSH/RustDesk availability and record residual processes/artifacts. Retain public fixture/evidence; do not restore the VM clone.

Pass requires reboot evidence, effective process isolation before/after reboot, verified retained publication/coordinator startup, observed native output, and successful cleanup. Missing sign-in, policy enforcement, runtime identity or display evidence leaves that check pending. This does not establish D12 autostart/lockdown, disconnected adapter behavior, sudden power loss, installed-package servicing, Android, real touch/portrait or full stage4 acceptance.
