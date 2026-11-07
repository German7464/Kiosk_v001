# Core documentation audit — 2026-11-05

Dated coordinator review, not requirements, a second progress ledger or a new implementation dispatch. The owner narrowed the audit to the documents needed to understand the product and its execution. Current outcome/acceptance stays in [the sole ledger](TZ_PROGRESS.md).

## Scope and understanding

Read the complete approved specification (sections1–27 and appendices), current ledger control/evidence/remainder sections, documentation index, root README, architecture, execution and two-PC rules. Consulted Events/delivery contracts and targeted publication/display/delivery/Android module documentation. Archived audits and the entire historical ledger were not reread; this is not an exhaustive source or deployed-system audit.

The product is one LAN/offline-capable Kiosk system with platform builds for Windows10 and Android. Windows uses the existing Flask/SQLite server engine for independent local installation or network server; Android is a display/online-administration client, never a server or independent offline editor. Prepared clients keep a fully verified assigned publication and local navigation/TV pagination across network loss and restart. Hashes establish byte integrity; trusted enrollment/publisher authority is separate.

The complete target also includes shared pages/datasets/block instances, TV/kiosk and orientation layouts, profiles, two product roles, concurrent shared drafts with pinned readiness dependencies, and explicit coherent publication. The current Events snapshot/delivery work does not implement that stage6 authoring model. Backup, signed updates, fenced replication, independent recovery and release/fleet qualification remain their assigned later-stage obligations, not features implied by the prototype. Automatic leader election is optional future scope.

## Findings and disposition

| Finding | Disposition |
| --- | --- |
| Root README still used specification1.2.1, described stage3 as in progress and pending Edge acceptance | Corrected to1.2.2 and the current ledger/profile boundary; Edge excluded, release readiness not claimed |
| Architecture called persistent client snapshots entirely future work and omitted three existing modules | Documented publication/display/opt-in delivery and their limits; Android checkout ownership explicit |
| Current ledger resume/operator review followed long superseded queues | Moved existing current blocks to the front without deleting evidence; older requirement/decision status maps explicitly identified as reconciliation-baseline snapshots |
| Execution roadmap's70%-used stopping instruction contradicted root context rules | Replaced with root AGENTS handoff/compaction policy; no invented telemetry |
| Operator task attributed frozen targets to R12.1 and could imply complete distribution coverage | Corrected traceability to R9.3/R9.4; R12.1 is durability, ready/outstanding is partial R9.4, not full stage5 acceptance |
| Practical task could reuse a frozen evidence DB or implicitly require new TLS material | Required new disposable fixture/copy; frozen evidence retained, no TLS bypass, new working keys/trust or system changes |
| Approved specification footer names1.2.1 while its header/changelog identifies1.2.2 | Recorded editorial inconsistency only; approved specification text and requirements not changed |
| PC1 android/README is still preparation-only despite reviewed PC2 implementation | Not evidence of absent Android implementation; do not overwrite PC2-owned Android files or integrate dirty branches by assumption |
| Some module README paragraphs still say Android/resume/restart pending despite later evidence | Recorded for owning executors' next documentation reconciliation; no source check is reopened and no module file concurrently edited by coordinator |
| Missing TZ.md and CHAT_HANDOFF.md links in preserved ledger history | Historical provenance, not current required inputs; no superseded document recreated |

## Execution and remaining limits

Coordinator owns common documents/contracts, dispatch and acceptance; PC1 executor owns server/Windows source and focused checks; PC2 owns android/ and returns evidence. The owner relays prompts manually. Shared contract changes precede dependent implementation. Existing current task needs no Android wire change, so no artificial parallel Android task is issued.

The pending PC1 prompt is limited to the already required practical Windows Chrome operator journey, not reimplementation or repeated25+3 tests. Windows MCP ControlStatus previously responded in this coordinator session; that alone does not prove GUI control or Chrome availability in another executor. A synthetic-ready report proves accounting, not native rendering or physical screen power. Actual tool/TLS blockers remain pending rather than being replaced by API evidence. Current stages/build identities and physical scope remain exclusively in the ledger.

Validation: local Markdown file-link scan, changed-anchor navigation, focused diff and git diff --check. Historical missing links are identified above. No source tests/builds, new HTTP/browser/device checks, PC2 changes, deployment or Git writes performed by this audit. Initial published checkpoint remains3b90c08a722e364ede0b17770ad6bcf6bbb9d8a1; subsequent source/documentation changes remain uncommitted.
