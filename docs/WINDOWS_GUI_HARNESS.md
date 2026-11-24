# Windows VM GUI harness

Use the installed harness on the assigned lab VM for real GUI evidence. It uses UI Automation for native windows, Playwright over loopback CDP for Chrome and WebView2, and a Win32 fallback for supported native controls. See the [lab boundaries](TEST_LAB_POLICY.md).

## Setup and checks

1. Confirm the assigned VM identity, strict SSH host key, required interactive console and matching test application. Find the installation and local machine values in the private lab inventory.
2. If the harness is missing, use the existing offline GUI payload within the lab authorization. Run its installer and selfcheck. A session-zero selfcheck verifies installation only.
3. Before a native journey, run the UIA smoke check in the interactive console. For a browser journey, use Chrome with a disposable profile and a loopback DevTools endpoint where the guest policy permits it. For WebView2, use the harness's supported CDP attachment. Keep certificate verification enabled.
4. Use the existing scripts for the actual scenario. Record application identity, guest/session, observed action and result, and the evidence location. Keep secrets in the existing local secret mechanism. Stop only task-owned processes and clean their temporary profiles within the assignment.

## Known limits and evidence

- CDP can be blocked by the guest's browser debugging policy. Check the policy and use the appropriate assigned platform. An available CDP connection alone is not a passing product journey.
- UIA may need the harness's native fallback for controls without a UIA pattern. SSH session zero is not interactive display evidence.
- Validate UTC and certificate windows before time-sensitive work. The November guest clock correction established bounded stability only.
- Historical records remain in the local qualification evidence and the [ledger](TZ_PROGRESS.md). The installed guide supplies machine-local examples. The project lab policy governs current authorization.
