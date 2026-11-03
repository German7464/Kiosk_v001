# Bounded Windows long-content measurement

PC1-only follow-up to the accepted native display foundation; this procedure does
not change the shared renderer or contract while PC2 works from its fixed base.
Status/evidence belongs only in [TZ_PROGRESS.md](TZ_PROGRESS.md).

Use disposable synthetic Events packages verified by the existing validator and
views built by the existing client renderer. Retain the candidate EXE/source,
runtime/OS identity, package/view hashes, viewport/device-pixel ratio, observed
mode and active revision with each result. Never use working event data.

| Fixture | Measurement |
| --- | --- |
| Empty events | Placeholder, disabled navigation, no unexpected scroll/crash |
| Short control | Readable card, local image, reachable footer; TV counter advances |
| Long title/place | Long word and Unicode wrapping; horizontal overflow and footer reachability |
| Long description | Multiline content/vertical extent, actual visible content and any clipping |
| Many tags | Tag wrapping, focus/navigation and card/controls remaining reachable |

Exercise kiosk and TV separately at landscape and portrait-shaped window sizes;
record actual content/client viewport dimensions. Window aspect simulation is
not physical portrait or touch acceptance. Confirm shared renderer readiness and
unchanged public package identity before/after each resize. If a preparation
failure occurs, preserve the previously ready view; do not clear the cache to
manufacture a pass.

Measure DOM scrollWidth/clientWidth and scrollHeight/clientHeight for document,
card and controls through a separate native test host using the production
PreparedView policy, not a new product bridge. Pair measurements with visual
inspection on the Windows VM, counter progression and keyboard navigation.
Overflow alone does not establish unreadability: record what is clipped and
whether a user can reach it. A TV rotation timeout is not proof that long text
was visible long enough to read. Record failures without silently adding text
truncation, auto-scroll or a new layout policy. Coordinate any shared asset fix
with PC2 before editing.

Use bounded owned processes/profiles, unique fixture directories, and remove only
owned launch shortcuts/processes. Keep fixtures/evidence under ignored logs.
No OS settings, firewall, installed service, credentials or working data changes
are needed for these measurements. Continuous profile retention/capacity and
physical portrait/touch remain separate checks; this document claims no pass.
