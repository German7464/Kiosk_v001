# Android Codex task — BLOCKED draft

Do not launch this task yet. Missing conditions: owner authorization to publish
and merge PC1 preparation into v2, actual completed integration, and verification
of the resulting exact v2 commit. `BASE_V2_COMMIT = PENDING_VERIFIED_MERGE` is an
explicit missing value, not a usable revision. PC1 must replace it before sending.

## Standalone prompt to send after the gate

You are PC2, implementing a bounded Android/Android TV preparation task for
`https://github.com/German7464/Kiosk_v001` in a separate local clone.
Exact agreed v2 base: `PENDING_VERIFIED_MERGE` (STOP if not replaced by PC1 with
a verified40-character commit reachable from the agreed v2).
Contract: `contracts/events-v1/README.md`, documentation edition1,
tuple `(1, events, events-v1, 1)`.

First inspect applicable AGENTS, Git branch/status/index and local/remote refs.
Preserve existing work; do not switch over unfinished changes or reset/stash
another task. Verify the agreed commit exists and branch from that exact commit
as `android/events-conformance-design`. If identity/base/project/conversation
differs or another task is running, stop and report; do not replace it.

Read root AGENTS.md, android/README.md, docs/TWO_PC_WORKFLOW.md, the current
control section of docs/TZ_PROGRESS.md, approved docs/TZ_RECONCILED.md R§3,
R§17.1/R§18/R§22/R§24.2, contracts/README.md and Events contract. Consult
kiosk/publication/README.md, compatibility.py, exporter.py, renderer.py and
renderer_assets only as needed; kiosk/display/README.md describes Windows
boundaries, not an Android implementation.

Scope: produce an Android implementation design and conformance test plan in
android/README.md. Inventory available Android Studio/SDK/JDK and physical
Android/TV devices without changing system settings; propose justified platform
and tooling versions with official-source verification, distinguishing available
from proposed. Explain offline package verification/storage/atomic activation,
controlled local origin, lifecycle/readiness, security, TV focus and reuse of
existing Events HTML/CSS/JS. No full app or platform choice is approved by this
task. Do not create a parallel renderer; Python/Jinja is build-time, not Android
runtime. Identify the smallest next implementation slice for owner/PC1 review.

Allowed edits: android/README.md and optional design/test-plan files under
android/. Do not edit contracts, shared renderer, server/Windows, root AGENTS,
requirements, common ledger or dependency declarations. Do not implement D13,
network transport, server, replication, updates, signing or lockdown. Do not
start a full Android project, install tools or change security/remote access.

If existing Python dependencies are available, run from repo root:
`python -m contracts.events_examples --output logs/pc2-contract-examples-UNIQUE`.
Compare all9 cases with expected.json, including safe errors and unchanged
trusted content on proposed activation failure. If unavailable, report the
missing dependency; do not claim execution. Use generated kiosk/TV views as
shared-renderer reference artifacts. A browser/emulator cannot establish physical
Android/TV acceptance. For this docs task check links/diff; no unrelated source
regression or speculative application build is required.

Return a concise report in Russian: exact base/branch/head, changed files,
available versus proposed tools/device identities (no secrets), commands and
PASS/FAIL/SKIPPED with evidence paths, design decisions requiring approval,
pending hardware/security/storage gates and smallest next task. Update Android
README only; PC1 reviews results and maintains the single ledger. No push,
merge, GitHub changes or stage acceptance; leave changes reviewable and report
whether committed (do not commit without separate authorization).
