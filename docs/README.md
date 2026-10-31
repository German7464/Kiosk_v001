# Kiosk documentation index

Primary requirements: **owner-approved TZ_RECONCILED.md revision 1.2.2 (owner decisions through 2026-10-28)**. One current status/check ledger: **[TZ_PROGRESS.md](TZ_PROGRESS.md)**, including stage acceptance and the current owner-selected execution boundary. Specification approval alone does not grant acceptance or select an implementation stage.

## Current working documents

Two-PC entry points: [coordination workflow](TWO_PC_WORKFLOW.md),
[shared Events contract and examples](../contracts/README.md),
[Android workspace](../android/README.md), [blocked Android task draft](ANDROID_TASK_DRAFT.md).

Client implementation modules: [publication export/store/renderer](../kiosk/publication/README.md) and [native display candidate](../kiosk/display/README.md). These describe implemented interfaces and limits; current acceptance/evidence remains in the progress ledger.

| Document | Role / when to read |
| --- | --- |
| [Root AGENTS](../AGENTS.md) | Workflow, scope, permissions and test/report rules |
| [Root README](../README.md) | Existing startup, dependencies, packaging and operator entry points |
| [Approved specification](TZ_RECONCILED.md) | Target requirements, 32 decisions, stage allocation and unresolved technical gates |
| [Progress ledger](TZ_PROGRESS.md) | Current factual status, target traceability, stage-3 checks and preserved acceptance history |
| [Execution roadmap](EXECUTION_PLAN.md) | Approved checkpoint sequence, dependencies and tests; not a progress ledger or permission to start future stages |
| [Architecture](ARCHITECTURE.md) | Implemented baseline and code organization; not proof of the future architecture |
| [LAN transport](LAN_TRANSPORT.md) | Existing source/Windows HTTPS, CA/CSR custody, renewal and dated fixtures |
| [Development recovery](DEVELOPMENT_RECOVERY.md) | MVP inspection, isolated restoration precautions and verification commands |
| [Changelog](CHANGELOG.md) | Append-only history of meaningful changes; not another live stage queue |

## Supporting evidence and historical boundaries

| Document | Role / limit |
| --- | --- |
| [MVP scope](MVP_SCOPE.md) | Historical compatibility boundary; its exclusions do not cancel v2 requirements |
| [MVP measurements](MVP_BASELINE.md) | Retained workload/results; not UI, Android, 100-device or 72-hour acceptance |
| [Implementation audit](PROJECT_AUDIT.md) | Unchanged technical snapshot dated 2026-10-26; not a current device check |
| [Specification technical audit](TZ_TECHNICAL_AUDIT.md) | Reconciliation rationale and findings, read with its current integration clarification |
| [Lab context](LAB_CONTEXT.md) | Preserved handoff history; no live-state, instruction or permission authority |
| [Integration report](TZ_PROGRESS_UPDATE_REPORT.md) | Changed files, preservation/links verification and limits |
| [Owner transfer guide](DOCUMENTATION_GUIDE.md) | Exact package layout, replacement/removal map and first Codex task |

For each task, start with AGENTS, current progress and only the relevant requirement/dependency paragraphs. Consult supporting documents when needed, not by rereading every historical document. In a discrepancy, use the owner's current scope and approved specification for requirements; retain observed failures/evidence in the ledger rather than rewriting them as successes. Architecture/audits/old notes cannot silently amend requirements.

Feature READMEs remain beside the existing code; this bundle does not replace them: [Launcher](../kiosk/launcher/README.md), [transport](../kiosk/transport/README.md), [administration](../kiosk/features/admin/README.md), and [public API](../kiosk/features/api/README.md). Current stage-gate links point to the current control section of the ledger. Local paths, linked headings and navigation reachability were checked on 2026-10-28; runtime commands and full source/behavioral consistency were not revalidated.

Historical source-document names in dated audits and preserved history are provenance only. Missing superseded specifications/plans are not required reading. Do not follow obsolete next-task or permission wording from historical blocks.
