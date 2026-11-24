# Kiosk development progress

## Current checkpoint

As of 2026-11-24, ChatGPT Work accepted Stage 5 within the recorded scope. The final matrix contains **37 PASS, 0 FAIL, 0 BLOCKED**. [Dated evidence](#dated-evidence) identifies the matrix and teardown report. Cleanup was verified. Retained data, rollback copies and the original Android application were preserved. Qualification used the recorded working sources and artifacts based on `work/windows-layout-checks` at `72d22ed`.

Stage 6 has not started and requires a separate owner assignment. The selected manual Windows offline update/build slice has its own bounded acceptance. Full Stage 7 and Stages 8–10 remain unselected. Release, production rollout, 100 live clients and the 72-hour run remain outside the accepted scope.

The notebook is the active checkout. See [workstation roles](TWO_PC_WORKFLOW.md#ownership-and-working-copy) and the [verified source checkpoint](DEVELOPMENT_RECOVERY.md#unified-source-checkpoint---2026-11-24). Source checkpoints and documentation reviews do not rerun tests or change stage acceptance.

## Dated evidence

Evidence paths below are relative to the original notebook or retained evidence root. The local reports may be unavailable in a Git-only checkout.

| Date | Evidence | Scope |
| --- | --- | --- |
| 2026-11-24 | Notebook `logs/stage5-final-20261121/README.md`, final 37-row qualification matrix, and `logs/stage5-final-20261121/coverage-review/r-stage5-final-cleanup-verified.json` | Formal acceptance within recorded Windows, Chrome and physical Android bounds. Reused cases retain their original source, artifact and environment limits. |
| 2026-11-19 | Notebook `logs/notebook-migration-20261119/report.md` and `essential-manifest.json` in the same directory | Notebook source and development environment migration. PC1 retained as fallback. |
| 2026-11-15 | Retained `logs/device-profiles-integration-20261115/{report.md,results.json,windows-physical-correlation.json}` | Display-profile-v1. Native Windows and physical Android TV/Kiosk ready and offline reopen within the recorded profiles. |
| 2026-11-13 | Retained updater evidence and original ledger, section “Windows offline updater accepted”, indexed by date | TEST-key VM slice, server/client 3.0.16 to 3.0.17. Client button and folder selection observed. Server button was outside the observed journey. |

For earlier environment identities, accepted subcases, earlier failures and qualified versions, use the [archive index](archive/README.md#acceptance-and-owner-decisions) only if the dated evidence leaves a specific question unresolved.
