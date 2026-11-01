# Android offline Events harness and conformance design

## Full candidate: independent-copy integration review (2026-11-01)

The accumulated **experimental Android development harness** has now been rebuilt
and exercised from a fresh copy of the agreed base plus **only 449 delivery
files**. This supersedes historical inventory counts below; it does not change
stage status or grant production admission. No feature/source changes were needed
for this review. Only this README was updated; all previous work/index was retained.

Delivery scope: 447 new files under `android/`, plus modified `android/README.md`
and `docs/CHANGELOG.md`. Exact relative paths, byte sizes and SHA256 are in the
[449-file inventory](../logs/pc2-integration-20261101-143109/inventory.json) and
[future commit list](../logs/pc2-integration-20261101-143109/future-commit-files.txt).
These are review artifacts, not build prerequisites. The deliverables consist of
10 Gradle/Wrapper/config files, 110 main code/assets, 165 instrumentation code/assets,
6 shared test helpers, 6 JVM test files, 139 synthetic testdata/provenance/oracle
files, 7 developer tools, 4 separate visualtest files and 2 documentation files.
No build/cache/logs, local.properties, local SDK, signing keys or credentials are
in that list. The standard disposable `android` debug key password in build.ps1
is not a product secret; the generated key stays ignored.

### Reproduce without historical logs or the original checkout

1. Use base `5d652d4d99a577e8809a87839800a9f24c6250fa`, overlay only the
   listed delivery files at their relative paths, and verify every inventory hash.
   The review used `git archive` of the base followed by file copies, with no Git
   index or branch in the fresh tree. Before toolchain seeding it contained no
   logs, Gradle state, builds, local.properties or signing key. No file from the
   original ignored evidence directories was supplied as a build/test input.
2. Supply an already installed SDK (platform35, BuildTools36.0.0), measured full
   build JDK, Gradle9.6.0 Wrapper distribution and compatible dependency caches.
   This run reused JBR25.0.3 and Java17 bytecode with AGP9.4.1; it is experimental
   build evidence, not JDK17 equivalence or product support. No tool was installed.
   For a fully offline run, preseed the **existing installed** Wrapper distribution
   into the new project's `.gradle/user-home/wrapper/dists`; `--offline` does not
   itself prevent a missing Wrapper distribution from bootstrapping a download.
3. Dependency cache is an external build prerequisite, not source data. The user
   cache alone initially lacked kotlin-reflect2.2.10: the first offline configure
   failed as expected. Seeding the existing supplemental `caches/modules-2` from
   a compatible Gradle9.6.0 build resolved it (about3.45MiB, not old build outputs).
   Copy dependency metadata/artifacts with relative paths, excluding locks and
   `gc.properties`; never copy project outputs or signing keys. The measured
   initial supplemental transfer included one harmless zero-byte gc.properties;
   it is not required. [Gradle cache documentation](https://docs.gradle.org/current/userguide/dependency_caching.html#sec:cache-copy)
   describes cache relocation and offline failure for missing artifacts. A shared
   read-only cache must not have concurrent writers. No remote dependency fetch
   or global Gradle/Java setting was used.
4. From any cwd, run the helper from the fresh tree, using explicit external paths:

```powershell
# Supply these existing paths locally; none is stored in local.properties.
$Fresh = '<fresh base-plus-deliverables tree>'
$BuildJdk = '<existing measured full build JDK>'
$AndroidSdk = '<existing Android SDK>'
$Cache = '<existing read-only compatible dependency cache>'
& "$Fresh/android/tools/build.ps1" -BuildJdk $BuildJdk -AndroidSdk $AndroidSdk -ReadOnlyDependencyCache $Cache -Tasks ':app:testDebugUnitTest',':app:assembleDebug',':app:assembleDebugAndroidTest','--offline'
```

The helper creates a new disposable project-local debug key if absent. Do not
copy another app's key or expect an independently generated key to update an
already installed differently signed package. This run used a clean owned
read-only Medium_Phone session; its package inventory was empty before install.
No uninstall/clear/settings change was needed.

5. On a verified owned AVD/serial, install **the fresh tree's** two APKs and run
   only the two external methods, in order (do not class-scan inherited drivers):

```powershell
$Adb = "$AndroidSdk/platform-tools/adb.exe"
$Serial = '<verified owned serial>'
& $Adb -s $Serial emu avd name
& $Adb -s $Serial install -r "$Fresh/android/app/build/outputs/apk/debug/app-debug.apk"
& $Adb -s $Serial install -r "$Fresh/android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"
& $Adb -s $Serial shell am instrument -w -r -e class 'org.kiosk.harness.LocalAdmissionDriverTest#testSeedConfirmedC' org.kiosk.harness.debug.test/org.kiosk.harness.HarnessTestRunner
& $Adb -s $Serial shell am instrument -w -r -e class 'org.kiosk.harness.LocalAdmissionDriverTest#testReplaceConfirmedB' org.kiosk.harness.debug.test/org.kiosk.harness.HarnessTestRunner
& $Adb -s $Serial shell am start -W -n org.kiosk.harness.debug/org.kiosk.harness.StoredHarnessActivity
```

Require instrumentation `OK (1 test)` for each method, not just ADB exit0. The
methods confirm exact PC1 preparation digests, capture with providers disabled,
hand off to the existing store/coordinator, assert real C kiosk navigation/TV
rotation, then B replacement and both mode receipts. Test inputs are vendored;
fixed confirmations are in sharedTest/test APK only.

6. Observe restart externally. Record PID/session and the ready private state via
   `adb exec-out run-as org.kiosk.harness.debug cat files/fixture-publications/display-state.json`.
   This diagnostic is advisory, not sole proof of visible DOM. Execute
   `adb -s <owned serial> shell am force-stop org.kiosk.harness.debug`, require PID
   absence over a bounded6s observation, then explicitly start the same Activity.
   Poll at most28s for the new PID/session, `ready`, expected B/mode/receipts,
   private_reads>0 and asset/package-asset reads0. Compare private revision,
   authority and pointer/receipt hashes before/after; exercise visible Next and TV
   rotation, capture/view screenshots. The external bounded observer and full argv,
   exit codes and timestamps are preserved in the integration evidence bundle.
   Do not treat instrumentation killed with the process as restart evidence.
7. Finish only owned test activity/emulator after checking serial, launcher/QEMU
   PID, parent, executable and AVD/read-only/no-snapshot arguments. Do not stop
   ADB server or unrelated applications, change settings or save a snapshot.

### Actual independent-copy result and isolation

Fresh build: **PASS**, all67 tasks executed, **47/47 JVM** tests across six suites.
Confirmed C/B external methods: **PASS2/2**, plus force-stop/private startup,
post-start native Next and automatic TV transition. PID4520 became5051; sessions
changed,6s had no process/self-start; fresh startup recorded116 private reads,
zero asset/package-asset reads and unchanged revision/authority/metadata hashes.
Screenshots were actually viewed. Target: owned Medium_Phone Android17/API37
x86_64, WebView145.0.7632.218. Final guarded cleanup left an empty ADB inventory.
No reboot or unchanged image/visual/runtime regression suite was repeated.

Fresh main APK SHA256:
`331bb06d96b725858089ece69765dfc46a2934e9b88038cebeed1befc5cc393d`.
Fresh test APK SHA256:
`ed61abad967426faf4acfafc9361cd8134e9a72d97fb6db8936f473c5ad7376f`.
Installed bytes matched these hashes. Whole signed APK byte reproducibility is
**not** claimed: the fresh key differs and incremental DEX numbering changes.
After mapping shards, all6 test DEX and7/8 main DEX are byte-identical to the
prior build; the remaining main DEX differs only in header checksums and one
embedded synthetic checksum metadata string (code bytes unchanged). All non-DEX,
non-signature payload entries, including manifest/resources/renderer assets, match.

Main has no INTERNET permission, preparation parser, test confirmations, test
runner, local-admission/parity inputs or VisualHostActivity. `:visualtest` is a
separate executable module, never an app dependency. Main retains experimental
native seams, exported harness Activities, A/B fixture controls and the explicit
unverified development permit API; it is **not a production/release app**.
Actual debugRuntimeClasspath is Kotlin stdlib2.2.10 plus annotations13.0 (AGP's
built-in Kotlin configuration); JVM-only dependencies are JUnit4.13.2,
Hamcrest1.3 and org.json20240303. No new dependency was added. There is no complete
product dependency lock/verification policy; the measured cache identities are
review evidence, not supply-chain authentication.

Full [integration report](../logs/pc2-integration-20261101-143109/integration-report.md),
[evidence map](../logs/pc2-integration-20261101-143109/evidence-map.md),
[source/APK identities](../logs/pc2-integration-20261101-143109/apk-identities-isolation.json)
and inventory are separate ignored review artifacts. Historical helper scripts
that compare original PC1 archives require those optional logs; they are not
called by Gradle, JVM tests or this smoke. The image generator reads vendored
sources even though its metadata retains a historical logs label. No shared
renderer/contract/Windows/server/ledger changes are in the candidate. Linux/macOS
build/Wrapper executable-bit acceptance was not performed; PC1 should review
`gradlew` mode when staging on its platform (no index edit was made here).

All five broad admission gates, production admission, hostile-source/filesystem
and decoder policy, physical Android/TV and stage4 remain open. Test confirmation
only covers exact pinned preparations; it is not a new production protocol,
authentication or authorization for future packages. Next action is PC1 integration
review and a separate owner decision on commit/publication; no new functionality
was selected or started.

## Pinned Windows preparation: local TEST admission experiment ? 2026-11-01

This is an owner-authorized **test-only confirmation** of two exact PC1
preparations, followed by the existing development playback path. It is not
production authorization, source authentication, or a new Events/view protocol.
The five broad packagecore admission gates remain open. The development permit
continues to mean explicitly unverified development playback.

[LocalPreparation](app/src/sharedTest/java/org/kiosk/harness/binding/LocalPreparation.java)
exists only in shared JVM/instrumentation test sources. Its native `Confirmation`
constants pin the independently supplied C/B preparation digests. `confirm` owns
and closes its input, reads at most 256 KiB, verifies both the caller digest and
fixed confirmation, then parses the **same bytes**. The returned `Evidence` has a
private constructor; a source self-hash cannot create it. Missing, wrong, foreign
or rewritten confirmations fail before typed expectations or a playback permit
are returned. There is no general admission-success result.

The adapter checks the exact test-envelope shape/scope, integer sizes, hash syntax,
manifest raw pin, package root `store/revisions/<attested canonical identity>`,
distinct `cache/<64hex>` view roots, inventories and shared JS/CSS pins. It resolves
only logical bundled-test entries, never arbitrary filesystem paths/URI. Narrow
test-envelope restrictions are not changes to Windows Events unknown-property
semantics. Canonical identity remains PC1-attested, separate from raw manifest SHA;
matching descriptor.package_sha256 alone is not evidence of HTML derivation.
Existing binding/LocalView recheck full content, mode/package/revision and renderer
expectations; the adapter does not reimplement those algorithms.

Vendored inputs and PC1 metadata are under [local-admission](testdata/local-admission/).
Each C/B `provenance.json` records the independently checked archive/preparation
hashes. Only exact inventory files and evidence are vendored, without PC1 lock or
publication-pointer files. These synthetic preparations contain PC-side verifier,
PublicationStore/cache and renderer evidence supplied by PC1. They are not a local
rerun of Windows verification, a signature or proof of full Pillow pixel loading.
No build/test needs ignored logs or an absolute source fixture path.

The test caller derives independent typed native expectations from confirmed
bytes and invokes the existing capture/store/coordinator. Capture checks actual
saved bytes; providers are emptied before persistence; accepted capture closes
when the coordinator completes. No C identity, parser, confirmation constants or
local-admission assets enter the ordinary APK. Its SHA256 remains
`851321eada7d200a0bc50524d6c93658fdce8a4c70a458dd49a4f66e88ec131d`.
Main source, store format and display/catalog are unchanged.

Focused commands (same explicit JDK/SDK/cache as the build section below):

```powershell
& android/tools/build.ps1 -BuildJdk D:/programThisPc/AndroidStudio/jbr -AndroidSdk C:/Users/admin/AppData/Local/Android/Sdk -ReadOnlyDependencyCache C:/Users/admin/.gradle/caches -Tasks ':app:testDebugUnitTest','--tests','org.kiosk.harness.binding.LocalPreparationTest',':app:assembleDebug',':app:assembleDebugAndroidTest','--offline'
adb -s emulator-5556 shell am instrument -w -r -e class org.kiosk.harness.LocalPreparationAndroidTest,org.kiosk.harness.LocalAdmissionStoreTest,org.kiosk.harness.LocalAdmissionTest org.kiosk.harness.debug.test/org.kiosk.harness.HarnessTestRunner
```

External driver: select **only** `LocalAdmissionDriverTest#testSeedConfirmedC`,
then `#testReplaceConfirmedB`; do not class-scan this external driver (it inherits
isolated tests). It uses the default private store only on the owned disposable
AVD. Regression subclasses reuse existing scenarios, with a test-only input method
override; no production fault surface was added.

Windows evidence is recorded separately from Android capability. The focused
Android decoder test performs bounds and full BitmapFactory decode of the exact
captured upload, opens/closes a fresh verified stream for each pass and recycles
the bitmap. This follows the official [bounds API](https://developer.android.com/reference/android/graphics/BitmapFactory.Options#inJustDecodeBounds)
and [stream decode API](https://developer.android.com/reference/android/graphics/BitmapFactory#decodeStream(java.io.InputStream)).
Actual WebView readiness, natural image availability, local navigation, automatic
TV rotation and viewed screenshots are separate playback observations. None
establishes Pillow/Android/WebView decoder equivalence or production admission.

Results: **4/4 JVM**, **15/15 focused Android** (33.7 s), plus the two
individually selected external driver methods passed. Confirmed C reached actual
kiosk navigation and TV rotation; confirmed B replaced it and produced both mode
receipts. Six seconds after external force-stop had no process/self-start; explicit
private startup changed PID 6404 ? 6758 and session, revalidated private bytes,
reported 116 private reads and zero asset/package-asset reads. Pointer, native
authority, private revision and receipt hashes were unchanged across force-stop.
Post-restart native Next and TV auto-rotation passed. Decode observations for the
exact pinned upload were 4?4 bounds and 4?4 full decode on Android for both inputs;
this is separate from PC1 Pillow 13.0.0/Python 3.14.5 preparation evidence.

Target: owned read-only `Medium_Phone`, Android 17/API37 x86_64,
`com.google.android.webview` 145.0.7632.218. Actual screenshots were viewed and
showed C content/local blue synthetic image, then B card two and TV without kiosk
controls. Screenshots are emulator observations, not color/scale or hardware
acceptance. The `confirmed-C-home` screenshot caught the events card during the
transition despite its filename; home DOM navigation was independently asserted
by the focused journey test. Guarded owned launcher/QEMU cleanup passed; final
ADB inventory is empty. No system settings, VPN or ADB server were changed.

Evidence: [local-admission report](../logs/pc2-local-admission-20261101-141344/report.md),
[checks](../logs/pc2-local-admission-20261101-141344/checks.json),
[external states](../logs/pc2-local-admission-20261101-141344/external-result.json).
The first compile/cache-access failure is retained separately; final checks pass.
Reboot and unchanged 21-vector image/visual suites are intentionally not repeated;
earlier evidence retains its stated limits. Physical Android/TV, production
image/source/identity admission and stage4 acceptance remain open.

## Generic DEVELOPMENT playback integration — 2026-11-01

The generic development path now uses the **existing** `FixturePublicationStore`,
`StoredHarnessActivity`, `PreparedWebView` and recovery state machine. The historical
store class name is retained for source/metadata compatibility; no second store or
coordinator was introduced. Complete C and B publications pass the same native API,
including C outside the catalog. New identities require test/native caller inputs
and witnesses, not a main-code allowlist entry.

### Explicit native authority, not admission

[DevelopmentPlaybackAuthority](app/src/main/java/org/kiosk/harness/storage/DevelopmentPlaybackAuthority.java)
issues a `Permit` only through the explicitly named
`authorizeUnverifiedDevelopmentPlayback(packageWitness, rendererWitness,
kioskWitness, tvWitness)` native opt-in. A binding/structural `Report` alone is not
a permit. This API intentionally accepts the five unresolved admission gates for
**DEVELOPMENT ONLY**; it is not the future production authorization policy. The
native caller must obtain independent expectations, never treat a source-supplied
witness or self-hash as trust. The native UI and private diagnostics identify this
scope and retain `admission_gates_unchecked=5` even after real renderer ready.

`installDevelopment(capture, permit, budget, checkpoint)` copies from the scoped
capture into the existing persistent store under its writer lease. The same
packagecore/binding/LocalView verification checks saved package plus both views
before pointer publication. PC-side common renderer preparation remains unchanged;
package `resources/templates`/JS are never served or executed. Canonical identity
is caller-attested and kept separate from raw-manifest SHA. No approximate canonical
JSON serialization, new Events/view format, URI/directory/ZIP importer or network
path was introduced.

The trusted native permission is durably recorded separately from package sources
as internal app-private `development-authority/<id>.json`. It contains the independent
expected inventories, raw manifest pin, renderer/JS/CSS witness and an accidental
corruption checksum. Only the native permit+successful persistent preflight path
registers it. This is a saved native development decision, not a signature, new
delivery protocol or authentication of content/source. A same-UID/root writer can
replace it; that threat is outside this exclusive app-owned experiment. The record
is bounded to8MiB as internal development metadata, not an Events manifest limit.
Startup resolves authority by explicitly referenced identity; it does not scan a
registry/revision directory or reread input providers/test assets. Missing/corrupt
authority refuses that identity, allowing only the existing bounded recovery paths.

### Ownership, staging and compatibility

Persistent generic revisions contain `package/`, `view/` (TV), `view-kiosk/` and an
owned operation fingerprint. `.development-incoming` is one shared leased staging
slot, mutually excluded with legacy `.incoming`/`.kiosk-incoming` operations.
Copy/hash/flush/sync, directory rename, pointer/backup/mode/receipt atomics and
runtime cleanup reuse existing mechanisms. Caller budgets count both prepared
views, package, native authority and metadata headroom; free-space checks are
advisory. They are per-operation development policy, not product quotas or a global
disk reservation. No revision GC/deletion was added.
The retained staging-tree defense additionally bounds entries to16+4 times the
witness file count and bytes to witness sum+largest file+8192 (one partial-file
allowance). This is a development implementation constraint, not a portable Events
limit: deeper otherwise-valid trees can be safely refused. `maxBytes` here budgets
declared copies/native metadata; it is not an exact filesystem-block/transient-byte
reservation. Broader input/resource policy remains a separate review decision.

The store does not take ownership of the caller's session. The existing coordinator's
native-only `installDevelopment` returns true when it accepts ownership, false when
the caller must retain/close it. Accepted queued work is closed if abandoned;
running work closes capture in its finally/resource scope. The persistent revision
is an independent verified copy, so closing the original capture cannot delete it.
No capture source escapes into persistent LocalView or an active WebView.

Interrupted staging remains bounded and is never selected at startup. Only an
explicit same-witness retry may resume its owned slot or finish its unreferenced
complete revision. Another candidate/legacy install refuses that unfinished slot;
no automatic repair, scan or deletion occurs. Commit failures can leave a complete
unreferenced revision/native grant, but never a partial directory behind the pointer.
Existing active/backup/confirmed data is retained.

Legacy A/B revisions, TV receipt bytes/renderer identities, mode defaults and
external kiosk-cache paths remain readable through their legacy adapter. Generic
paths first resolve the persisted independent native grant, without A/B identity
lookup; the old `PublicationFixtures.Pin` value record is reused only as a pin
container by the existing copy helper. Installing generic bytes over an already
committed legacy layout under the *same* identity refuses a layout conflict rather
than migrating/overwriting it. A different authorized identity can replace it using
the normal pointer mechanism. There is no destructive migration.

Pointer, selected mode, actual visible view and per-mode ready receipts remain
separate. Mode choice commits after private preflight and before the renderer attempt;
receipt commits only after real DOM/visual ready. Receipt failure can leave visible
ready with receipt pending. Renderer failure does not roll back pointer and cannot
guarantee preservation of an old shared-renderer surface. Recovery is bounded to
explicit pointer/backup entries and one distinct same-mode confirmed receipt; no
cross-mode readiness inference, provider repair or restart loop.

### Descriptor ownership correction found during integration

A long affected batch exposed `EMFILE`/native surface abort. Three deterministic
bounded tests proved that the former `PrivateFiles` File*Stream(FileDescriptor)
wrappers left their native descriptors open. The official
[Android input-stream warning](https://developer.android.com/reference/java/io/FileInputStream#FileInputStream(java.io.FileDescriptor))
and [output-stream reference](https://developer.android.com/reference/java/io/FileOutputStream#FileOutputStream(java.io.FileDescriptor))
explain ownership. The helper now duplicates into an owned
[ParcelFileDescriptor](https://developer.android.com/reference/android/os/ParcelFileDescriptor),
closes the original, and uses its AutoClose streams. `O_NOFOLLOW`, regular-file
checking, explicit `CLOEXEC`, sync and safe error normalization are retained. These
platform APIs require no new permission and fit minSdk30. This fixes an observed
resource leak; it is not evidence of hostile-filesystem safety or power-loss durability.

### Verification and reproduction

Same reviewed C inputs plus B vendored under
[generic-playback provenance](testdata/generic-playback/B/provenance.json), derived
from PC1 ZIP SHA256 `7b4fc5f24e71ea0676de33d21eff1d70d27257dbe4283bc9935713b771b942d3`.
B/C package resources and shared JS/CSS are byte-identical. The B renderer label is
an independent native development attestation reusing PC1 C's label, **not** a new
measurement of the Python renderer build; that unproven gate remains explicit.

```powershell
& android/tools/build.ps1 -BuildJdk $BuildJdk -AndroidSdk $AndroidSdk -ReadOnlyDependencyCache $Cache -Tasks ':app:testDebugUnitTest','--tests','org.kiosk.harness.binding.*Test','--tests','org.kiosk.harness.storage.DevelopmentAuthorityTest','--tests','org.kiosk.harness.packagecore.EventsPackageTest',':app:assembleDebug',':app:assembleDebugAndroidTest','--offline'
# Explicit filtered Android classes; external driver methods are separate bounded ADB scenarios.
adb -s VERIFIED_SERIAL shell am instrument -w -r -e class org.kiosk.harness.storage.PrivateFilesOwnershipTest,org.kiosk.harness.GenericStoreTest,org.kiosk.harness.GenericPlaybackTest,org.kiosk.harness.StoreTest,org.kiosk.harness.StoredCoordinatorTest,org.kiosk.harness.EngineTest,org.kiosk.harness.LifecycleTest,org.kiosk.harness.binding.CapturedCandidateAndroidTest,org.kiosk.harness.binding.PublicationBindingAndroidTest,org.kiosk.harness.packagecore.PackageParserTest org.kiosk.harness.debug.test/org.kiosk.harness.HarnessTestRunner
# Separate explicit native test callers for the default private-store external journey:
adb -s VERIFIED_SERIAL shell am instrument -w -r -e class org.kiosk.harness.GenericExternalDriverTest#testSeedGenericC org.kiosk.harness.debug.test/org.kiosk.harness.HarnessTestRunner
adb -s VERIFIED_SERIAL shell am instrument -w -r -e class org.kiosk.harness.GenericExternalDriverTest#testNextGenericBAndTV org.kiosk.harness.debug.test/org.kiosk.harness.HarnessTestRunner
# External host observer verifies PID/ready state before/after these operations:
adb -s VERIFIED_SERIAL shell am force-stop org.kiosk.harness.debug
adb -s VERIFIED_SERIAL shell am start -W -n org.kiosk.harness.debug/org.kiosk.harness.StoredHarnessActivity
# On that SAME owned running AVD only; save boot_id/private hashes first:
adb -s VERIFIED_SERIAL shell reboot
# Bounded wait for changed boot_id +boot_completed; then explicit launch and compare hashes.
```

Evidence: `logs/pc2-generic-playback-20261101-124817/`. Final JVM22/22 and one final
Android78/78 batch PASS (208.760s), including legacy compatibility, generic native
authority/persistence/capture ownership, real kiosk navigation/TV rotation/receipts,
renderer termination, late callbacks, pointer/mode/receipt failures, interrupted
staging/resume, cancellation, budgets/low-space injection and corrupt-byte recovery.
32 native I/O cycles and8 authority startup loops both measured96 →96 descriptors.
Initial D-pad immediate-observer failure, pre-fix resource crash and FD3/3 failures
are preserved separately. D-pad now polls the native Center result within3s without
JS input/renderer changes. Unchanged image/visual suites and clean builds were not
repeated. External restart/reboot result and precise source/APK scope are recorded
in the current evidence report. Physical Android/TV, production admission, hostile
source/filesystem guarantees, GPU failure, power-loss durability and stage4 remain open.
Final external attempt PASS: fresh C/B native preparation, real kiosk/TV receipts,
capture closure/providers disabled, external force-stop and fresh private launch,
then actual in-session ADB shell reboot. Boot ID changed
`3ae4f102-55d9-4cbe-becc-f2efbd509496` → `af3a4395-f93e-42ce-a9bf-bc15f05f8629`;
host launcher19736/QEMU29520 stayed identical and private revision/native-authority/
pointer/mode/receipt hashes were unchanged. Explicit post-reboot TV ready/rotation
and kiosk next-card worked with zero asset reads. Original failed/hung transport
attempts are archived, not counted as successful reboot. The successful final
attempt performed a real guest reboot inside one owned AVD session; creating that
session was not used as reboot evidence. Guarded final cleanup stopped it without
snapshot save. Screenshots were actually inspected; no physical/color-parity claim.

## Disposable captured candidate session — 2026-11-01

[CapturedCandidate](app/src/main/java/org/kiosk/harness/binding/CapturedCandidate.java)
adds an explicit owner/lifecycle around the generic binding boundary. Native
`capture(Context, packageSource, kioskSource, tvSource, expectedPackage, renderer,
kioskWitness, tvWitness, Budget, Cancellation)` accepts logical streams and the
same independent typed witnesses, never external directories, URIs or archives.
It creates one unique `session-*` tree under the app's no-backup
`captured-candidates` root; this is separate from the fixed publication store.
There is no public raw pathname, writable file handle or generic activation API.

The caller supplies nonnegative `Budget(maxBytes, maxFiles, minFreeBytes)` for
this capture. Byte/file counts include all package and both view files/descriptors,
including duplicated media. Overflow-safe accounting rejects declared excess
before copying; available space is checked before creation and before each file.
These are experimental per-call resource controls, not new Events quotas, global
disk reservations, concurrent-session quotas or guarantees that writes will fit.
Allocation/write/close errors still fail. Capture streams16KiB blocks, reuses
`PinnedSource` to enforce declared/actual size/hash and exact source inventory,
and creates files with `CREATE_NEW`. It does not buffer the complete bundle;
the existing packagecore/LocalView parsers retain their documented bounded buffers.

Only the pinned manifest is initially copied. The new manifest-only
`EventsPackage.inspectManifestCompatibility` reuses the same extracted helper as
full inspection; unsupported tuple/schema/entrypoints fail before data/media copy.
After copying, `PublicationBinding.inspect` runs entirely on the saved trees,
including exact captured inventory, pins, descriptor/mode/revision and trusted
JS/CSS checks. No original provider is retained by the returned session.

`report()` retains the existing non-activating binding result and **all five**
packagecore admission gates. `scopedGuarantees()` adds provider-independent capture,
verification before open, revocation on close and the exclusive app-owned model.
Neither result claims authenticity, independently computed canonical identity or
renderer build, HTML derivation, production image admission or hostile filesystem
safety. Original providers may change/disappear after successful capture without
changing the saved candidate. This is not absolute immutable protection from a
same-UID/root writer: permissions or an undisclosed pathname are not such proof.

### Read scopes, cancellation and ownership

`source(PACKAGE|KIOSK|TV)` exposes logical read-only inventory/open operations.
Before returning any handle, `open` verifies the **whole saved file** against its
independent pin and rewinds the same read-only descriptor. A corrupted file
therefore fails before a consumer receives a handle/bytes. It does not return a
raw FileInputStream/FileChannel. This assumes exclusive app-owned writes; mutation
by a hostile same-UID/root writer during or after verification is outside the
guarantee. Each open repeats verification rather than treating an old report as
a future-read capability. The result is not wired to LocalView display or store.

The caller owns the returned AutoCloseable session. Capture owns/closes input and
output streams, including read/close/cancellation failures; provider objects remain
caller-owned. Cancellation is cooperative at creation, manifest/file/chunk and
binding boundaries, not interruption of a blocking provider/native call. It applies
to in-progress capture; cancel after return is not close. Use a worker thread.
Session operations and handle reads serialize with close. Close marks the session
closed, closes/revokes every opened handle, then removes only that session's tree.
Existing handles reject subsequent reads; repeated handle/session close is safe;
report/source/files/open after close reject. Cleanup failure has a stable code and
close can retry removal. Another live session is not removed. Empty parent root
may remain. Process death can leave disposable orphan trees; there is no recovery,
startup scanning, GC, persistent publication commit or power-loss durability claim.

Filesystem decisions use official Android docs:
[no-backup app root](https://developer.android.com/reference/android/content/Context#getNoBackupFilesDir()),
[unique temp directories and create-new files](https://developer.android.com/reference/java/nio/file/Files),
[available-space hint](https://developer.android.com/reference/java/io/File#getUsableSpace()).
The APIs used are available below the harness minSdk30 (no-backup21, NIO26,
usable-space9). No new permission or dependency is added. Internal path traversal
checks/no-follow inventory checks are defense within the owned-tree model, not
a replacement for hostile-filesystem admission or a new source trust policy.

### Focused checks and reproduction

Same vendored C inputs/witness/provenance as the binding slice; no A/B catalog or
shared renderer change. Native test-only hooks inject faults/cancellation/space
and captured mutation; no Intent/page/controller selects them in the harness.

```powershell
& android/tools/build.ps1 -BuildJdk $BuildJdk -AndroidSdk $AndroidSdk -ReadOnlyDependencyCache $Cache -Tasks ':app:testDebugUnitTest','--tests','org.kiosk.harness.binding.*Test','--tests','org.kiosk.harness.packagecore.EventsPackageTest',':app:assembleDebug',':app:assembleDebugAndroidTest','--offline'
# On a verified owned read-only emulator after installing the two debug APKs:
adb -s VERIFIED_SERIAL shell am instrument -w -r -e class org.kiosk.harness.binding.CapturedCandidateAndroidTest,org.kiosk.harness.binding.PublicationBindingAndroidTest,org.kiosk.harness.packagecore.PackageParserTest org.kiosk.harness.debug.test/org.kiosk.harness.HarnessTestRunner
```

Evidence: `logs/pc2-captured-session-20261101-121938/`. PASS20 JVM methods
(8 new session,6 binding,6 affected packagecore). Android:18/19 initially passed;
the isolated-store test setup used an alias path rejected by the existing store's
plain-path policy. Canonicalizing **only that test path** fixed it; its focused
rerun PASS1/1. Thus all19 distinct checks passed, not one claimed clean19-test run
on the final test APK. Main session/core code was unchanged by the setup fix.
New cases cover provider loss/mutation after capture, mutations during copy and
binding, pre-open corruption refusal, short/overlong/zero/error/close failures,
inventory/witness failures, cancellation at9 boundaries, partial copy, budgets and
simulated low space, open handles/use-after-close, two owners and early tuple refusal.
The Android-only public Context factory and existing isolated store preservation
also passed; the latter compares every byte including pointer, mode and both
test-generated receipts, without claiming new real renderer readiness.
Main/test builds PASS; no unchanged UI/image/visual suites were repeated.
Medium_Phone Android17/API37/x86_64; physical Android/TV, all admission gates and
stage4 remain open. Await PC1 review before connecting any further functionality.

## Generic non-activating package/view binding — 2026-11-01

Implemented [PublicationBinding](app/src/main/java/org/kiosk/harness/binding/PublicationBinding.java)
and [DevelopmentWitness](app/src/main/java/org/kiosk/harness/binding/DevelopmentWitness.java),
separate from fixture catalog, storage, UI and activation. `inspect(packageSource,
kioskSource, tvSource, expectedPackage, renderer, kioskWitness, tvWitness)` reuses
`EventsPackage.inspect` and `LocalView.verify`. It accepts three logical
`LocalView.Source` instances plus independently supplied typed native expectations;
there is no directory/ZIP/URI importer and no witness JSON parser in the main API.
The C fixture is **not** added to `PublicationFixtures` or main APK assets.

The package witness supplies an explicitly **caller-attested canonical identity**,
separate raw-manifest SHA256 and complete file size/hash inventory, including the
manifest. No canonical JSON algorithm is introduced. The two artifact witnesses
bind mode, expected package identity, renderer-witness identity and full inventory
including `view.json`. A separate renderer witness supplies the expected renderer
identity and trusted JS/CSS hashes. The API compares artifact renderer identities
with that native expectation, but does not independently derive the Python renderer
build from the package. LocalView still checks schema, mode, package identity,
inventory and independent JS/CSS; binding additionally checks package/view revision.
Descriptor equality alone does not prove HTML derivation. A caller loading its
expectations from the same untrusted source has not established independence.

`Report` contains the caller-attested canonical package identity, observed raw
manifest hash, revision and per-mode artifact identities (raw descriptor hash plus
the complete observed inventory). Proven checks are structural/integrity validation,
observed inventory/size/hash, package/mode/revision agreement, caller-witness match
and JS/CSS match. All five packagecore unchecked gates remain: image validation,
Android decoder parity, filesystem safety, source trust and activation readiness.
Additional explicit unproven items are independently computed canonical identity,
HTML derivation, independently computed renderer build, source immutability and
future reads/lifetime. There is no ready/activation flag, usable view/source handle,
pointer, receipt or store write in the result.

### Streams, ownership and bounds

Caller owns the three source objects and must keep them usable for the complete
synchronous call. The inspector owns and closes every stream returned by `open`,
including failure paths; it does not close source objects. Close errors fail the
inspection. Each open may happen multiple times: pinned manifest preflight,
packagecore passes/resource rereads, complete inventory pin pass, view preflight
and descriptor revision reread. Every read is independently size/hash checked;
short, overlong, zero-progress and error streams fail. Inventories are checked at
entry and after inspection. No snapshot or cross-file simultaneity is promised:
mutation outside observed reads, post-return changes, symlinks/parent races and
source lifetime remain unchecked. The report is not a capability for later use;
subsequent consumers must establish their own stable-byte guarantees and admission.
Synchronous source calls must return; byte bounds do not interrupt a blocking
`open/read/files/close` or protect against a hung caller-supplied provider.

Package limits mirror packagecore: manifest2MiB, payload file256MiB, payload sum64MiB,
10000 payload entries. View limits remain separate LocalView adaptations:
descriptor2MiB, file64MiB, payload sum128MiB, 10000 payload entries. Witness accounting
uses subtraction before addition and streaming16KiB blocks without whole-file
allocation; existing packagecore/LocalView buffering limits remain in force.
Unknown-property/schema behavior in those inspectors is unchanged. Compatibility
is checked by packagecore before opening package data/media. Error boundary
`BindingFailure.Code` emits fixed codes only, without source exception causes,
suppressed exceptions, payload or private paths; multi-defect ordering is not a contract.

### Inputs and focused reproduction

Vendored test-only [C inputs/provenance](testdata/generic-binding/provenance.json)
come from PC1 `inputs.zip` SHA256
`6c58ec4683e038cca00b924d387ef9cbe735450a46f854801fbf775a96fdf07e`.
PC1 independently attests canonical package identity
`b14a125bde2dafbccb1c304f0ac0ae22428e2caef7c79e02ffebebccf215e731`;
its raw manifest happens to have the same hash, which is not a general equality.
`pc1-witness.json` is consumed only by the shared **test adapter**, not a required
serialized product protocol, signature or production authentication. Preparation
remains PC-side using the existing Python renderer/cache; shared artifacts are unchanged.

```powershell
& android/tools/build.ps1 -BuildJdk $BuildJdk -AndroidSdk $AndroidSdk -ReadOnlyDependencyCache $Cache -Tasks ':app:testDebugUnitTest','--tests','org.kiosk.harness.binding.PublicationBindingTest',':app:assembleDebug',':app:assembleDebugAndroidTest','--offline'
# Install only the debug/test APKs on the verified owned read-only target, then:
adb -s VERIFIED_SERIAL shell am instrument -w -r -e class org.kiosk.harness.binding.PublicationBindingAndroidTest org.kiosk.harness.debug.test/org.kiosk.harness.HarnessTestRunner
```

Evidence: `logs/pc2-generic-binding-20261101-115606/`. Final focused JVM6/6 and
Android6/6 PASS (Android1.583s), affected main/test APK build PASS. Vectors include C
outside A/B, witness/package/mode/renderer/JS/CSS mismatch, descriptor/self-hash
tampering, missing/extra files, bounded/short/overlong/zero/error/close streams,
changed rereads, early unsupported tuple refusal, revision mismatch and lifetime.
Publication store was absent both before and after instrumentation; no Activity or
activation ran. Original compile failure (`JSONObject.keySet` in shared test) and
its `keys()` correction are preserved separately from final results. Existing
UI/image/visual suites were deliberately not rerun: their sources and wiring are
unchanged, while this API is unreferenced by the display/store paths.
Medium_Phone emulator Android17/API37/x86_64, WebView145.0.7632.218; guarded owned
emulator cleanup performed with no snapshot save. Physical Android/TV, full image
and source admission, production trust and stage4 remain open. Next step requires
PC1 review of this observational boundary before selecting further implementation.

## Integration candidate review — 2026-11-01

The accumulated implementation is a **debug development harness**, ready for scoped
source review, not production admission or stage4 acceptance. The read-only review
bundle is `logs/pc2-integration-review-20261101-113613/`: `inventory.json`,
`future-commit-files.txt`, `untracked-deliverables.sha256`, `evidence-map.md` and
`integration-review-report.md`. The ordinary Git diff excludes untracked files;
`full-text-review.diff` combines its tracked portion with a separate untracked text
export. Binary fixtures and Wrapper JAR are identified by SHA256 in the inventory.
Nothing was staged, committed or removed.

The final mode-slice source hashes and existing debug APK are unchanged. Existing
evidence is reused only with the scope and source comparisons in the review bundle;
no engine, image or clean-build suite was repeated for this documentation review.
Build/test inputs are vendored under `android/`; ignored logs contain historical
evidence and optional PC1 provenance-verification inputs. The historical
`prepare-package-test-assets.py`, `check-fixtures.py` and
`check-runtime-fixtures.py` need the original PC1 logs and are **not build or test
prerequisites**. The image generator reads vendored sources; its manifest retains a
historical logs provenance label rather than reading that path.

`:visualtest` is a separate application, not an `:app` dependency. Instrumentation
classes and parity assets are absent from the ordinary harness APK. Injection
interfaces/checkpoints and package-private Activity configuration methods remain
in main harness bytecode; their controller is in the test APK, with no Intent or
page-based fault selection. This is isolation of test control, not removal of all
test seams from the main APK. Both exported harness Activities and native A/B
fixture controls are experimental surfaces. No product/release variant is accepted.

Proposed next functional block, **requiring PC1 review before implementation**:
define and exercise one bounded local publication-candidate boundary that binds a
full Events package to separately prepared kiosk/TV artifacts from the unchanged
common renderer, independent of A/B catalog identities. Keep renderer generation
on the existing Python side initially; Android does not execute package templates
or introduce another renderer. The artifact handoff, independent trust/identity
binding, image admission and source guarantees require explicit decisions; an
external prepared view is not automatically trusted because its descriptor names
a package. See the review gap matrix for technical tasks versus open decisions.
No importer, transport, decoder, admission, activation or new format was added by
this review. Physical Android/TV, image/source admission and stage4 remain pending.

## Authority and source identity

The owner selected the minimal experimental harness on 2026-10-31 after PC1 design
review. The bounded implementation and measured results are recorded below; the
remaining design sections are proposals, not implemented product features or acceptance.
Base and HEAD: `5d652d4d99a577e8809a87839800a9f24c6250fa`.
Branch: `android/events-conformance-design`; clone:
`C:/Users/admin/AndroidStudioProjects/Kiosk_v001` (origin German7464/Kiosk_v001).
The unrelated Kiosk_Android_app scaffolding is preserved and supplies no platform decision.
The owner's coordinated continuation confirms PR #1 integration and this exact v2 base;
BLOCKED/PENDING in the historical task draft is superseded for this task, not edited.

Sources: [root instructions](../AGENTS.md), [workflow](../docs/TWO_PC_WORKFLOW.md),
[approved specification](../docs/TZ_RECONCILED.md) R§3, R§10.4/R§10.5/R§11, R§17.1, R§18, R§22/R§24.2,
[current control ledger](../docs/TZ_PROGRESS.md), [contracts](../contracts/README.md),
[Events edition 1](../contracts/events-v1/README.md), and
[publication implementation](../kiosk/publication/README.md).
PC1 alone maintains the ledger. Implementation is confined to `android/` with ignored evidence under `logs/`; the
root AGENTS changelog rule is satisfied by a short documentation-only delivery note.
Prior README edits are retained. Ordinary project dependencies,
Wrapper and debug installation on the existing emulator are owner-authorized. No shared
contract/renderer, server/Windows code, ledger or Kiosk_Android_app scaffolding changes.

## Implemented experimental slice — 2026-10-31

### One private publication in kiosk/TV, selected mode and guest reboot

The same fixed-fixture store/coordinator now supports both modes, using one complete
Events package per A/B identity and PC1's unchanged prebuilt kiosk/TV artifacts. No
independent renderer, general importer, decoder/admission policy or shared format was
added. Packagecore's five unchecked gates remain unchanged. This extends the earlier
TV-only experimental scope below; its dated no-reboot/no-kiosk results remain historical.

[PublicationFixtures](app/src/main/java/org/kiosk/harness/storage/PublicationFixtures.java)
adds only the exact kiosk pins from the independently hashed original ZIPs. Both kiosk
view trees match their ZIP/extracted sources byte-for-byte and bind to the already pinned
A/B package IDs. Existing packages, TV views, image corpus and renderer JS/CSS are unchanged.
Native fixture installation prepares both modes; package bytes are copied only when a
revision is absent. An explicit install of an old TV-only revision adds its missing kiosk
artifact cache without reimporting the package. A corrupted committed cache is refused,
not repaired. Mode switching/startup never construct an asset source or fill a missing view.

```text
fixture-publications/
  revisions/<package ID>/package/   # one full Events package, shared by both modes
  revisions/<package ID>/view/      # original TV location preserved
  kiosk-views/<package ID>/view/    # pinned kiosk artifact cache
  selected-mode.json               # private choice, independent of publication/ready
  last-ready-tv.json
  last-ready-kiosk.json
  active.json / active.backup.json
```

Mode cache paths are internal, not a new Events format. The original TV descriptor pins,
BUILD value, receipt encoding and filenames are preserved exactly. Absent selected-mode
metadata defaults to TV for compatibility; an invalid existing mode record fails safely
instead of guessing TV. No automatic data migration/import occurs on startup. Actual
upgrade was tested by installing the previous PC1-reviewed APK, writing A/TV with it,
then updating to the new APK with `install -r` (no clear/uninstall): old private hashes
and receipt bytes remained identical and new TV startup used0 fixture asset opens.

#### Choice commit, visibility and receipts

`selected-mode.json` is an atomic, bounded internal `{schema:1,mode:"tv"|"kiosk"}` record.
For a published package, the native mode action verifies that package and the requested
private artifact, then commits the choice **before** the existing WebView preparation.
An empty store can remember an explicit mode request, but stays non-ready until a fixture
is installed and actually ready. This separates the mode argument from publication and
ready evidence as Windows does: its mode participates in cache identity and mode-specific
last-ready records, rather than being an Events-package revision.

| Situation | Pointer | Selected mode | Actual display | Receipts |
| --- | --- | --- | --- | --- |
| Successful mode switch | Same package | Atomic new choice | Changes only after current DOM/visual ready | Write only the new mode's receipt |
| Missing/bad other view or failure before mode rename | Unchanged | Old choice | Working old view retained | Both unchanged |
| Error after mode rename, or new renderer preparation failure | Unchanged | New choice may already be committed | Working old view retained; status shows the distinction | No invented new ready; no rollback |
| Receipt write failure after ready | Unchanged | New choice | Actual new mode remains visible, receipt pending | Other mode untouched; after-rename error may already have written the new receipt |
| Invalid mode metadata at startup | Unchanged | Invalid (not guessed) | Native safe non-ready message | Records preserved; explicit known-mode action may recover |

`visible` and `visible_mode` identify the actual live view; `selected_mode` is authority
for the next start. `receipt_tv` and `receipt_kiosk` are separate historical ready evidence.
A TV receipt copied to the kiosk filename is invalid. Startup snapshots the selected mode
and eligible records **under one writer lease**; it verifies the current artifact and at
most one distinct confirmed artifact of that same mode. No cross-mode ready inference,
directory-scan selection, asset repair or cyclic renderer/process restart. A mode change
restarts the unchanged view's navigation position; event/slide position is not persisted.

On Activity recreation, startup may briefly wait for the old worker's lease within the
existing20s UI deadline; this is bounded lock acquisition, not a renderer restart loop.
`finish()` immediately cancels its generation/worker and disposes the candidate on UI;
final active cleanup remains detach -> destroy. Late DOM/visual completions cannot mark
another mode ready after closing. This was a necessary lifecycle correction found by the
new late-callback test; first run45/46 and the corrected results are retained. The
[Activity lifecycle reference](https://developer.android.com/reference/android/app/Activity#finish())
was checked: requesting finish and reaching onDestroy are distinct lifecycle boundaries.

One writer/busy gate still covers package, artifact and mode operations. Existing
`.incoming` package/TV staging and added `.kiosk-incoming` artifact staging are sequential
under that lease, associated with the same fixed fixture. Each uses pin-derived byte/tree
bounds, exact inventory/hash checks and the existing file/directory sync +rename adapter.
Interrupted operations are retained and only explicitly resumed for their fixture. No
active/recovery data deletion or general GC/product quota was added. Sync/rename are
separate steps and do not form a multi-record transaction; after-rename uncertainty and
all earlier hostile-writer/TOCTOU/durability limitations still apply. Timers remain15s
native/20s coordinator and do not independently protect a blocked UI/native thread.

#### Measured mode/restart/reboot checks

Evidence: `logs/pc2-modes-reboot-20261031-203239/` (host-clock directory label), including `plan.md`, `report.md`,
`fixture-identities.json`, `source-apk-identities.json`, complete commands/results,
mode/pointer/visible/receipt states, screenshots, reboot polling and cleanup proof.

| Check | Actual result |
| --- | --- |
| Mode/source/core tests | PASS6 new store methods: old TV bytes/default mode, no package recopy, mode commit boundaries, cross-mode receipt refusal, same-mode confirmed fallback, missing/corrupt cache/mode metadata, kiosk staging resume and receipt failure |
| Real mode coordinator | PASS6 new methods: A home/events native touch, B next/previous native touch, automatic TV transition/back with unchanged import counters, bad other view retaining current, mode/receipt write faults, early close/late callback and explicit invalid-mode recovery |
| Affected regression | PASS46/46 in173.956s after recreation fix:18 store/platform +13 coordinator +10 engine +5 lifecycle; final atomic startup-snapshot refinement reran all31 store/coordinator methods, PASS31/31 in79.0s; untouched engine/lifecycle evidence reused |
| Legacy actual APK upgrade | PASS old A/TV data and receipt bytes unchanged, no selected-mode file created by startup, private TV-ready with0 fixture opens |
| External A/B kiosk | PASS actual home/events and both B cards via native controls; prepared missing A kiosk cache explicitly with5 view opens and0 package opens; B imported once, package counter16; mode switches did not import again |
| External selected kiosk force-stop | PASS old process absent for6s; fresh PID9837 kiosk-ready with116 private opens/0 fixture opens, then real Next navigation |
| Same live AVD guest reboot | PASS boot_id changed, same host launcher/QEMU PIDs and private package/cache/metadata hashes; no app PID before explicit launch; TV-ready PID2722 with116 private opens/0 fixture opens and actual automatic ONE/TWO transition |
| Post-reboot kiosk/failure | PASS explicit kiosk switch and navigation with0 imports; corrupt other-mode TV view refused while kiosk and both receipts remained; no repair; exact test-byte restoration then private-ready |
| Unchanged image checks | SKIPPED: image-parity/visual corpus and suites were not repeated |

The final source reads mode+choices as one leased snapshot;31 targeted tests and the
external reboot ran on that APK. Earlier46-run engine/lifecycle code/PreparedWebView/core
and renderer assets were unchanged by this refinement. The first external observer
expected uppercase `TV` instead of stored enum `tv`; app was correctly ready. Observer
normalization and resume-after-B preserved the successful setup/import/navigation evidence.
No incomplete attempt was counted as reboot or test success.

Boot IDs: `1e06581f-a92e-426f-9b73-90534c93b66b` ->
`71e763ad-e186-4a39-a549-74799cfc05fb`; observed boot polling18.7s. Host launcher23728 and
QEMU22080 stayed the same across `adb -s emulator-5556 reboot`. No close/new read-only
session, snapshot restore, force-stop substitute or reinstall was used for the reboot.
The official [ADB documentation](https://developer.android.com/tools/adb) and
[emulator data/command-line documentation](https://developer.android.com/studio/run/emulator-commandline)
were checked before the experiment. Read-only session data was preserved across the guest
reboot; that does not imply retention when the read-only emulator process is finally closed.

Target stayed Medium_Phone, Android17/API37/x86_64,
`google/sdk_gphone64_x86_64/emu64xa:17/CE2A.260420.051.A2/16418371:user/release-keys`,
WebView `com.google.android.webview/145.0.7632.218` before/after. No INTERNET permission,
network fallback, boot receiver/autostart, lockdown or system setting was added. App
fixture-open counters exclude framework/provider resource reads; hash comparisons and
negative missing/corrupt-view observations independently rule out asset repair.

Original screenshots were actually viewed: `test-mode-A-kiosk-home.png` shows the real
home, B kiosk shows1/2 and2/2, post-reboot TV shows the image/title without kiosk controls,
post-reboot kiosk home/events and the refused-other-mode screenshot retain correct content.
The earlier `A-kiosk-home.png` captured the pre-paint event screen and is retained only as
a timing artifact; it is not the home proof. No screenshots were substituted with DOM-only
claims. Only the owned launcher23728/QEMU22080 were stopped after all checks with guards;
no snapshot saved. Physical Android/TV, display/color/remote acceptance, production
admission/decoder/source trust and sudden power-loss durability remain open. Stage4 is
incomplete. A normal emulator OS reboot is not a sudden-power-loss test.

```powershell
& android/tools/build.ps1 -BuildJdk D:/programThisPc/AndroidStudio/jbr -AndroidSdk C:/Users/admin/AppData/Local/Android/Sdk -ReadOnlyDependencyCache C:/Users/admin/.gradle/caches -Tasks ':app:assembleDebug',':app:assembleDebugAndroidTest','--offline'
adb -s emulator-5556 shell am instrument -w -r -e class org.kiosk.harness.StoreTest,org.kiosk.harness.StoredCoordinatorTest,org.kiosk.harness.EngineTest,org.kiosk.harness.LifecycleTest org.kiosk.harness.debug.test/org.kiosk.harness.HarnessTestRunner
# On that SAME verified running owned AVD, after saving baseline boot_id/private hashes:
adb -s emulator-5556 shell cat /proc/sys/kernel/random/boot_id
adb -s emulator-5556 reboot
# Bounded wait for changed boot_id +sys.boot_completed=1; no replacement emulator session.
adb -s emulator-5556 shell am start -W -n org.kiosk.harness.debug/org.kiosk.harness.StoredHarnessActivity
adb -s emulator-5556 exec-out run-as org.kiosk.harness.debug cat files/fixture-publications/display-state.json
```

Next step is PC1 review of this scoped shared-publication/mode/reboot evidence before
any further delivery or production-admission implementation.

### Fixed-fixture private publication and offline restart ? 2026-10-31

Owner-selected scope now includes a **development fixture store/coordinator**. This
supersedes earlier no-store/no-switch scope statements only for the exact A/B experiment
below. It does not implement general package admission, arbitrary sources, networking,
D13, delivery, replication, updates or a production filesystem/image adapter. All five
packagecore unchecked gates remain intact, including IMAGE_VALIDATION, FILESYSTEM_SAFETY,
SOURCE_TRUST and ACTIVATION_READINESS. A `Selection` is a closed-fixture view handle,
not a general admission token; independently pinned bytes are not production trust.

The default MAIN/LAUNCHER/LEANBACK entry is now
[StoredHarnessActivity](app/src/main/java/org/kiosk/harness/StoredHarnessActivity.java).
It opens saved private data only; empty or unusable storage shows a native safe message
and never reports ready. Explicit native buttons install/resume fixed A or B. No Intent,
page, URI, archive or arbitrary-directory import/fault configuration is accepted here.
The earlier HarnessActivity remains a direct test entry for existing asset-view cases.

| Component | Responsibility |
| --- | --- |
| [PublicationFixtures](app/src/main/java/org/kiosk/harness/storage/PublicationFixtures.java) | Independent build-owned exact file sizes/hashes, package IDs, view descriptors and catalog/renderer generation |
| [FixtureAssetSource](app/src/main/java/org/kiosk/harness/storage/FixtureAssetSource.java) | Explicit fixed-button A/B preparation only; startup/recovery never constructs it |
| [FixturePublicationStore](app/src/main/java/org/kiosk/harness/storage/FixturePublicationStore.java) | Writer lease, bounded copy/staging, packagecore inspection, artifact preflight, atomic pointer and ready receipt; bounded record-led recovery |
| [PrivateFiles](app/src/main/java/org/kiosk/harness/storage/PrivateFiles.java), [StoreMetadata](app/src/main/java/org/kiosk/harness/storage/StoreMetadata.java) | App-owned file access, sync/rename, exact private inventory, bounded internal metadata; not a general safe-source admission API |
| StoredHarnessActivity | Single worker with one outstanding preparation, hidden candidate, generation/20s watchdog, swap only after existing DOM/visual ready, separate visible state and receipt-pending status |

#### Closed fixture provenance and byte identity

Only original PC1 full packages and corresponding unchanged TV views are used, copied
into `app/src/main/assets/publications/{A,B}/{package,view}`. Both original ZIP SHA256
pins from the earlier harness are rechecked, then **all four extracted/package asset
trees are compared byte-for-byte to ZIP entries**. Every descriptor inventory, byte
size/hash, renderer JS/CSS pin, and view/package/mode binding is verified. PC1 canonical
manifest identities are independently checked at fixture preparation:

| Fixture | Package identity | Source | Full package+view bytes |
| --- | --- | --- | --- |
| A | `3658670566f16d0cb77e0f58facc10bcb2ec518100764421d3510ef1a604edfa` | original contract/valid + contract/view-tv | 587361 |
| B | `0d027e264096337f7f37f3ca6dd128ed3e6622aa2491ee404f742bb7f5cd1d18` | original two-card package + two-card-tv | 587930 |

Catalog pins map **exact raw manifest bytes** to these already-known PC1 canonical
package identities. This avoids inventing a general JVM canonical-JSON identity
algorithm. Any modified fixture, including otherwise tolerated unknown properties,
is outside this development source; packagecore's generic unknown-property tolerance
has not changed. Prepared `view.json` and package `manifest.json` remain different
formats. Full package resources are retained/inspected but never executed: PreparedWebView
serves only the independently pinned prebuilt view and unchanged shared renderer assets.
There is no runtime rendering/generation from package-supplied HTML/JS.

#### Store, commit and state separation

Persistent root is `getFilesDir()/fixture-publications`, not cache or APK assets. Only
the OS-supplied files root is canonicalized before app-owned descendants are selected:
inside this emulator's **app namespace** `/data/user/0` is a system alias/symlink (different
from the adb-shell namespace). Initial strict ancestor checks refused it; the evidence
contains native/NIO diagnostics and the targeted fix. Symlink ancestors/components in
the selected private tree are still refused; leaf open uses O_NOFOLLOW and fstat regular
file checks. This is not a hostile-concurrent-writer/parent-TOCTOU guarantee. Exclusive
app ownership and this harness's write-once revision protocol are assumptions; debug
run-as mutation is used only in tests. Packagecore FILESYSTEM_SAFETY stays unchecked.

Each preparation holds a non-blocking FileChannel lock, then copies bounded streams into
one `.incoming` operation with a synced owner marker. Source file-set equality is checked
before copy. Each payload is limited by its independent fixture pin, streamed in at most
256KiB blocks with remaining+1 excess detection, exact size/SHA256 and no-progress refusal;
each private package/view tree is then re-enumerated and rehashed, packagecore runs, and
LocalView preflight validates package/mode plus independent JS/CSS pins before pointer
commit. Closed pin sizes bound additional pin-check buffering (largest445924 bytes);
existing package/view level limits are unchanged and are not new product quotas.

The complete directory is renamed to `revisions/<package identity>` before any pointer
can reference it. Already committed revisions are reverified and reused, never repaired
from assets or overwritten. `active.backup.json` saves the previously resolved revision,
then `active.json` atomically replaces current/previous. Native metadata is bounded4096
bytes and canonical/exact; its schema is internal Android state, not Events-v1.

| State | Meaning / failure behavior |
| --- | --- |
| active.json (+ backup) | Publication authority after package/artifact preflight; can become B while A is still visible |
| Activity visible ID / live WebView | Only changes after the current generation's fixed DOM + visual ready; a hidden-candidate failure keeps a still-working A |
| last-ready-tv.json | Written after actual ready, binds known package, TV view descriptor and compiled catalog/renderer generation; a write failure keeps actual B visible with receipt pending |
| display-state.json | Advisory PID/session/source/three-state diagnostics, may lag the UI; never used to select/recover/activate |

Runtime renderer loss clears visible and shows a safe message; it does not roll back
publication or rewrite the historical last-ready receipt. A shared renderer/GPU cannot
promise retention of A. There is no automatic runtime restart loop. Explicit relaunch
revalidates saved bytes and attempts the resolved current view, then at most one distinct,
verified last-ready view for this generation if startup preparation fails. Store resolution
checks active current/previous then backup current/previous, independently revalidating
packages; artifact failure then uses only a confirmed receipt, matching Windows semantics.
No selection by directory scanning, mtime or newest name, no startup asset repair. Invalid
pointer/receipt with no usable record gives a safe non-ready state even when revision
directories exist. Recovery does not silently rewrite the publication pointer.

One worker/busy gate and OS writer lease prevent parallel preparations; no unbounded
request queue. Only two fixed revision slots are possible and neither is GC'd. One
staging operation is retained on interruption/error and ignored for startup selection;
new preparation for another fixture is refused while it exists. An explicit button for
the same fixed fixture resumes its owned partial files and rechecks the complete result.
Only that operation's own `.part` files are rewritten; committed/recovery data is not
removed. Scratch-byte bound is the selected pinned package+view total plus its largest
file and8192 metadata bytes; tree work is also bounded from pinned entry counts. This is
an experiment-derived scratch envelope, not a product storage quota. Free-space checks
are best-effort, not reservations; unexpected write/sync failure refuses the candidate.
An unrecognized/missing operation marker is preserved and refused, not automatically
cleaned; no general repair/GC is implemented.

#### Android API decision and durability limits

Official documentation was checked via Context7 and direct Android reference before API
selection: [app-private files](https://developer.android.com/training/data-storage/app-specific),
[canonical platform root](https://developer.android.com/reference/java/io/File#getCanonicalFile()),
[FileChannel.tryLock](https://developer.android.com/reference/java/nio/channels/FileChannel#tryLock()),
[FileDescriptor.sync](https://developer.android.com/reference/java/io/FileDescriptor#sync()),
and [Os.rename/fsync](https://developer.android.com/reference/android/system/Os).
Android Os documents the Linux syscall semantics; see its linked
[rename documentation](https://man7.org/linux/man-pages/man2/rename.2.html) and
[directory fsync requirement](https://man7.org/linux/man-pages/man2/fsync.2.html).
Same-filesystem rename replaces the pointer as one namespace operation. Files are flushed
and descriptor-synced before rename; affected directory descriptors are fsynced afterward.
This platform adapter adds an explicit directory-sync attempt; it is not a measured
improvement over Windows. No hidden cross-filesystem copy fallback is used. A sync/close
error after successful rename can mean **commit happened despite reported failure**;
records are re-read, not rolled back or deleted. Metadata files are separate commits,
not one multi-file transaction. Linux/application sync calls are not a measured guarantee
for host disk/controller behavior, emulator persistence, device reboot or power loss.
Only process termination/restart was exercised. Handler20s is a UI-loop deadline, not an
independent guard against a blocked UI/native thread; candidate preparation retains15s.
Each distinct confirmed startup attempt has its own bounded coordinator attempt, as in
Windows. Cancellation/generation checks prevent late callbacks from attaching views;
commit completion concurrent with process/Activity loss is resolved by persisted records.

#### Actual checks and reproduction

Evidence: `logs/pc2-private-publication-20261031-194514/`. `plan.md`, `report.md`, `fixture-identities.json`,
`zip-extracted-asset-parity.json`, `source-apk-identities.json`, full command/log files,
state JSON, fault scenario matrix, screenshots and guarded-cleanup proof are retained.

| Check | Actual result |
| --- | --- |
| New storage/platform tests | PASS12 (including one metadata diagnostic); raw roundtrip, bad hash/missing/extra/copy error, wrong view identity, staging resume,9 pointer/journal boundaries,3 receipt boundaries, corrupt records/package/view, single writer and link refusal |
| New real coordinator tests | PASS7: A->B, private restart, hidden candidate refusal, receipt-pending B, bounded confirmed fallback, actual renderer terminate/onRenderProcessGone, actual20s staging watchdog and recreation |
| Affected existing engine/lifecycle | PASS10 engine +5 lifecycle; together with18 new tests33/33 in142.245s; final isolated identity/extra-source test1/1 in0.741s |
| External process interruption | PASS: deliberately killed instrumentation during open B staging stream; observer continued outside app, staged bytes survived, A fresh private-ready PID6700; explicit B button resumed complete publication |
| External B force-stop/fresh launch | PASS: old PID6700 absent for10s with no self-restart; new PID7103, fresh session, pointer/visible/receipt B,116 private reads and0 asset opens; persisted package/view trees byte-identical; actual ONE/TWO transition and blue image observed |
| No hidden assets fallback | PASS: corrupt private B index -> PID7583 safe failed, visible=null, pointer/receipt still B,96 private reads,0 asset opens; damaged file unchanged despite intact APK; explicit exact-byte restoration -> PID7671 private-ready |
| Final launcher route | PASS: MAIN/LAUNCHER resolves StoredHarnessActivity; launch resolved component (no fixture extras) -> PID8087 B-ready,116 private reads,0 asset opens; no INTERNET permission |
| Image parity/visual suites | SKIPPED unchanged; no repeated21 measurements or visual suite |

`asset_reads` counts fixture payload open calls through FixtureAssetSource, not framework/
WebView-provider resource reads. `private_reads` counts pinned private package/view opens;
metadata reads are separate. The damaged-private negative independently rules out silent
fixture repair, rather than relying on counters alone.

The33-test run preceded the final launcher-only manifest move and added isolated source
negative; main Java, PreparedWebView, core and assets were unchanged afterward. Final APK
launcher/cold-start smoke and the added test passed; reuse is not a claim of re-running33
against a different manifest. PC1 fixtures/oracles and shared code were not modified.
Initial compile/API and alias failures are preserved. External observer diagnostics also
remain: exec-out exit status did not prove marker existence (fixed PID+content check),
Button text was uppercase (fixed casefold lookup), and plain implicit am-start lacks
launcher explicit-component resolution (queried MAIN component then launched it).
None of these incomplete attempts was counted as a passing process check. Killed
instrumentation is the victim, not evidence of subsequent startup success.

```powershell
& android/tools/build.ps1 -BuildJdk D:/programThisPc/AndroidStudio/jbr -AndroidSdk C:/Users/admin/AppData/Local/Android/Sdk -ReadOnlyDependencyCache C:/Users/admin/.gradle/caches -Tasks ':app:assembleDebug',':app:assembleDebugAndroidTest','--offline'
# Install both current APKs only on the verified owned read-only emulator.
adb -s emulator-5556 shell am instrument -w -r -e class org.kiosk.harness.StoreTest,org.kiosk.harness.StoredCoordinatorTest,org.kiosk.harness.EngineTest,org.kiosk.harness.LifecycleTest org.kiosk.harness.debug.test/org.kiosk.harness.HarnessTestRunner
# Fresh private-data entry, never an asset fixture Intent:
adb -s emulator-5556 shell am start -W -n org.kiosk.harness.debug/org.kiosk.harness.StoredHarnessActivity
adb -s emulator-5556 exec-out run-as org.kiosk.harness.debug cat files/fixture-publications/display-state.json
```

Full bounded external scenario and commands are copied into the evidence directory;
its explicit native controls/fault hooks are in test APK only. Production store hooks
are inert injected callbacks with no Intent/page/runtime setting. Native state buttons
are development fixture actions, not server publication authorization. Existing build
versions remain unchanged. Own Medium_Phone read-only emulator-5556, Android17/API37/
x86_64 and WebView145.0.7632.218 were used; no network/settings isolation was changed.
App has no INTERNET permission and the origin never falls back, so rendering required
no server/network even though emulator system network icons remain present. Screenshots
of A, B ONE/TWO and the corrupt-private safe state were actually viewed.
Owned launcher26476/QEMU18412 were stopped with executable/parent/AVD/port/read-only guards,
no snapshot saved. Physical Android/TV, arbitrary-source trust/image admission, hostile
filesystem race safety, full product capacity, GPU/process recovery beyond this scoped
restart, OS reboot and power-loss durability remain separate gates. Stage4 is incomplete.
Next step: PC1 review this complete fixed-fixture private-publication slice and evidence;
no delivery/network, production decoder or broader activation API is inferred.

### Non-activating Events-v1 structural/integrity core

API: [EventsPackage.inspect](app/src/main/java/org/kiosk/harness/packagecore/EventsPackage.java)
accepts the existing logical `LocalView.Source` interface (finite names + streams),
not an archive, directory importer or URL. It returns `StructuralIntegrityReport`
with revision/fileCount and an immutable `unchecked` set containing IMAGE_VALIDATION,
ANDROID_DECODER_PARITY, FILESYSTEM_SAFETY, SOURCE_TRUST and ACTIVATION_READINESS.
There is no activation-ready result or display/catalog/store connection. A successful
report proves structural/integrity checks of the inspected bytes only. No image validator
is installed, stubbed or treated as successful admission. A correctly hashed corrupt
image deliberately passes this restricted API with IMAGE_VALIDATION still unchecked.

| Module | Responsibility |
| --- | --- |
| [PackageJson](app/src/main/java/org/kiosk/harness/packagecore/PackageJson.java), [PackageSchema](app/src/main/java/org/kiosk/harness/packagecore/PackageSchema.java) | JSON token semantics; manifest/revision; exact public Events/Tags/settings fields, integer types, tag links and content_version |
| [PackageInventory](app/src/main/java/org/kiosk/harness/packagecore/PackageInventory.java), [PackageCaseFold](app/src/main/java/org/kiosk/harness/packagecore/PackageCaseFold.java) | Portable package paths and full casefold duplicates; inventory/tree, bounded streams, sizes/SHA256, reread resource bytes and overflow-safe totals |
| [PackageResources](app/src/main/java/org/kiosk/harness/packagecore/PackageResources.java) | Structural media/resource closure, translations and existing CSS/JS/template dependency checks |
| [PackageFailure](app/src/main/java/org/kiosk/harness/packagecore/PackageFailure.java) | Stable code-only exceptions; original cause and suppressed stream-close failures discarded |

This is the package `manifest.json` layer, separate from prepared-view `view.json`.
It preserves the exact tuple(1,events,events-v1,1), entrypoint `["data/events.json"]`,
Python manifest/entry unknown-property tolerance, and the exact public schema.
Boolean/float values never become integer IDs/sizes/versions. Manifest validation precedes
compatibility as in Python: invalid schema/renderer yields `invalid_package`; unsupported
kind/resource_contract yields `unsupported_client_contract`. Both tuple and entrypoints
are refused before file enumeration/data/media reads. No additional first-error ordering
is specified when defects coexist.

Bounds remain manifest2MiB,1..10000 entries,256MiB/file and64MiB inventory sum,
with256KiB streaming blocks. Declared totals are checked before payload reads; arithmetic
uses subtraction against the remaining allowance. Data/resources are buffered after a
streaming integrity pass and reread against the declared size/hash. Media are hashed
without buffering or decoding. A streaming source has no trusted fstat metadata, so
metadata-specific Python `file_too_large`, inode/mtime `source_changed`, symlink/reparse
and tree-race checks are not claimed. Excess/short stream bytes cause `integrity_failure`;
changed resource rereads cause `source_changed`. The future filesystem adapter must
establish equivalent safe ownership, metadata and TOCTOU guarantees before package admission.

The13 legacy resources must close exactly with public JSON and referenced media.
Translations must be string dictionaries; dependency regex checks follow the current
Python verifier (including matching dependencies in comments), not a general script-safety
analysis. Package-supplied code is never executed. Pillow validation of both referenced
media and the legacy site icon is explicitly outside this core.

Evidence: [logs/pc2-package-core-20261031-183949](../logs/pc2-package-core-20261031-183949/).
`case-comparison.json` compares all9 PC1 cases with actual JVM and Android core results;
PC1 `results.json` remains its oracle, never relabeled as a PC2 run.

| Check | Actual result |
| --- | --- |
| New JVM core tests | PASS6/6 in0.467s; `jvm-results.xml` |
| Android parser/core tests | PASS3/3 in1.951s; `android-parser-verified.txt`, `android-core-logcat.txt` |
| Nine cases | PASS9/9 on JVM and emulator as structural/integrity parity; valid/empty → structural_integrity_ok, images/platform unchecked |
| Targeted negatives | Tuple/types/early refusal, revision, entrypoints, portable/full-casefold paths, count/size/total/hash/tree, public fields/tag references/media/resources, safe I/O/close failures |
| JSON/Unicode target probes | Exact integer tokens incl128-digit IDs,4300-digit boundary, floats/bools, duplicate-key last wins, UTF8/16/32 with/without BOM, surrogatepass, invalid syntax/bytes, unknown-property tolerance |
| Build | PASS incremental offline JVM/debug/test APK build, unchanged toolchain/dependencies; no clean rebuild |
| UI/runtime/lifecycle suites | SKIPPED: source and assets unchanged, new core is disconnected |

The initial Android CSS-vector FAIL is preserved in `android-parser.txt`; subsequent
correction and final PASS are separate logs. Original Java regex diagnostic matches
dotless-I on JVM but not Android; explicit character sets now preserve Python behavior.
[prepare-package-test-assets.py](tools/prepare-package-test-assets.py) copies nine original
cases unchanged into **test APK assets only** and verifies archive/byte identity.
[generate-package-casefold.py](tools/generate-package-casefold.py) pins Python Unicode16.0.0;
test assets also have byte-preserving Git attributes. Production fixtures/catalog and all
shared renderer assets remain unchanged.

```powershell
python android/tools/prepare-package-test-assets.py
python android/tools/generate-package-casefold.py
& android/tools/build.ps1 -BuildJdk D:/programThisPc/AndroidStudio/jbr -AndroidSdk C:/Users/admin/AppData/Local/Android/Sdk -ReadOnlyDependencyCache C:/Users/admin/.gradle/caches -Tasks ':app:testDebugUnitTest','--tests','org.kiosk.harness.packagecore.EventsPackageTest',':app:assembleDebug',':app:assembleDebugAndroidTest','--offline'
# Install both debug APKs on the verified owned serial, then:
adb -s emulator-5556 shell am instrument -w -r -e class org.kiosk.harness.packagecore.PackageParserTest org.kiosk.harness.debug.test/org.kiosk.harness.HarnessTestRunner
```

Target: read-only Medium_Phone, Android17/API37/x86_64, WebView145.0.7632.218;
these core tests do not instantiate WebView or exercise images/GPU. The next bounded
step is to specify image-validation/decoder parity vectors and the safe source-adapter
requirements with PC1 before any full admission API, storage or activation. Physical
gates and stage4 remain incomplete; no store/network/pairing/update implementation.

### Image verification and safe source adapter ? proposal for PC1 review

**Status:** design only; no production implementation, decoder execution or new admission
claim. The implemented `EventsPackage.inspect` still returns structural/integrity evidence
with all five `unchecked` requirements. Nothing below clears them, feeds display/catalog,
or authorizes storage/activation. Review PC1 decisions before implementing the next slice.

The baseline is [Events-v1 edition1](../contracts/events-v1/README.md),
[exporter verification](../kiosk/publication/exporter.py) (`_plain_path`, `_stream_stable`,
`verify_package`, `_validate_image_path`, `_check_resources`) and the existing core above.
[Image generation](../kiosk/core/images.py) produces progressive JPEG event variants
and RGBA PNG icons; upload validation has additional load/pixel checks which must not
be mistaken for the package verifier's Pillow `verify()` behavior.

| Existing Windows/Python guarantee | Android limitation / current gap | Proposed solution, pending PC1 | Future verification |
| --- | --- | --- | --- |
| Referenced media and resource site icon pass Pillow open/verify; selected exceptions become invalid_image | No Pillow-equivalent guarantee in core; decoder acceptance and WebView display are different observations | Separate image evidence from structural report; compare identical bytes on all three engines; retain mismatch as unresolved admission gate | Per-vector Pillow, Android decoder and WebView columns, versions and byte hashes |
| No extension allowlist in package image verification; content is inspected | Extension or MIME-only checks could silently tighten or weaken acceptance | Sniff content for diagnostics, never substitute suffix approval for verification; review unsupported formats explicitly | Valid content with wrong/missing suffix; image suffix with non-image bytes |
| Pillow decompression-bomb policy applies; verify is not a full pixel-load proof | Encoded 64MiB package bound does not bound decoded pixels, frames or peak memory | Propose explicit per-image dimensions/pixels, cumulative decoded-byte and concurrent-decode budgets; values require measurement and PC1 approval | Boundary dimensions, checked multiplication, many small images, animation and bounded worker/resource exhaustion |
| Root/ancestors and each component reject symlinks/reparse points; leaf must be regular | Logical Source has no filesystem metadata or race-resistant traversal | Initially restrict any future adapter to an owned private root; reject links/special files and refuse operation when no race-resistant traversal proof exists | Root/ancestor/intermediate/leaf links, dangling links, FIFO/device/directory leaves and concurrent replacement |
| File-set equality; traversal rejects links even outside referenced files | A files() set can hide duplicate names or tree changes | Validate raw enumeration before set conversion, portable/full-casefold uniqueness and exact file inventory; inspect all tree entries | Extra/missing file, linked directory, duplicate aliases, mutation during enumeration |
| lstat/fstat compares dev/inode/size/mtime_ns before/after stream and final pathname; resource reread witness equality | Canonical paths and equal hashes alone do not prove pathname stability; Android metadata resolution/API differs | Handle-relative no-follow traversal and metadata witness where demonstrable; otherwise refuse arbitrary mutable directory sources | Swap between check/open, same-size rewrite, rename/unlink, parent replacement and coarse timestamp cases |
| Size/SHA256 checks, bounded blocks and package limits | Closing/rereading or decoding a path can introduce new bytes | Keep an inspection-scoped verified-byte session; image checks use captured bytes or a sealed private snapshot, never unchecked source reopen | Replace source after verification; every consumer must see original verified bytes or fail |
| Integrity witnesses do not establish authenticity or eliminate all hostile concurrent writes | Private storage and a hash are not source trust | Document exclusive-writer assumption and retain SOURCE_TRUST and FILESYSTEM_SAFETY gates until independently proven | Untrusted writer simulation; no full admission result on incomplete evidence |

#### Planned synthetic image-parity vectors (not run)

Generate deterministic, non-private inputs in a disposable test workspace, with generator
version/seed, encoded SHA256, dimensions, frame count and package role recorded. Keep
original nine oracle fixtures unchanged. Exercise each image in referenced event media,
settings site_icon and `resources/static/img/site_icon.png` as applicable; update inventory
hashes for deliberate image defects so integrity rejection does not mask image behavior.

| Vector family | Required cases / observations |
| --- | --- |
| Current generated formats | Progressive RGB JPEG at kiosk 1400x900, TV 1920x1080 and thumb 420x260 bounds; smaller/aspect-ratio variants; RGBA PNG icon up to 256x256 including transparency; baseline/sequential JPEG and PNG palette/gray as comparison cases |
| Wider decoder surface | Small GIF (including animation), WebP and other formats accepted by the pinned reference Pillow build: exploratory cases, not a new supported-format list; record first-frame versus all-frame behavior |
| Corruption and truncation | Empty/random payload; bad signature/header/chunk/checksum; truncation at header, scan/body and trailer; malformed dimensions and trailing data; record verify versus actual decode differences |
| Suffix mismatch | Valid JPEG named .png, PNG named .jpg, no suffix; invalid payload named .jpg; do not invent an extension rejection absent in Python |
| Resource pressure | Zero/huge dimensions, extreme aspect ratio, dimension-product overflow, highly compressed large image, many frames/images, budget boundary -1/equal/+1 and cancelled decode; bounded generated headers/streams rather than huge allocations |
| Presentation | Orientation metadata, transparency, color modes/profiles and visible content/fit; successful decoding alone does not prove correct display |

For **each vector** retain three independent outcomes: (1) pinned PC1 Python/Pillow
open/verify result, exception/warning and effective bomb threshold/warning filters;
(2) exact Android build/API/ABI, decoder path/version, bounds result, full decode result,
allocation/peak observations and cancellation; (3) exact WebView provider/version,
local-origin load/error, natural dimensions and screenshot/visual observation. Add runtime,
source hash, encoded bytes and explicit PASS/FAIL/SKIPPED for each column. Full Pillow
load may be an additional diagnostic, never relabel it as verifier behavior. Pillow bomb
warnings and errors are distinct: the exporter catches DecompressionBombError, not an
explicit warning; do not silently convert the reference policy. No measurements exist
for this proposed corpus yet. Phone-emulator observations cannot establish Android TV
or physical memory/display acceptance. No physical devices are currently available.

#### Proposed source-adapter contract (not implemented)

1. **Root and authority.** A caller supplies one owned, app-private, inspection-scoped
   root selected by native code, never an Intent, page, arbitrary URI or shared/external
   directory. No network, content-provider or archive extraction adapter in this slice.
   Reject symlink roots/ancestors/components and non-regular leaves. A canonical-prefix
   check is diagnostic only, not a race-proof authorization mechanism. Hard-link aliases
   or concurrent external writers must be excluded by ownership/proven isolation, or
   refused; this proposed restriction exceeds Python's explicit symlink checks and
   requires review. APK assets remain the existing harness source, not proof for a
   filesystem adapter.
2. **Names and tree.** Reuse existing portable paths/full Unicode casefold rules without
   normalization, URL decoding or case rewriting. Validate raw entries before creating
   a set. Enumerate all entries without following links and require exactly manifest
   plus inventory files; empty directories are not extra files in Python, but links in
   any directory still fail. Bound traversal depth/entry work as a reviewed Android
   safety restriction, not an invented common-contract quota. Unsupported tuple must
   still fail before data/media enumeration or reads.
3. **Stream ownership.** Each open returns a fresh bounded stream owned by one inspector;
   try-with-resources closes it on success, validation/I/O error and cancellation.
   Session owns any root/file handles and temporary captured bytes, closes them after
   all consumers finish, and exposes no raw filesystem path. Failed open transfers no
   ownership. Close failures cause safe refusal without private paths or exception
   causes; do not mask an existing stable failure with arbitrary diagnostic text.
4. **Budgets.** Preserve manifest2MiB, 10,000 inventory files, individual256MiB,
   payload sum64MiB and 256KiB streaming blocks, with subtraction/checked arithmetic.
   Enforce actual bytes as well as declarations and reject no-progress streams.
   Manifest is separate from payload sum. Proposed image/heap/time/traversal budgets
   must be explicit and measured; no claim that all otherwise valid 64MiB packages fit
   Android heap. Cap buffered resources and concurrent work or refuse safely; additional
   caps require PC1 review because they may reject Python-valid input.
5. **Mutation and lifetime.** Establish handle identity/type/size metadata before/after
   reads and compare final entry identity where possible, in addition to exact length
   and SHA256. Detect changed enumeration and rereads. Same-size writes and rename
   races are not solved by mtime alone. Do not claim the Python witness eliminates all
   adversarial races either. If exclusive ownership/race-resistant opens cannot be
   established, support only immutable build assets for now and refuse mutable roots.
6. **Verified-byte binding.** Propose bounded capture into an inspection-private snapshot
   or immutable byte buffers; hash the captured bytes, then decode those same bytes.
   Snapshot creation is a future adapter mechanism, not a publication store proposal.
   Root pathname or a still-writable open descriptor is not an immutable byte token.
   Later consumers would require a scoped opaque handle bound to manifest/inventory
   digest and byte lifetime, or re-verification of every byte; neither is wired to
   display/activation. Cancellation/failure destroys temporary captures and returns no
   successful image/filesystem evidence. Decoder/platform success never clears source
   trust or activation readiness.

#### Future tests, refusal policy and review decisions

Use deterministic barriers in a disposable owned tree for replacement between enumeration,
metadata check, open, read and reread; include root/intermediate swap, link insertion,
unlink with open handle, same-length overwrite, truncation/growth and changed final path.
Assert exact inventory and that no out-of-root sentinel is read. Test unsupported tuple
with a source that throws on any data/media access. Count opens/closes on every failure,
zero-progress/short reads, injected read/close errors, cancellation and session disposal;
no leaked handles, partial successful evidence, raw path or payload in public errors.
Test snapshot substitution/retained writable handle and consumer use after session close.
Use bounded streams for huge declarations and arithmetic limits. Isolated defects get
exact stable error assertions; combined defects need only a permitted safe refusal,
without establishing a new global first-error order.

Proposed refusal categories distinguish invalid image, unsupported decoder/format,
budget exceeded, unsafe source, source changed and I/O failure. Existing core codes stay
unchanged; public adapter/image code names and their mapping to Python require PC1 review.
Timeout/cancellation or allocation/decode failure produces incomplete evidence, never an
admission success. A UI-thread Handler is not protection from blocked native decode;
choose bounded worker execution and isolation/cancellation policy before hostile-image
experiments. Do not deliberately trigger process OOM on an ordinary target. No automatic
retry loop or fallback to unchecked bytes/another path is permitted.

**Open decisions for PC1:** reference Pillow/version/plugins and warning configuration;
image format scope and mismatch policy; decoder API/toolchain and attainable memory/time
bounds; numeric pixel/frame/aggregate budgets; raw-tree traversal caps; demonstrable
Android no-follow/handle metadata facilities on the selected minimum API; private-root
writer threat model, hard-link restriction and snapshot lifetime; safe error vocabulary.
Platform API choices require official documentation review before implementation; this
design does not claim an untested Android API provides Windows-equivalent safety.

Next bounded step after PC1 review: a test-only corpus/three-column runner and isolated
source-adapter race prototype, separately authorized before production changes. Current
structural report, APK harness and earlier evidence remain unchanged. Store, activation,
network, pairing, updates, physical gates and stage4 completion are outside this design.

### Attached-window image visual check ? 2026-10-31

The separate **test-only** [visualtest module](visualtest/build.gradle) owns
[VisualHostActivity](visualtest/src/main/java/org/kiosk/harness/visualtest/VisualHostActivity.java)
and [three new screen tests](visualtest/src/androidTest/java/org/kiosk/harness/visualtest/AttachedImageVisualTest.java).
Its applicationId is `org.kiosk.harness.visualtest`, with a non-exported Activity and no
INTERNET/device permissions. It is not a dependency of :app; host Activity, synthetic
page and test assets are confined to its APKs. Main harness APK remains byte-identical
SHA256 `285474a8665bcccbdd5a0e392e2f8245dbcaf858fe88cec7841b9a0a01c06a94`.
Production display/catalog, packagecore, renderer and ImageParityTest are unchanged.

```powershell
& android/tools/build.ps1 -BuildJdk D:/programThisPc/AndroidStudio/jbr -AndroidSdk C:/Users/admin/AppData/Local/Android/Sdk -ReadOnlyDependencyCache C:/Users/admin/.gradle/caches -Tasks ':visualtest:assembleDebug',':visualtest:assembleDebugAndroidTest','--offline'
# Verify the owned read-only emulator serial before installing only these two APKs:
adb -s emulator-5556 install -r android/visualtest/build/outputs/apk/debug/visualtest-debug.apk
adb -s emulator-5556 install -r android/visualtest/build/outputs/apk/androidTest/debug/visualtest-debug-androidTest.apk
adb -s emulator-5556 shell am instrument -w -r -e class org.kiosk.harness.visualtest.AttachedImageVisualTest org.kiosk.harness.visualtest.test/android.test.InstrumentationTestRunner
# Extract NAME=rgb, rgba, jpeg artifacts using exec-out and binary-safe host file writes:
adb -s emulator-5556 exec-out run-as org.kiosk.harness.visualtest cat files/NAME-screen.png
adb -s emulator-5556 exec-out run-as org.kiosk.harness.visualtest cat files/NAME-results.json
```

Each test verifies its selected corpus SHA256, attaches a VISIBLE WebView to the
Activity/window, waits for img load, then
[postVisualStateCallback](https://developer.android.com/reference/android/webkit/WebView#postVisualStateCallback(long,%20android.webkit.WebView.VisualStateCallback)),
an actual subsequent onDraw/frame and foreground focus. This follows the documented
attached/visible conditions for the first visual frame. Real whole-display
[UiAutomation.takeScreenshot](https://developer.android.com/reference/android/app/UiAutomation#takeScreenshot())
provides screenshot pixels, not WebView.draw or DOM-only evidence. Waits are bounded:
load10s, JS3s, visual5s, subsequent draw5s, focus5s; external instrumentation180s.
These waits do not guarantee interruption of a blocked UI/native engine. A finally
block recycles the screenshot and performs UI-thread idempotent detach -> destroy;
there are no WebView calls after destroy. No system settings/rotation are changed.

Only the exact synthetic index and image GETs are served on `https://visual-test.invalid`;
other requests return403, network/file/content access and arbitrary navigation/windows
are blocked, with no bridge/fallback. MIME is image/png or image/jpeg here. This is
synthetic visual test plumbing, not production resource serving or admission policy.

Background is sRGB (32,64,96). All images start at CSS (24,80). Observed DPR2.625,
WebView screen origin(0,0), screen1080x2400, screenshot sRGB IEC61966-2.1. DOM rectangle,
view geometry and screenshot regions are recorded independently in each JSON:

| Input | Natural size -> CSS display | Screen rectangle x,y,w,h | Pixel/visible check |
| --- | --- | --- | --- |
| progressive.jpg | 1400x875 -> 280x175 (0.2x) | 63,210,735,459.375 | PASS: visible colorful repeating gradient/grid; 96/96 grid samples non-background and96 distinct colors; no bit equality requirement |
| generated-3x2-rgb.png | 3x2 -> 96x64 (32 CSS px/source pixel) | 63,210,252,168 | PASS all6 source-cell centers plus background, 3x3 screen-pixel regions; max channel error0 |
| generated-7x5-rgba.png | 7x5 -> 168x120 (24 CSS px/source pixel) | 63,210,441,315 | PASS all35 cell centers plus background; transparent and partial-alpha regions; max channel error1 |

PNG CSS uses image-rendering:pixelated; sample points are far from tile edges. Generator
source pixel is (31*x mod256,47*y mod256,123), alpha=(x+y)*63 mod256 for RGBA.
Expected per-channel sRGB source-over is round((source*alpha + background*(255-alpha))/255).
Tolerance is +/-3 channel units to accommodate integer premultiplication/compositor
rounding, not arbitrary color drift. Each9-pixel patch must meet it. RGBA(0,0), alpha0,
expected/observed(32,64,96); RGBA(1,1), alpha126, expected(32,56,109), observed(31,55,110);
RGBA(2,2), alpha252, expected(62,94,123), observed(61,94,123). Full patches and centers
are retained. Fractional JPEG height and platform filtering preclude edge/bit assertions.

Evidence: `logs/pc2-image-visual-20261031-192854/`: original `jpeg-screen.png`, `rgb-screen.png`,
`rgba-screen.png`, per-image results, `visual-review.md`, build/instrumentation/ADB logs,
source/APK identities and owned-emulator cleanup proof. All three original screenshots
were actually opened and visually inspected: complete colorful JPEG rectangle, six
RGB blocks, and RGBA tiles blending into the known background, including invisible
fully transparent top-left tile; no broken-image placeholder or clipping observed.
PASS3/3 new tests in9.624s and the affected test-host build. No repeat of the previous
21 measurements, JVM/core/UI/runtime/lifecycle suites or clean builds.

Target remains Medium_Phone read-only emulator-5556, Android17/API37/x86_64,
WebView145.0.7632.218; full fingerprint in evidence. Owned launcher20616/QEMU22116
were stopped with PID/parent/executable/AVD/port/no-snapshot checks, no snapshot saved.
Screenshots establish this emulator's composited output only: no physical color
calibration, ICC/HDR/wide-gamut parity, scaling-edge quality or exhaustive image fidelity.
Physical Android/TV, production decoder/image admission and stage4 remain incomplete.
Next step is PC1 review of screenshots and bounded pixel evidence before any new scope.

### Complete image corpus and three-engine measurements ? 2026-10-31

This supersedes the earlier partial-corpus blocker below. PC1 supplied a synthetic
progressive JPEG and a separately measured Pillow oracle. JPEG SHA256 is
`91073b508d9fd564ab2967383e193b9bf59cf82a7c0cfdda5bcc568c72f2580c`.
The ready [manifest](testdata/image-corpus/manifest.json) and all **21 vectors** match
PC1 complete/ byte-for-byte. Small pinned sources, [provenance](testdata/image-sources/provenance.json),
[jpeg identity](testdata/image-sources/jpeg-identity.json) and unchanged
[PC1 Pillow13.0.0 oracle](testdata/image-sources/pillow-oracle.json) live in Android testdata.
Generation no longer reads ignored logs; manifest retains its historical PNG provenance
label. Two independent full runs from different cwd locations matched the ready corpus.

```powershell
python android/tools/generate-image-corpus.py --output NEW_OUTPUT_DIRECTORY --jpeg-source android/testdata/image-sources/pc1-progressive.jpg --jpeg-sha256 91073b508d9fd564ab2967383e193b9bf59cf82a7c0cfdda5bcc568c72f2580c
python android/tools/test-image-corpus.py
# Incremental offline build with the existing documented toolchain:
& android/tools/build.ps1 -BuildJdk D:/programThisPc/AndroidStudio/jbr -AndroidSdk C:/Users/admin/AppData/Local/Android/Sdk -ReadOnlyDependencyCache C:/Users/admin/.gradle/caches -Tasks ':app:assembleDebug',':app:assembleDebugAndroidTest','--offline'
# After installing both debug APKs on the verified owned serial:
adb -s emulator-5556 shell am instrument -w -r -e class org.kiosk.harness.ImageParityTest org.kiosk.harness.debug.test/org.kiosk.harness.HarnessTestRunner
adb -s emulator-5556 exec-out run-as org.kiosk.harness.debug cat files/image-parity-results.json
```

[Test-only runner](app/src/androidTest/java/org/kiosk/harness/ImageParityTest.java)
checks manifest/oracle ID+SHA256 association and performs independent bounds and full
`BitmapFactory.decodeByteArray` calls on the same bytes (`inScaled=false`, no sampling).
Bounds mode intentionally returns no bitmap; dimensions are evidence of header parsing,
not successful full decode. Full results record null/exception or bitmap dimensions and
allocation; bitmaps are recycled. These APIs were selected for observation after checking
[official bounds documentation](https://developer.android.com/reference/android/graphics/BitmapFactory.Options#inJustDecodeBounds)
and [BitmapFactory](https://developer.android.com/reference/android/graphics/BitmapFactory).
Neither call implements Pillow verification or selects a production decoder.

Each vector also gets a fresh unattached WebView, a synthetic test page and exact local
`https://image-test.invalid` resources. The common renderer is untouched. The
[official interception API](https://developer.android.com/reference/android/webkit/WebViewClient#shouldInterceptRequest(android.webkit.WebView,%20android.webkit.WebResourceRequest))
runs off the UI thread: immutable bytes are returned for exact GET index/image URLs,
all other requests receive403; no null/network fallback. File/content/network loads,
arbitrary navigation and windows are blocked; no bridge and no INTERNET permission.
All image responses deliberately use neutral application/octet-stream to observe content
sniffing including wrong/absent suffixes; this is not production MIME policy. Fixed
load/error listeners record natural dimensions; UI-thread evaluateJavascript polls only
the test observation. No onPageFinished-only success. UI-thread finally detaches if
needed and destroys, with no later WebView call. Observation deadline8s/vector plus
2s JS wait and external240s test limit are not protection against blocked UI/native decode.
No screenshots/pixel correctness, malicious pressure or full image-admission claim.

Evidence: `logs/pc2-image-parity-20261031-192039/`, especially `image-parity-results.json`, `api-decision.md`,
`pc1-comparison.json`, `adb-commands.json`, `source-identities.json` and APK copies/hashes.
PASS: 3 generator-tool tests; 21+manifest PC1 byte comparison and repeated full generation;
incremental debug/test APK build; 1 instrumentation test measuring all21, in15.145s.
Initial Java BOM compilation failure and sandbox SDK-access failure are retained;
BOM removed and build rerun with permitted SDK access. No production source changed.
Target: owned read-only Medium_Phone, Android17/API37/x86_64,
`google/sdk_gphone64_x86_64/emu64xa:17/CE2A.260420.051.A2/16418371:user/release-keys`,
WebView `com.google.android.webview/145.0.7632.218`. Guarded owned emulator shutdown
completed without snapshot save or settings changes.

**Measured mismatch:** `png-truncated-idat-png` and `png-truncated-before-iend-png`
are invalid_image in PC1 Pillow but have available bounds, decoded bitmap and WebView
load3x2 here. Thus Android/WebView acceptance cannot substitute for Pillow. Two truncated
JPEG vectors (scan-data and before-EOI) are accepted by all three probes; this is the
actual oracle, not an assumed rejection. Wrong/absent JPEG suffixes decode/load1400x875.
All other cases have aligned coarse accept/reject observations on this target; this is
not proof of equivalence or correct pixels. All21 rows include input hash, unchanged
PC1 result, Android bounds/full dimensions and WebView load/error/natural dimensions.
Pillow is PC1 execution only. No production image validation, filesystem adapter,
activation/store, decoder parity gate closure or physical/TV acceptance follows.
Existing core unchecked flags and stage4 remain unchanged. Next step: PC1 review of
these measured mismatches and explicit policy for a future bounded experiment.

### Earlier partial image corpus generator ? 2026-10-31 (superseded)

[Generator](tools/generate-image-corpus.py) and its
[standard-library checks](tools/test-image-corpus.py) do not import Pillow or decode
images. Output is a new explicitly named directory containing `manifest.json` and
`vectors/`; existing outputs (including symlinks) are refused. Script-relative fixture
lookup works from any cwd; relative output/JPEG arguments are relative to caller cwd.
No absolute source paths or timestamps enter the manifest. The generated PNG stream
uses explicit stored DEFLATE blocks, CRC32 and Adler32 rather than compressor-dependent
output. Each vector records stable ID, derivation, source identity, SHA256, byte count,
purpose, known parameters and three `not_measured` decoder columns.

```powershell
# Explicit partial run, while the existing progressive JPEG source is unavailable:
python android/tools/generate-image-corpus.py --output logs/image-corpus-new --png-only
python android/tools/test-image-corpus.py
# Full run AFTER PC1 supplies an existing synthetic progressive JPEG and independent hash:
python android/tools/generate-image-corpus.py --output logs/image-corpus-full-new --jpeg-source PATH_TO_EXISTING_JPEG --jpeg-sha256 PC1_SHA256
```

The pinned existing PC1 card PNG is copied byte-for-byte from the original contract
fixture (SHA256 `4b02621a1639a302da7e368db30b5b96f931f6be98b1154b2e0d787986227a46`).
Four small RGB/RGBA PNGs use deterministic formula pixels (1x1, 3x2, 2x3 and 7x5),
including zero/partial alpha. Separate vectors contain an IHDR CRC-only defect,
prefix truncations at named signature/IHDR/IDAT/pre-IEND offsets, trailing bytes,
empty input and plain text with a PNG suffix. There are 13 PNG/non-image vectors.
The ready partial corpus is [android/testdata/image-corpus](testdata/image-corpus/manifest.json);
its manifest is generated output and matches both independent logged runs. It is test-only
and is not included in APK assets or connected to packagecore/display/catalog.
These construction labels are not decoder acceptance predictions.

The full mode additionally copies the supplied progressive JPEG unchanged under .jpg,
wrong .png and extensionless names; adds separate prefix truncations at SOI,
scan-header, scan-data and pre-EOI boundaries plus trailing data. It checks the supplied
SHA256, SOF2 dimensions/first SOS marker boundaries, SOI/EOI and small test-input caps
(2MiB, each dimension <=2048). These caps constrain this generator experiment only,
not package admission or production decoder policy. Marker inspection is not image
validation. No JPEG is generated or recompressed by this tool.

Evidence: `logs/pc2-image-corpus-20261031-191553/`. Two independent PNG-only runs from
different cwd locations matched every byte and manifest; three tool tests passed.
The nine original oracle fixtures remained byte-identical. No Android build/emulator,
Pillow, decoder, WebView, resource-pressure or unchanged regression tests were run.

**Historical blocker (resolved above):** no existing progressive JPEG was found in the provided fixtures
or local synthetic test materials; JPEG cases remain `pending_source`, not complete.
PC1 must supply that synthetic source and independent SHA256 before the full corpus
can be generated. Do not treat marker-only unit-test data as a JPEG image vector.
For handoff, send the corpus directory with its manifest and corpus-identities.json;
PC1 verifies hashes and measures the pinned bytes using project .venv Pillow13.0.0,
recording actual verify/warnings/errors separately from any optional full load.
Return a separate oracle keyed by vector ID/hash and environment; never overwrite
manifest measurements with guessed expectations. Android decoder and WebView measurement
runners remain a later authorized task. Production core/display/catalog are unchanged;
physical gates and stage4 remain open. Await PC1 oracle/next task before implementation.

### Package adapter differences and display boundary

Package-core adaptation boundary (selected separately on2026-10-31): logical streams,
not a filesystem adapter, are inspected without activation. The package parser uses
Python-style arbitrary-size integer tokens, last-key-wins objects, BOM/UTF encodings,
and Python casefold data rather than Android org.json coercion. The existing view JSON
helper has different semantics and remains unchanged. The implemented Android-only
JSON container depth128 refuses deeper documents with `invalid_package`; Python's
interpreter recursion bound differs. Integer-token digits are bounded4300, matching the
checked Python3.14 default, not a claim about every configurable Python installation.
Casefold data is pinned to Python Unicode16.0.0 and generated reproducibly; equivalence
to a different reference Unicode version requires its own comparison. This adapter restriction is documented,
not a change to Events-v1. Filesystem metadata/symlink/TOCTOU equivalence is not claimed:
stream size/hash are checked, and buffered resources are reread for consistent bytes.
Pillow/Android decoder validation and source trust remain mandatory separate gates.
Target tests exposed different Unicode-case behavior between Java/Android regex engines
for CSS `@import` (including dotted/dotless I). The adapter spells out Python's matching
characters and whitespace instead of relying on platform Unicode-case flags; this preserves
the existing refusal rule rather than proposing a different resource policy.

One Activity displays one build-delivered, independently preflighted view. Select only
`valid-kiosk`, `valid-tv`, `empty-kiosk`, `empty-tv`, `two-card-tv`, `two-card-kiosk`
with the `fixture` intent extra;
default is `valid-kiosk`. Other values enter a native safe error state. There is no
package ingestion, publication store/pointer/receipt, live switch, automatic fallback,
pairing, server, download/import, replication, updater, lockdown or product installer.
Activity recreation starts fresh validation of the same catalog selection, never URL
history. Failure does not automatically relaunch the Activity or renderer.

| Files | Responsibility |
| --- | --- |
| [app/build.gradle](app/build.gradle), [settings.gradle](settings.gradle), [Wrapper properties](gradle/wrapper/gradle-wrapper.properties) | Pinned experimental build, SDK selection and checked distribution checksum |
| [core/LocalView.java](app/src/main/java/org/kiosk/harness/core/LocalView.java), [JsonSyntax.java](app/src/main/java/org/kiosk/harness/core/JsonSyntax.java) | Descriptor bounds, exact inventory, sizes/hashes, pinned JS/CSS and expected package/mode before engine creation |
| [OriginPolicy.java](app/src/main/java/org/kiosk/harness/core/OriginPolicy.java), [AssetViewSource.java](app/src/main/java/org/kiosk/harness/AssetViewSource.java) | Pure request policy and Android APK asset adapter |
| [FixtureCatalog.java](app/src/main/java/org/kiosk/harness/FixtureCatalog.java), [bundled views](app/src/main/assets/views/) | Build-owned expected identities/pins, separate from candidate descriptors; unchanged PC1 view bytes |
| [PreparedWebView.java](app/src/main/java/org/kiosk/harness/PreparedWebView.java), [HarnessActivity.java](app/src/main/java/org/kiosk/harness/HarnessActivity.java) | Restricted WebView, generation-bound readiness, 15s native / 20s startup watchdog, native failure message |
| [LocalViewTest.java](app/src/test/java/org/kiosk/harness/LocalViewTest.java), [EngineTest.java](app/src/androidTest/java/org/kiosk/harness/EngineTest.java), [LifecycleTest.java](app/src/androidTest/java/org/kiosk/harness/LifecycleTest.java) | JVM validation/policy, real Android WebView regression and lifecycle fault injection |
| [check-fixtures.py](tools/check-fixtures.py), [build.ps1](tools/build.ps1) | Provenance checks and process-local build setup; no machine configuration changes |

The PC1 ZIP SHA256 is
`ad1bc48b8c68edb78b1a9c0b147002848d2e24a04745f66703a1ed34a11f8aa5`.
All 163 ZIP entries passed CRC and exact comparison with supplied extracted files.
The initial four prepared views and the two runtime views described below are bundled;
no ZIP extraction or package generation occurs
on Android. JS/CSS match the Git HEAD blobs byte-for-byte (JS
`9dbea16811df97b75c2b3e4db25fd468bf9de4a9d2f9fc1b6b3740f4b4ce53fc`, CSS
`8662399cc92650fb31434a92240a7dda50f013d6be002de5c5d97d7d746ab37c`).
Shared working-tree sources have CRLF while Git/PC1 assets have LF; no shared source
was rewritten. Android `.gitattributes` preserves the delivered asset bytes. Expected
package identities in the catalog were cross-checked against canonical PC1 valid/empty
manifests; Android does not execute the package verifier. PC1 `expected.json` and
`results.json` remain PC1's nine-case evidence, not nine Python runs on PC2.

### Selected build tuple and reproduction

The actual experiment uses Java source/bytecode 17, AGP **9.4.1**, Gradle **9.6.0**,
compileSdk/targetSdk **35**, Build Tools **36.0.0**, minSdk **30**, and installed
JBR **25.0.3+-15898627-b508.16** as the explicitly selected build JDK. No Kotlin/UI
framework or AndroidX runtime dependency is required for the custom resource handler.
JVM tests pin JUnit 4.13.2 and org.json 20240303; Android uses platform org.json.
The installed Studio is Quail 4 / 2026.1.4 (AI-261.26222.65.2614.16379836).

This replaces the earlier AGP 8.9.2 / JDK17 tooling candidate for this harness only:
[AGP 9.4 compatibility](https://developer.android.com/build/releases/agp-9-4-0-release-notes)
requires Gradle 9.6.0, Build Tools 36.0.0 and minimum JDK17;
[Gradle's matrix](https://docs.gradle.org/current/userguide/compatibility.html) supports
running on Java25 from 9.1;
[Studio's compatibility table](https://developer.android.com/studio/releases) lists
AGP 7.1–9.4 for Quail4. Wrapper creation, debug/test builds and a clean offline rebuild
are actual checks of this tuple, not an assumption that JBR25 substitutes for JDK17
with older Gradle. No system JDK/SDK was installed. Java8 in PATH is not used. This is
not product minSdk, engine support, release/security or Play distribution approval.

From repository root in PowerShell (network needed for an uncached first build):

```powershell
python android/tools/check-fixtures.py --pc1 logs/pc1-harness-fixtures-20261031
& android/tools/build.ps1 -BuildJdk D:/programThisPc/AndroidStudio/jbr -AndroidSdk C:/Users/admin/AppData/Local/Android/Sdk
```

`build.ps1` sets Java/SDK/Gradle variables for its process and places caches plus a
disposable debug signing key in ignored `android/.gradle/`. The key is not release
trust. With the already populated PC2 cache, the verified clean offline command is:

```powershell
& android/tools/build.ps1 -BuildJdk D:/programThisPc/AndroidStudio/jbr -AndroidSdk C:/Users/admin/AppData/Local/Android/Sdk -ReadOnlyDependencyCache C:/Users/admin/.gradle/caches -Tasks 'clean',':app:testDebugUnitTest',':app:assembleDebug',':app:assembleDebugAndroidTest','--offline'
$adb = 'C:/Users/admin/AppData/Local/Android/Sdk/platform-tools/adb.exe'
& $adb -s emulator-5556 install -r android/app/build/outputs/apk/debug/app-debug.apk
& $adb -s emulator-5556 install -r android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
& $adb -s emulator-5556 shell am instrument -w org.kiosk.harness.debug.test/org.kiosk.harness.HarnessTestRunner
& $adb -s emulator-5556 shell am start -W -n org.kiosk.harness.debug/org.kiosk.harness.HarnessActivity --es fixture valid-tv
```

Omit `--pc1` to check bundled provenance against Git without ignored PC1 evidence.
Required prerequisites elsewhere: full compatible build JDK, SDK platform35,
Build Tools36.0.0, accepted SDK licences, platform-tools and an authorized target.
The script does not install them or bypass execution policy. Initial sandbox network
denial and an uncached offline-plugin failure are retained in logs; subsequent
authorized dependency access used normal TLS with no trust/policy modification.

### Android adaptations and measured boundary

- The source is an immutable APK asset tree, not a filesystem directory. No symlink,
  reparse-point or mutable extraction tree is accepted through a runtime input API.
  The adapter enumerates the asset tree and requires exactly inventory plus descriptor;
  resource bytes are size/hash checked again for each response. A future directory
  importer needs its own link/nonregular/TOCTOU checks; none is implemented here.
- The custom handler retains Windows `https://kiosk.invalid` and returns local 200/403
  for every intercepted request. It never returns null to permit network fallback.
  No listener/certificate is installed. INTERNET permission, file/content access,
  mixed content, device grants, app Java bridges, windows/downloads and arbitrary
  main/subframe navigation are disabled/denied; renderer CSP also blocks connects.
  Encoded slash/backslash/double-encoding is explicitly denied as the reviewed Android
  URL-adapter policy. GET/inventory mappings and traversal/query/method refusals have
  JVM and target checks; this is not a packet capture of the whole emulator/provider.
- Android's lenient JSON parser is preceded by bounded standard-JSON syntax/depth
  validation, preserving cache preflight's refusal of comments/trailing garbage.
  Unknown descriptor properties remain tolerated; entry keys and integer types follow
  cache checks. Native coercion edge cases, malformed Unicode and non-ASCII case
  equivalence beyond the supplied ASCII filenames are not proven fully equivalent
  to C# `OrdinalIgnoreCase`; PC1 vectors/review are required before general view input.
  Current case collision tests cover ASCII. No package limits were substituted for
  the native view limits (2MiB descriptor, 64MiB/file, 128MiB inventory).
- Readiness keeps the fixed Windows counter regex, exact origin, one launch generation
  and deadlines. An attached-view visual-state callback is the Android synchronization
  adapter; it does not prove a physical screen is readable. Image decode is checked in
  engine tests, not added as a new readiness gate. Stale callbacks after disposal cannot
  promote the view. No live activation, last-ready receipt or shared-failure retention
  guarantee is implemented by this single-view harness.
- The provider exposes a built-in `[object Android]` JS namespace even after removal
  of legacy Java interface names. Its complete absence was an incorrect initial test
  expectation. No `addJavascriptInterface` or message port is registered by the app;
  runtime probes found no Java `getClass`, app `nativeBridge` or WebView2-style bridge.
  This does not claim absence of all standard engine-provided web APIs.

### Lifecycle correction after PC1 review — 2026-10-31

`PreparedWebView` now owns detachment as well as destruction. Its UI-thread-only,
idempotent `dispose()` marks the instance disposed and removes its Handler work,
removes an attached view from its parent, stops loading, then destroys it. The Activity
delegates cleanup rather than inspecting/removing an already destroyed WebView;
pause/resume/start wrappers also refuse access after disposal. This follows the
[WebView.destroy contract](https://developer.android.com/reference/android/webkit/WebView#destroy()).

Construction installs the native deadline only after WebView creation and configuration
have succeeded. A configuration exception cleans the owned partial view before
propagating to the Activity's safe failure state, without scheduling a late readiness
callback. A factory creation exception has no transferred view or timer to clean.

Package-private adapter seams have no Intent/page controls. The
[test-only runner](app/src/androidTest/java/org/kiosk/harness/HarnessTestRunner.java)
injects preflight/factory adapters before framework `onCreate`; it does not replace
framework Activity construction. Test code can throw before allocation or during
early/late setup, track detach/destroy order, hold real DOM/visual callback registrations,
and delay preflight on the worker. These controls are in the instrumentation APK;
the normal app always selects the platform factory and bundled-view verifier.

Both deadlines use main-thread Handler dispatch. They bound work while the UI loop
continues dispatching; neither is independent protection against a hung UI thread.
The startup test deliberately waits on the verification worker, not on the UI thread.
There is no claimed renderer/GPU/process-death validation in this correction.

New evidence: [logs/pc2-harness-fixes-20261031-175106](../logs/pc2-harness-fixes-20261031-175106/).
Exact new APK/source identities are in `source-identity.json`; full commands/results
are in `commands.txt`, `summary.md`, build logs and instrumentation output. Target is
the same read-only phone AVD, API37/x86_64, WebView145.0.7632.218. It is not AndroidTV
or physical hardware. Actual checks of the corrected source:

| Check | Actual result |
| --- | --- |
| Incremental debug/test APK assembly with unchanged tool tuple | PASS, `build-runner-fix.txt` and `build-task-fix.txt`; no clean rebuild |
| Lifecycle fault injection | PASS 5/5 in67.710s, `lifecycle-verified.txt` / `final-logcat.txt` |
| Creation and early/late configuration exceptions | PASS: >20s quiet period, no late completion, no transferred object on allocation refusal; both owned partial views destroyed once and detached |
| Attached/unattached, synthetic error, native timeout and repeated cleanup | PASS: UI-thread detach before destroy, no tracked WebView calls after destroy; repeated dispose/start/pause/resume inert |
| Held DOM/visual callbacks after native timeout and >20s elapsed | PASS: no ready/promotion or post-destroy WebView access |
| Actual startup timeout with worker-only delayed preflight | PASS: failed/safe message after20094ms, UI pulse processed; late verified result creates no WebView |
| Real Activity recreation with old preflight and held visual callback | PASS: old generation cannot attach/promote, replacement reaches ready, repeated old cleanup safe |
| Affected engine regression | PASS 10/10 in28.066s, `engine-regression.txt`; four views, origin/bridge/CSP/DOM/deadline/input checks retained |
| Fixture/archive and shared JS/CSS identity | PASS, `fixture-identity.txt`; bytes unchanged |

Initial test launches were aborted, not passed: `NEW_TASK` reused an already open
Activity (ActivityTaskManager result code3), so `startActivitySync` waited for creation
that did not happen. The lifecycle tests now request an isolated new task and use
bounded launch/UI waits. Those test-only fixes and incomplete attempt logs are retained.
The final runner lets the framework construct the Activity and injects adapters before
`onCreate`; no injection mechanism is selected by Intent or production app statics.
The tracked-view checks verify ownership/detachment/destruction, not a heap-profiler
or long-run leak measurement. Ordinary debug-app stops used to abort test launches are
not renderer/GPU/process-death acceptance scenarios.

The previous 21 JVM results are reused without rerun: verifier, JVM tests, fixtures,
shared assets, tools and dependency versions have unchanged hashes (`unchanged-baseline.txt`).
At that checkpoint physical testing, multi-card TV rotation, renderer/GPU/process-death
handling and long-run stability remained pending. The runtime slice below adds phone
emulator rotation and real renderer termination evidence. No contract, shared renderer, Windows/server,
ledger, store, network or pairing implementation changed. No commit/push/merge.

The existing `valid-tv` fixture contains one card. Its TV test proves readiness and
hidden controls only; it does **not** establish automatic multi-card rotation. That
scenario now has separate two-card emulator evidence below; physical TV/remote/touch
acceptance remains pending.

### Two-card TV and real renderer termination — 2026-10-31

Evidence: [logs/pc2-tv-runtime-20261031-181604](../logs/pc2-tv-runtime-20261031-181604/)
(`summary.md`, full commands/logs, source/APK SHA256 identities and copied APKs).
[RuntimeTest.java](app/src/androidTest/java/org/kiosk/harness/RuntimeTest.java)
adds two bounded target tests. The production change beyond catalog entries is a
renderer-gone diagnostic counter/log; cleanup/recovery behavior is unchanged.

PC1 runtime ZIP SHA256:
`7b4fc5f24e71ea0676de33d21eff1d70d27257dbe4283bc9935713b771b942d3`.
[check-runtime-fixtures.py](tools/check-runtime-fixtures.py) checks CRC, all26 extracted
files, exact bundled TV/kiosk bytes and independent JS/CSS pins. Catalog package identity
for both modes is `0d027e264096337f7f37f3ca6dd128ed3e6622aa2491ee404f742bb7f5cd1d18`.
The supplied package-validator result belongs to PC1; it was not rerun on Android.
No delivered HTML/CSS/JS or renderer timer was edited.

| Check | Result |
| --- | --- |
| Incremental offline build / debug installs | PASS; existing selected toolchain, no clean build |
| New runtime tests | PASS 2/2 in56.858s, `runtime-final.txt` / `runtime-logcat.txt` |
| Automatic TV rotation | PASS three transitions: ONE → TWO → ONE → TWO; intervals10593/10536/10550ms |
| Real renderer termination | PASS `terminate()=true`, actual `onRenderProcessGone`, `didCrash=false`; application PID2702 survived |
| Cleanup and bounded observation | PASS detached before one UI-thread destroy, native safe message, real captured DOM/visual registrations redelivered inert, no reload/restart over21s |
| Explicit close/relaunch | PASS same package/mode and pinned assets freshly verified, new WebView ready with images |
| Affected engine regression | PASS 10/10 in29.808s; catalog test now verifies six views, origin/bridge/CSP/DOM/deadline/input checks retained |

Rotation uses read-only DOM polling every200ms, with monotonic before/after sample
times, counter and both titles retained. No keys, clicks, model calls or accelerated
timers are used. The unchanged `eventsSlideDuration` computes
`min(24000,max(8000,base+text.length*70))`; base defaults to8000ms and the fixture's
title/short-description/place yield10590ms on both cards. Polling bounds explain
sample differences; tests allow750ms sampling margin and2500ms scheduling delay
(first sample also allows2500ms after native readiness). Observation is bounded85s.
Each sample checks ready, TV/content version2, hidden controls and loaded local images;
the host ready log records the verified package identity. This is a phone emulator
observation, not physical Android TV acceptance.

The official [WebViewRenderProcess.terminate contract](https://developer.android.com/reference/android/webkit/WebViewRenderProcess#terminate())
is available from API29: it returns whether termination was possible and can affect
multiple WebViews sharing a renderer; every affected view must handle
`onRenderProcessGone`, otherwise the app can terminate too. This separate owned debug
Activity launch has exactly one live WebView, and the API handle is obtained from that
view on the UI thread. No arbitrary PID is killed. The callback is real, not injected;
only the subsequent stale readiness delivery is synthetic. No production Intent/page
fault controls are added. GPU failure and death of the whole application remain pending.

Reproduce with the existing build command above, then on the owned target:

```powershell
python android/tools/check-runtime-fixtures.py
adb -s emulator-5556 install -r android/app/build/outputs/apk/debug/app-debug.apk
adb -s emulator-5556 install -r android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb -s emulator-5556 shell am instrument -w -r -e class org.kiosk.harness.RuntimeTest org.kiosk.harness.debug.test/org.kiosk.harness.HarnessTestRunner
adb -s emulator-5556 shell am instrument -w -r -e class org.kiosk.harness.EngineTest org.kiosk.harness.debug.test/org.kiosk.harness.HarnessTestRunner
```

Target remains read-only `Medium_Phone`, emulator-5556, Android17/API37/x86_64,
WebView `com.google.android.webview`145.0.7632.218 (763221809). Prior21 JVM and5 lifecycle
results are reused, not rerun: verifier/lifecycle logic and corresponding tests are
unchanged (only renderer callback diagnostics added). Engine regression is repeated
because the catalog now includes six selections. No system settings/snapshot changes.
Physical Android/TV, remote/touch/portrait/endurance, GPU and app-process-death gates
remain pending. Handler watchdogs require a responsive UI loop. Stage4 is incomplete.

### External debug-package force-stop and fresh asset launch — 2026-10-31

Evidence: [logs/pc2-process-restart-20261031-182729](../logs/pc2-process-restart-20261031-182729/).
The bounded [external ADB scenario](../logs/pc2-process-restart-20261031-182729/process_restart.py)
records every command, exit code, UTC/host-monotonic timestamps, PID and raw output;
it uses the unchanged previously checked APK, with no build or instrumentation run.
Target is the same read-only phone AVD/API37/WebView145.0.7632.218.
The installed package is exactly `org.kiosk.harness.debug`; local and installed APK
SHA256 is `fe684027de64a74deab59bd1c383892aa3f4cfc4c58c26459620d36c0bb48b2d`.
The scenario checks the exact serial, installed debuggable package, APK hash and absence
of INTERNET permission before using `am force-stop` on that package alone.

PASS: final externally observed PID4938 disappeared (including `/proc/4938`), with no
package process during21s observation. Explicit launch produced PID5307 and fresh ready
at15:31:36.775 device log time. Native preflight/DOM/visual ready retained the same identity;
external XML/screenshots show Version2, blue fixture image and automatic ONE → TWO.
The image was visually inspected; no new naturalWidth probe/instrumentation was run.
The first post-launch accessibility tree can lag visual readiness; bounded retries and
initial observer failures are recorded without changing application code.

Both launches select `two-card-tv`, verified package identity
`0d027e264096337f7f37f3ca6dd128ed3e6622aa2491ee404f742bb7f5cd1d18`, TV descriptor SHA256
`03d7810273353c846268f2f8db8e26f36d671966478a4d610a8de95c6f5d23ae`.
Host `ready` is emitted only after successful full preflight and fixed DOM/visual readiness,
not just navigation completion. Each fresh process executes this same preflight path;
no test injection is configured. External accessibility XML and screenshots record visible
Version2, card title and local image. The TV counter remains hidden by unchanged CSS and
is not externally sampled as a visible counter. No WebView debug port/page bridge is enabled.

This checks explicit fresh launch from immutable APK assets following a package force-stop.
It does not establish publication-store/last-ready-receipt recovery, process-death persistence,
power-loss durability, GPU failure, boot/autostart or physical acceptance. No such storage
or automatic recovery implementation exists here. Network settings remain unchanged;
the app has no INTERNET permission and serves only its verified APK resource map.
Final PASS/FAIL results, observations and owned-emulator cleanup are in `summary.md` and
`result.json` in the evidence directory. Stage4 remains incomplete.

### Pending physical Android/TV procedure

1. Obtain the owner's exact model, Android version and available ADB connection to PC2.
   Record `adb devices -l`, the selected serial, model/manufacturer, build fingerprint,
   API/security patch, display size/density/orientation, input device and
   `adb -s SERIAL shell dumpsys webviewupdate`. If unavailable/unauthorized or below the
   experimental minSdk30, leave the target gate pending; do not alter device settings.
2. Check debug APK SHA256/applicationId, confirm that the target is the owner's test
   device and that an existing same-package installation is disposable. Install only
   `app-debug.apk` using `adb -s SERIAL install -r ...`; no instrumentation APK, server,
   trust roots, device permissions, production data or system settings are needed.
   If ADB is not already available, the owner must arrange access separately.
3. Explicitly launch `org.kiosk.harness.debug/org.kiosk.harness.HarnessActivity` with
   `--es fixture valid-kiosk`, `empty-kiosk`, `two-card-kiosk`, `valid-tv`, `empty-tv`
   and `two-card-tv` in separate closed/relaunched runs. Record host identity/ready,
   images/empty messages and denied external navigation. On TV observe at least three
   automatic transitions with monotonic times and unchanged timer algorithm.
4. Exercise actual touch and the physical remote/D-pad/Select/Back; record focus visibility,
   tag/card selection and hidden TV controls. Test available portrait/landscape behavior
   by physically rotating an appropriate device, without changing rotation/system settings;
   fixed panels or unsupported orientations remain explicitly pending. Record readability,
   clipping, image shape and lifecycle/resume behavior on that exact hardware/WebView.
5. Close only the harness, explicitly relaunch, and repeat the verified-asset ready check.
   If separately authorized on that device, use exact-package `am force-stop`, externally
   observe PID disappearance/no self-restart for21s, then explicitly launch and record
   fresh PID/ready/image/rotation. Never infer physical results from emulator evidence.
6. Safe cleanup is exact-serial `am force-stop org.kiosk.harness.debug` and verification
   that its process is absent; retain evidence. Do not clear data, uninstall other apps,
   reset settings, reboot, stop ADB or kill unrelated processes. Removal of a pre-existing
   same-package installation needs its own concrete authorization.

All physical steps are pending until the model/OS/ADB prerequisites and device are supplied.
The owner selected virtual Medium_Phone for current testing; this does not supply a
physical target or close any physical gate.

### Initial harness checks (before lifecycle correction)

Evidence directory: [logs/pc2-harness-20261031-170517](../logs/pc2-harness-20261031-170517/).
Full failed attempts are retained alongside final results; source/APK identities are
in `source-identity.json`, target details in `target.txt`, final summary in `summary.md`.

| Check | Actual result / evidence |
| --- | --- |
| PC1 archive, extracted bytes, four view inventories, JS/CSS Git identity | PASS, `fixture-identity.txt` |
| JVM descriptor/path/hash/pinning/origin cases | PASS 21/21, copied JUnit XML and `clean-rebuild-final.txt` |
| Debug and instrumentation APK; clean offline build through Wrapper/script | PASS, `clean-rebuild-final.txt`; two clean builds have identical APK SHA256 (`clean-reproducibility.json`); Wrapper JAR/distribution checked against official SHA256 |
| Real engine: four views, empty counters, decoded images, safe invalid selection | PASS, `engine-final.txt`, `engine-final-logcat.txt`, `screen-*.png` |
| Android parser/identity/extra/missing/hash/rehashed-JS refusals | PASS, nine isolated negative view cases inside `EngineTest`; these are not the nine Python package examples |
| DOM missing after navigation, native 15s timeout, CSP fetch denial, local 200/403, forbidden URL/bridge probes | PASS in final 10-test engine suite; 20s startup fault-injection not run |
| D-pad / Select | PASS on phone emulator: existing renderer BUTTON focus, `:focus-visible`, tag selection; single-card TV readiness/hidden controls only, no multi-card rotation evidence; no shared asset/key-map change |
| Physical Android/TV, remote/touch, landscape panel, suspend/process/GPU loss, long-run/capacity and network capture | SKIPPED / pending; no physical target supplied |

Target: read-only `Medium_Phone`, `emulator-5556`, x86_64 phone, API37 / Android17,
fingerprint `google/sdk_gphone64_x86_64/emu64xa:17/CE2A.260420.051.A2/16418371:user/release-keys`,
security patch 2026-08-05, 1080x2400 / density420, reported MemTotal8127932kB;
WebView `com.google.android.webview` **145.0.7632.218** (763221809).
The existing AVD was launched `-read-only -no-snapshot-save -no-window -no-audio`
on port5556; no system setting was changed. A first screenshot series caught launch
animation and is retained as `early-screen-*`; final screenshots followed an additional
1s settle and were visually reviewed. The native safe message is not a browser error page.
The engine-tested incremental APKs are retained as `app-debug.apk` and
`app-debug-androidTest.apk` in the evidence directory. Clean APKs are retained with
`-clean.apk` suffixes; their ZIP entry order differs from the incremental packages,
but all uncompressed entry bytes match (`apk-rebuild-comparison.txt`). Identical
clean-to-clean hashes establish reproducibility only for this source/tool/cache/debug
key environment, not across machines or signing identities. The owned AVD is stopped
after evidence collection; it was not a physical device or a configured TV target.

Initial D-pad assertion wrongly equated an empty element ID with no focus (tag buttons
have no ID); diagnostics proved BUTTON focus. A test-only WebSettings read was also
moved to the UI thread. These failures remain in `engine-first/second/expanded*` logs;
the corrected final suite passed10/10. No equivalent physical input/TV acceptance is
inferred. Next minimal step is PC1 review of this diff/evidence and an identified physical
Android/TV run of the same harness, before separately authorizing ingestion/storage.
Stage4 remains incomplete. No commit/push/merge is performed.

## Earlier design inventory on PC2 (2026-10-31, before harness)

| Available item | Observed identity / limitation |
| --- | --- |
| Host | Windows 10.0.19045, as reported by adb |
| Android Studio | Running at D:/programThisPc/AndroidStudio; product-info.json build AI-261.26222.65.2614.16379836, data directory AndroidStudio2026.1.4 |
| Bundled JBR | 25.0.3, JetBrains runtime 25.0.3+-15898627-b508.16; IDE runtime, not a verified Gradle JDK |
| Java in PATH | Oracle 1.8.0_351, 64-bit; unsuitable for the proposed AGP tuple |
| SDK | C:/Users/admin/AppData/Local/Android/Sdk; platforms android-30, android-34, android-35, android-37.0; build-tools 34.0.0, 35.0.0, 36.0.0 |
| ADB | 1.0.41 / 37.0.1-15733141, executable in SDK/platform-tools; not in PATH |
| Emulator | Installed 37.2.13; not launched |
| AVD | Medium_Phone, medium_phone, x86_64, android-37.0/google_apis_playstore image; phone, not TV |
| Physical devices | adb devices -l returned an empty list; no connected authorized device identity established, not a device failure |
| CLI tools | sdkmanager/emulator/adb absent from PATH; SDK cmdline-tools directory not found in bounded probe; Gradle installation/caches not established |
| Python | C:/Python314/python.exe, 3.14.5; generator import fails: ModuleNotFoundError: No module named PIL; no repo .venv/venv found |

Read-only inventory used Get-Command, product-info.json, jbr/release, SDK directory
lists/source.properties, java -version, adb version, adb devices -l and
emulator -list-avds. No emulator launch, settings change or installation occurred.
No device model, Android build, ABI, RAM, storage or WebView provider version can be
claimed for physical hardware. Do not extrapolate AVD API 37 to supported hardware.

## Earlier tooling candidate (superseded for this harness)

Candidate for a disposable first harness: Java source with platform WebView and
AndroidX WebKit 1.12.1, compileSdk/targetSdk 35, minSdk 30, AGP 8.9.2,
Gradle 8.11.1, Build Tools 35.0.0, build JDK 17. Java avoids selecting a Kotlin
plugin or a UI framework for this bounded probe. API 30 is a deliberately bounded
initial test floor with an installed SDK, not an approved product minimum or a
claim that older TVs are supported. API 35 tooling is installed and has a documented
compatible AGP tuple. This older pinned tuple is a reproducible experiment candidate,
not a current release/security endorsement or Play-distribution commitment.
JDK 17 and Gradle 8.11.1 availability remain unverified; do not run with PATH Java 8
or assume JBR 25 is interchangeable. Android Studio's compatibility with this old AGP
must be checked before a build; command-line execution is a separate possibility.
The earlier design-only task created no Gradle wrapper, dependency declarations or
project; the explicitly selected continuation above now supplies them.

Official sources checked through Context7 (resolution /websites/developer_android)
and direct official-page verification on 2026-10-31:

- [AGP 8.9 compatibility and 8.9.2 fixes](https://developer.android.com/build/releases/agp-8-9-0-release-notes): API maximum 35, Gradle 8.11.1, Build Tools 35.0.0, JDK 17.
- [WebKit releases](https://developer.android.com/jetpack/androidx/releases/webkit): 1.12.1 exists; this library is an adapter, not the device WebView engine. Re-evaluate maintained stable versions/security before any production selection.
- [Local content](https://developer.android.com/develop/ui/views/layout/webapps/load-local-content): WebViewAssetLoader supports HTTPS-style local content. Unhandled requests can fall through to network, so the proposed wrapper must explicitly deny them.
- [TV navigation](https://developer.android.com/training/tv/get-started/navigation): remote D-pad/select/back require dedicated navigation checks.

Installed WebView engine is unknown. Proposed policy: record package/version and
security patch/support status per physical model before approval; feature-detect
required APIs and refuse unsupported readiness. No fixed engine version or hardware
support promise is made. D04 and D19 remain owner/device decisions.

## Shared renderer boundary

Existing Python [renderer](../kiosk/publication/renderer.py) builds escaped HTML and
bootstrap JSON using Jinja; [client assets](../kiosk/publication/renderer_assets/events.html),
[CSS](../kiosk/publication/renderer_assets/events.css) and
[JS](../kiosk/publication/renderer_assets/events.js) implement the Events display.
Reuse their generated kiosk/TV views byte-for-byte for the initial harness. Python,
Jinja and Pillow run on the development PC, never as assumed Android runtime.
Package resources/templates/scripts are validated legacy export resources, not
executable Android renderer code. Only client-owned trusted assets may execute.
Do not introduce a second renderer, template fork or Android-side Events UI.

Generated view.json is a separate descriptor, not a replacement package manifest.
The harness verifies its inventory, expected source package identity and shipped
asset hashes before serving it. Production data-to-view preparation on Android is
an unresolved adapter/distribution decision; the initial pre-generated-view harness
does not solve it. Windows display code documents boundaries, not portable Android
leases, storage or WebView2 implementation.

## Prepared-view verification baseline

The initial harness must preserve both layers of Windows preflight:
[LocalView](../kiosk/display/windows/OfflineDisplay.cs) and
[verify_cached_view](../kiosk/display/cache.py), rather than attributing all checks
to LocalView alone. These are view rules, separate from Events-package limits below.

- Descriptor: LocalView accepts `schema_version = 1`, `renderer = "events-v1"`,
  `mode = "kiosk"` or `"tv"`, a nonempty `revision`, and `files` with 3?10,000
  entries. `package_sha256` identifies the source package: cache preflight requires
  equality with the verified package identity and expected mode; native switch
  handling also compares the requested package identity/mode. LocalView alone
  merely stores `package_sha256` (null becomes an empty string); it does not validate
  its syntax or bind revision to package content. Do not claim otherwise or silently
  impose package-manifest field/type rules on this descriptor.
- Bounds in LocalView: `view.json` at most 2 MiB in bytes; JSON parser maximum
  length 2 MiB and recursion limit 32; each inventoried file 0?64 MiB inclusive;
  total inventoried bytes at most 128 MiB. The descriptor is not part of that sum.
  These are not the package verifier's 256 MiB/file and 64 MiB inventory limits.
- Native paths: root and existing ancestors must not be reparse points. Relative
  paths reject empty names, backslash, colon, empty `/` segments, `.`/`..`, trailing
  dot/space in any segment, and reparse points along the resolved path. Inventory
  names must be unique under `OrdinalIgnoreCase`; lookup uses ordinal exact names.
  Allowed resources are exactly `index.html`, `events.js`, `events.css`, plus paths
  under `static/uploads/` with extensions `.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`,
  `.bmp`, `.ico` (extension comparison is case-insensitive). All three core files
  are mandatory; `view.json` is metadata, never a served inventory entry.
- LocalView opens and verifies every listed file at construction and again on each
  resource read: actual length must equal declared size, the full read must complete
  with no extra byte, and SHA256 must match the declared 64 lowercase hex digits.
  JS/CSS digests must additionally equal the trusted hashes embedded in the native
  build (`@RENDERER_JS_SHA256@` / `@RENDERER_CSS_SHA256@` are build placeholders).
  Rehashing modified JS/CSS into the descriptor cannot make them trusted.
- Cache preflight supplies exact tree validation: regular files must equal inventory
  plus `view.json`; extra/missing files and linked directories/files are refused.
  Each inventory entry has exactly `path`, `size`, `sha256`; size is a nonnegative
  integer, every file is rehashed, and JS/CSS match shipped renderer assets.
  LocalView itself does not enumerate unlisted files: do not describe its standalone
  `--check-view` as proof of exact-tree or expected-package validation.

The harness must refuse a damaged/unreadable descriptor, missing/extra file, wrong
expected package/mode, size/hash mismatch or incompatible trusted assets before
serving the candidate. Preserve current parser tolerance at each Windows layer;
stricter JSON typing/unknown-field policy is not implicitly approved. Android has
no Windows reparse-point API: propose equivalent rejection of symlinks/unsafe
ancestors and nonregular files beneath the private root, with traversal, link,
case-collision and mutation fixtures. Parser/coercion differences likewise require
cross-runtime descriptor vectors and PC1 review before any necessary deviation;
no additional Android limit or relaxed check is approved here.

## Package verification proposal

Consume a directory, not an invented ZIP/network protocol. Implement parity with
[compatibility](../kiosk/publication/compatibility.py) and
[independent verification](../kiosk/publication/exporter.py). Accept exactly
`(1, events, events-v1, 1)`; integer fields reject booleans/floats. Preserve current
unknown manifest-property tolerance and exact public-data keys rather than adding
incompatible restrictions. Check revision equals public content_version decimal,
unique IDs, tag references, allowlisted settings and image/resource closure.

Before allocation enforce existing limits: manifest 2 MiB, 10,000 entries,
256 MiB/file, 64 MiB inventory sum, with overflow-safe counters and bounded streams.
These are verifier safety bounds, not Android capacity approval. Verify raw-byte
size/SHA256, exact regular-file inventory (excluding manifest), missing/extra files,
all 13 required resources, translations and dependency closure. Decode/validate
images with bounded pixel/allocation policy; Android decoder parity with Pillow
requires explicit fixtures and review, not assumed equivalence.

Apply portable POSIX path rules even on Android: 1–240 characters; reject absolute,
empty/dot/dot-dot segments, backslash, colon, forbidden symbols/control characters,
trailing dot/space, Windows device basenames and casefold duplicates. Android Unicode
casefold parity needs vectors. Reject links and nonregular files, including ancestor
links; resolve/open beneath the owned root without traversal/TOCTOU escapes. Copy into
private staging, then independently reverify staged bytes; mutation during copy fails.

Expose only stable contract codes in diagnostics, never private paths or payload.
Match isolated fixture errors exactly (unsafe-path fixture is invalid_package).
Multiple-defect first-error ordering is not portable acceptance. Hashes establish
integrity, not authenticity: this synthetic local exercise establishes no server trust.

## Storage, activation and recovery proposal

Use app-private internal storage, no broad/external storage permissions. Separate
owned staging, immutable verified revisions, generated views and a bounded active
pointer. Serialize writers with an Android process/storage lock; never reuse Windows
msvcrt leases. Source directories cannot be rendered directly.

Preflight accounts for active + previous + candidate package + candidate view + staging,
metadata and reserve, including orphan files. Proposed experiment bound: 512 MiB store
and 32 MiB free-space reserve, subject to measurement/approval (D07/D11); count actual
bytes and abort before exceeding bounds. Retain active/previous and reader-pinned
revisions; no automatic deletion of trusted fallback to fit an oversized candidate.
No GC implementation is authorized; orphan cleanup requires bounded ownership checks.

Sequence follows Windows, with separate publication authority and display confirmation:
verify/copy candidate; reverify; prepare/validate immutable view under the storage
writer guard; flush/promote; commit publication pointer. Artifact preflight must not
wait for UI/network or re-enter storage. After commit, the display coordinator loads
a hidden candidate; only matching readiness permits visible swap and last-ready receipt.
No package/view bytes from different generations may be mixed.

Before pointer commit, any validation/quota/I/O/preparation failure leaves publication
and displayed content unchanged, provided the existing display runtime remains alive.
After commit, failure of the hidden candidate alone (load error or readiness timeout)
leaves the previous working WebView visible and the last-ready receipt intact, while
the publication pointer may be newer. This guarantee requires that previous WebView,
its renderer and Activity to remain operational.

Shared renderer/GPU failure, Activity loss or process death can destroy both views;
preservation of visible pixels/content cannot be guaranteed. Stop candidate activation
and, while the Activity can draw, show a client-owned native safe error/loading state
without unverified content or network fallback. During Activity/process absence no
on-screen guarantee is possible; enter that safe state on the next permitted launch.
Treat actual visible content as unavailable/unknown, not as proven by the persisted
last-ready receipt. Keep the publication pointer and receipt as separate records.
On startup, revalidate current/backup publication and its view; if engine readiness fails,
try at most one revalidated last-ready view from the same renderer build. Record
fallback explicitly without rolling back publication authority or scanning arbitrary
revisions. Recovery uses only reverified local package/view bytes with matching
identity and trusted assets, at most the current candidate and one last-ready fallback
per recovery attempt. With neither ready, remain in the safe error state; do not
schedule continuous reload/restart cycles. A later explicit launch/recovery can retry
the bounded sequence. This does not automatically roll back the publication pointer.
Activity/process restoration is an Android proposal requiring fault-injection checks,
not an inherited Windows guarantee.

Use temporary file + atomic replacement and an independently recoverable previous
record; Android filesystem flush/directory durability must be tested, not inferred
from rename. A disk commit, visual swap and last-ready receipt are distinct boundaries.
If receipt persistence fails after visible swap, retain actual displayed identity and
pending receipt; repair before another switch instead of claiming the old view remains.
Crash/restart tests must assert all three identities separately.

## Controlled origin and security proposal

Map one immutable view under https://appassets.androidplatform.net with
WebViewAssetLoader/custom allowlist handler, no listening HTTP server. Bind requests
to the selected view generation and exact descriptor inventory; map MIME types explicitly.
Deny unknown hosts, schemes, paths, ports, userinfo, traversal/encoded separators and
unlisted query variants. Return local errors for misses rather than allowing network
fallback; intercept subresources as well as main-frame navigation. No file:// or
content:// navigation, external intents, redirects, popups or new windows.

Enable JavaScript only for pinned shared renderer code, preserve renderer CSP and
block network/connect/frame/object/form capabilities. Disable file/content access,
universal file URL access, mixed content, cookies/third-party cookies and unnecessary
DOM storage. No addJavascriptInterface, unrestricted message bridge, downloads,
file chooser, geolocation, camera/microphone, permission grants or external browser
launch. Deny SSL/auth challenges rather than bypassing trust. Proposed first offline
harness has no INTERNET permission; test interception denials independently because
permission absence alone is not an origin policy. Disable release debugging; no
secrets or raw content in logs. Fullscreen is presentation, not OS lockdown.

## Lifecycle, readiness and TV behavior proposal

Keep storage verification off the UI thread; WebView operations on the UI thread.
Activity recreation/process death reopens the verified committed identity instead of
trusting saved URL/history. Resume rechecks identity/provider; pause stops shell-owned
work, and shared timer behavior must be observed before deciding any adapter changes.
Candidate-only errors and shared-runtime loss follow the distinct retention/recovery
rules above. For the first Android harness, fix the Windows baseline deadlines:
15 seconds for native view preparation/readiness and 20 seconds for startup
coordination. The earlier 10-second suggestion is withdrawn. These deadlines do not
establish D11 performance acceptance. Any different timeout must be a separate later
proposal supported by slow-device measurements and review, without changing current
behavior in this documentation task.

onPageFinished alone is insufficient: confirm expected origin/generation and the fixed
Windows DOM counter (including intentional empty state), then the Android visual-state
callback. CSS/image decode is tested separately; further readiness predicates remain
subsequent proposals requiring review. Use host-initiated fixed read-only DOM checks with
identity-bound callbacks, no general JS-to-native bridge. Readiness proves local render
preconditions, not that a physical panel is on or content is readable.

Reuse shared kiosk tag/home/previous-next navigation, 90+30 second idle behavior and
TV rotation; test EN/RU/DE and fallback, empty data, long text, portrait/landscape,
image fit and disconnected restart. D-pad focus must be visible, deterministic,
reachable and restored after filtering/recreation; test select, held/repeated keys,
back/home and no focus trap. TV autoplay requires no touch; remote expectations and
any shared focus change require PC1 review. Do not fork assets to fix focus locally.
Physical TV remote, touch kiosk, panel overscan/readability and suspend/resume remain
mandatory; phone emulator screenshots cannot establish them.

## Conformance plan and actual checks

| Case | Expected verifier result | PC2 execution |
| --- | --- | --- |
| valid | ok | SKIPPED: missing PIL |
| empty | ok | SKIPPED: missing PIL |
| tampered | integrity_failure | SKIPPED: missing PIL |
| extra-file | inventory_mismatch | SKIPPED: missing PIL |
| unsupported-contract | unsupported_client_contract | SKIPPED: missing PIL |
| unsafe-path | invalid_package | SKIPPED: missing PIL |
| bad-public-data | invalid_public_data | SKIPPED: missing PIL |
| revision-mismatch | revision_mismatch | SKIPPED: missing PIL |
| missing-resource | reference_closure_failure | SKIPPED: missing PIL |

Attempted from repo root:
`python -m contracts.events_examples --output logs/pc2-contract-examples-20261031-design`.
Execution blocked during import before generation; traceback retained in
`logs/pc2-design-20261031/generator.txt`. No expected.json/results.json or generated
kiosk/TV views exist from this run. Do not claim all9 comparison or reference-view
inspection passed. When dependencies are available through separate authorization,
use a fresh unique destination, compare the complete expected/results dictionaries,
and retain generated view-kiosk/view-tv as shared-renderer references.

Future Android parity test: install known valid A, record pointer and full served-byte
hashes; propose each invalid candidate B; assert exact safe error, no path/content leak,
unchanged pointer and served A, then restart and recheck A. Repeat with empty valid
package, concurrent install, source mutation, decoder failure, storage exhaustion,
crash at each staging/promotion/pointer/swap boundary, corrupt current/previous pointer,
no fallback, and interrupted cleanup. The Python generator only verifies packages and
builds views; it does not test Android activation or trusted-content retention.

Origin tests cover external main/subresource loads, unlisted local files, encoded
traversal, redirects, file/content/intent/data URLs, bridge probes, popups, downloads,
permission/file chooser requests and network capture showing zero requests. Lifecycle
checks cover background/resume, rotation, renderer/process death and offline cold start.
Record exact source, package/view hashes, tool versions and outcomes per case; physical
checks additionally require model, OS build/security patch, ABI/RAM/free storage,
WebView provider/version, resolution/orientation and input identity (no secrets).

Earlier design-only record (not current harness results): exact base/branch and clean initial index; SDK inventory and empty ADB
list obtained. Python generation is BLOCKED by missing dependency, all9 comparison and
view use SKIPPED. Android harness/build/emulator/physical/security/storage acceptance
SKIPPED because no implementation or connected target exists. Documentation verification
is limited to relative link existence, git diff --check and allowed-path diff review;
no unrelated regression/build is required.

## Decisions and smallest next slice

Owner/PC1 review must approve the experimental tool tuple/language/minSdk, trusted
renderer distribution and future runtime adapter, store bound/reserve/retention,
readiness/recovery policy, image-validation parity and supported hardware/engine policy.
D04/D07/D11/D17/D19 remain open; D05 media expansion, D12 lockdown/autostart and D13
trust are outside this slice. Physical power-loss durability and security/low-storage
measurements remain gates, not promises.

The now-selected first slice was a disposable offline harness under android/ loading
one PC-generated verified kiosk/TV view with the existing assets through a deny-by-default
local origin; no package ingestion, network or production activation. Acceptance: pinned
asset identity, local readiness/empty state, blocked origin/bridge/navigation probes and
recorded emulator results, followed by separately scheduled physical TV/kiosk checks.
The actual implementation/results above delimit this slice. Separately authorize package
verifier parity and transactional storage slices. No full app,
product-version commitment, commit, push or merge is authorized by this document.

## Windows baseline to Android adapter traceability

This design is a port of the existing Windows behavior, not an independent client.
Read at this exact base: [store](../kiosk/publication/store.py),
[artifact preflight](../kiosk/display/session.py), [cache](../kiosk/display/cache.py),
[coordinator](../kiosk/display/coordinator.py),
[resource host](../kiosk/display/windows/PreparedView.cs),
[window switching](../kiosk/display/windows/DisplayWindow.cs),
[descriptor/origin checks](../kiosk/display/windows/OfflineDisplay.cs).
The [Windows README](../kiosk/display/README.md) describes recorded VM evidence and
limits. Those results are existing Windows evidence, not checks rerun on PC2 and not
Android proof. Shared verifier/renderer semantics remain unchanged.

| Existing Windows solution | Android constraint | Proposed adapter preserving behavior | Verification required |
| --- | --- | --- | --- |
| Exact Events tuple and independent exporter verification | Python/Pillow not Android runtime | Port validation semantics; keep PC-generated oracle and image parity vectors | All9 oracle cases plus numeric/path/casefold/image/closure edge cases; no silent format changes |
| Canonical manifest digest identifies revision; copied files streamed/reverified | Different filesystem/API and concurrency | Preserve canonical identity algorithm; bounded copying into private immutable revision storage | Cross-language canonical JSON vectors incl. Unicode/numbers; source mutation and digest equality |
| msvcrt writer lease, exclusive coordinator/profile leases | No Windows byte-range mechanism | Single owned coordinator plus Android file-channel lock and in-process serialization, subject to API review | Concurrent writers, process death and lock reacquisition; prevent same-process overlap |
| Separate non-nested store/cache/state/profile; orphan-inclusive bounds | App-private directories, WebView may write runtime data | Keep separate private roots and account for orphans/profile growth | Nested-root refusal, quota exhaustion, no deletion of active or confirmed data |
| install_for_display validates view before pointer commit; no UI under lease | UI thread lifecycle independent of storage worker | Retain artifact preflight under guard, then engine preparation outside guard | Crash checkpoints; failed artifact leaves pointer unchanged; failed engine may leave newer pointer |
| Cache identity includes package, mode and shipped renderer/translations; full rehash on reuse | No Python/Jinja runtime approved | Use PC-generated view in first slice; preserve descriptor checks and pinned trusted asset identity | Tamper/extra file/build change refusal; no arbitrary cached fallback |
| Per-WebView immutable map at kiosk.invalid, every response rehashed, forbidden requests 403 | Different WebView interception APIs | AssetLoader/custom handler at reserved local HTTPS origin, exact GET/inventory mapping, rehash before serving; deny all misses | Repeat Windows policy vectors on Android, include subframes and request-method/encoded-path bypasses |
| Two controls: old remains visible until candidate ready, same window/fullscreen | Activity recreation, renderer/GPU failure may affect both WebViews | Two generation-bound WebViews in same Activity; dispose failed candidate only while previous WebView is healthy; shared failure enters safe state | Failed B retains A; successful C swaps once; rotation/fullscreen, shared engine death explicitly tested |
| Fresh session/PID/request/cache/package/mode; stale/duplicate request handling | Android recreation can keep PID while Activity changes | Fresh session and Activity generation plus request/package/view/mode IDs; no page bridge or external command API | Late callback, duplicate request, stale Activity and timeout reconciliation cannot switch wrong view |
| Navigation success plus fixed DOM counter; 15s native / 20s coordinator deadlines | Android rendering callbacks differ | Preserve fixed host-initiated DOM probe and bounded startup; propose visual-state/image checks as additional readiness only | Navigation-only and broken-DOM refusal; empty-list counter; delayed images, timeout and renderer death |
| Last-ready same-build fallback, at most two startup candidates; no continuous restart | Activity/process lifecycle needs restoration | Persist last-ready identity, revalidate package/cache, one fallback; bounded explicit recovery | Corrupt receipt, build mismatch, missing package, offline cold start, no arbitrary scan |
| Receipt write failure after swap preserves actual new identity and pending receipt | Async Activity lifecycle can interrupt persistence | Serialize state/receipt recovery before next activation | Inject post-swap write failure and process death; distinguish visible, published and confirmed identities |
| Shared kiosk idle/navigation and TV timers; fullscreen is not lockdown | D-pad/focus/touch and panel characteristics differ | Keep same assets and behavior; shell adapts input/lifecycle only | Windows behavior parity, physical remote/touch/portrait and resume timer checks |

Explicit proposals that depart from the Windows prototype require review:

- Windows store/cache/profile each have separate prototype bounds (256 MiB), with
  view cap128 MiB and metadata reserves. Android's earlier 512 MiB combined-store /
  32 MiB reserve suggestion is an unmeasured capacity experiment, not an improvement
  or replacement guarantee. Approve partition/accounting policy only after peak-space
  tests including two WebViews, retained fallback, orphan files and runtime profile.
- The first Android harness uses the Windows 15-second native and 20-second startup
  coordinator deadlines and fixed DOM counter. Different deadlines require a separate
  measured proposal; extra visual/image checks also remain unapproved proposals.
- Windows local hostname is kiosk.invalid; the proposed AssetLoader reserved hostname
  changes only origin plumbing, not permitted resources/navigation. Test CSP/relative
  URLs, exact origin policy and zero fallback to network before approving it.
- Windows native process failure ends the controlled run; Android lifecycle restoration
  needs an explicit bounded policy. Automatic perpetual restart is not inherited or
  approved. Process-death/recreation tests must establish the proposed recovery.

No adaptation above is proven better on Android. Contract, renderer, user behavior or
requirement changes must go to PC1/owner before implementation; local focus or readiness
experiments cannot silently alter shared assets. The smallest next harness must first
replay the Windows descriptor/origin/readiness scenarios with the same generated view;
it is a platform adapter experiment, not a replacement application.
