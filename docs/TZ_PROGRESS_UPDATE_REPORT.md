# Complete Kiosk documentation integration report

Date: **2026-10-27**. This report replaces earlier packaging reports. Scope: the supplied 11 existing docs files, root README/AGENTS context and the previously approved corrected specification bundle. No repository file, product code, dependency, running service, live data, trust store, account or network setting was modified. Outputs are staged for owner transfer.

## Authority and file layout

Root [AGENTS](../AGENTS.md) and [README](../README.md); full documentation under docs, mapped by the [index](README.md). Primary requirements: owner-approved [TZ_RECONCILED.md](TZ_RECONCILED.md), revision **1.2.1**. Single current status ledger: [TZ_PROGRESS.md](TZ_PROGRESS.md). Supporting procedures/audits do not override requirements or convert dated evidence into current acceptance. No obsolete target plans or active CHAT_HANDOFF are needed.

## File integration

| File | Targeted treatment |
| --- | --- |
| Root AGENTS.md | Kept the previously approved corrected version; added documentation map/lab boundaries and explicit owner-request-only push rule. No workflow rewrite |
| Root README.md | Updated specification, stage-map, recovery and index links; clarified dated status; existing startup/build/dependency commands retained |
| docs/TZ_RECONCILED.md | Approved revision 1.2.1 retained, including 27 sections/32 decisions; no further product requirements invented |
| docs/TZ_PROGRESS.md | Current index links updated, original 190732-byte ledger retained exactly; stage 3 remains incomplete |
| docs/PROJECT_AUDIT.md | Copied unchanged; source snapshot, not live acceptance |
| docs/TZ_TECHNICAL_AUDIT.md | Previously corrected integration status retained; historical review conclusions remain dated |
| docs/ARCHITECTURE.md | Updated target-spec link and selective isolation wording; retained implementation structure and baseline/target distinction |
| docs/LAN_TRANSPORT.md | Kept technical procedures and code blocks; linked current sources and corrected unqualified old stage-incomplete wording into dated history |
| docs/MVP_BASELINE.md | Kept measurements/tables; updated current links and historical stage wording |
| docs/MVP_SCOPE.md | Retained original lists, explicitly scoped as historical MVP boundaries rather than v2 exclusions |
| docs/CHANGELOG.md | Added one documentation-integration entry; every prior byte remains after removing that insertion |
| docs/DEVELOPMENT_RECOVERY.md | Retained useful restore/runtime/run-check sections from V2_PLAN; clarified snapshot existence is unverified and actions require current scope |
| docs/LAB_CONTEXT.md | Preserved complete 70570-byte historical handoff behind a non-authoritative dated boundary; not live permissions/next steps |
| docs/README.md | Added one index mapping all roles and current/historical precedence |
| docs/DOCUMENTATION_GUIDE.md | Exact transfer/replacement/removal map for all 11 supplied old docs; no automatic deletion |
| docs/TZ_PROGRESS_UPDATE_REPORT.md | This report; not a second stage ledger |

## Preservation and logical checks

- Original progress ledger SHA-256: `6c4c4ba4e49f079cd1f04dec4842ccebfe8da03e5f280499d5126b4902ce5e0a`. Actual output suffix compared byte-for-byte.
- Implementation audit SHA-256: `faf65ba421055a6c0ef68fb9eee03fb06b4e3d5b60f10421ac773141591fa994`; unchanged from supplied repository document.
- Complete lab handoff preserved byte-for-byte after the new boundary. No old lab instruction/authorization is made current by preserving it.
- Prior changelog content unchanged after removing the one inserted entry; measured baseline table rows unchanged. LAN/baseline fenced command blocks retained exactly.
- Specification has sections 1–27 and 32 decisions. Current ledger retains 32 DEC entries, 15 A findings, 13 D open questions and 14 acceptance work packages. Source/package/installed/physical acceptance remain separate.
- Owner approval of requirements is explicit and consistent. Stage 2 acceptance remains bounded; stage 3 incomplete; A01 not marked fixed; no automatic start of stage 4. Historical all-green 201-test run remains distinct from later failed full audit and successful targeted rerun.

## Link and structure verification

PASS: 79 active package links and 9 links to existing repository files checked, including referenced headings; no unresolved active local links. 7 external links classified without network verification.

Active local document links and heading fragments are checked within this staged package. Relative links to existing feature READMEs/source files are checked against the actual supplied repository; those files are not copied or replaced. External URLs are retained and classified but not fetched. No website availability claim is made.

Historical links in the unchanged implementation audit, embedded original progress ledger and preserved lab handoff are provenance. Some point to intentionally retired source documents; they are excluded from current-navigation validation and do not require restoring obsolete files. They were not silently redirected to a different specification. Full Markdown render appearance was not visually inspected.

Strict UTF-8 and balanced fenced blocks checked. Final archive is checked for exact membership and decompressed hashes against output files. No runtime tests, command execution from document examples, builds, browser/device checks, source-behavior audit, deployment or Git mutation was performed. Linked module documentation is checked for existence/fragments, not comprehensively re-audited against code. Newer unseen repository edits/evidence require comparison before replacing documents.

## Supplied repository input hashes

| Source | SHA-256 |
| --- | --- |
| docs/ARCHITECTURE.md | `a5cb9cf744cf30e3059f63893edda66364524c83de171a2c5f94f8f1a375ec48` |
| docs/CHANGELOG.md | `401b14c71082c88597467e11f28181a24ef6355eb5ff469328c69492ca9d026c` |
| docs/CHAT_HANDOFF.md | `7548277d3b6271ab57bb468e87f3d95ede15dc614e1efdc35e3d95feae0496b4` |
| docs/LAN_TRANSPORT.md | `9a433885c5b0803ce5ec1b6401d56c4abe480e630843f98c5bf258547078b7e4` |
| docs/MVP_BASELINE.md | `9f70f6d1de1f6e7e6aac925d63739592ead7e01e88841946ebb7a6111af34277` |
| docs/MVP_SCOPE.md | `28197d5e2eca0627e3cb4b1c3dfade7d43c6121788dc572cc0c12d1c2d0a0b52` |
| docs/PROJECT_AUDIT.md | `faf65ba421055a6c0ef68fb9eee03fb06b4e3d5b60f10421ac773141591fa994` |
| docs/TZ_PROGRESS.md | `6c4c4ba4e49f079cd1f04dec4842ccebfe8da03e5f280499d5126b4902ce5e0a` |
| docs/TZ.md | `6f3d7204f3c1dd76a8febb937bcd4118cf7866ff593597ac528f219124144eaa` |
| docs/V2_PLAN.md | `e9606e6f5eb217472f946657fe2b4f7176c0e204b6afeeefa8135ad6f2b00824` |
| docs/V2_REQUIREMENTS.md | `d9824292b5d7331f55375db36ab899481d70c63e3312f20e7e36cd681f656e77` |
| README.md | `d80053c97ef0f86978330920e40ee4cf2633f25c34f576039b0f812ce2ea2111` |
| AGENTS.md | `46fcff839591710f2df11d740fa411542b87681d54ca389bc7c052ae2ab007ae` |

## Owner transfer

Follow [DOCUMENTATION_GUIDE.md](DOCUMENTATION_GUIDE.md). The owner has saved old documentation outside the project; preserve any newer edits as well. Copy root files and complete docs contents; remove only the explicitly superseded old active documents. Feature READMEs/code/runtime assets remain in place. Review and record the integration as a documentation-only change. Reverting that documentation change restores the previous state; no runtime rollback is implied.
