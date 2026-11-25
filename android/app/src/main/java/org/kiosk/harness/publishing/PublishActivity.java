package org.kiosk.harness.publishing;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.view.ViewGroup;
import android.widget.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.delivery.DeliveryClient;
import org.kiosk.harness.delivery.PageReleaseProtocol;
import static org.kiosk.harness.delivery.DeliveryJson.*;
import static org.kiosk.harness.delivery.DeliveryProtocol.*;

/**
 * Native publisher entry point: QR/deep-link login and publication review/Publish.
 * No WebView and no remote signing bridge. Only the exact downloaded candidate is
 * verified; the operator confirms explicitly; the Keystore key signs once.
 */
public final class PublishActivity extends Activity {
    private static final int MAX_JSON = 2 * 1024 * 1024;
    private static final int PICK_AUTHORITY = 8117;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final AtomicInteger loadToken = new AtomicInteger();
    private PublisherKey key;
    private PublisherState state;
    private Map<String,Object> authority;
    private Map<String,Object> storedBundle;
    private Map<String,Object> grant;
    private long policyVersion;
    private Map<String,Object> document;
    private Map<String,Object> pageDocument;
    private Map<String,PageReleaseProtocol.Files> pageFiles;
    private String pageToken, pageContentOrigin, pageMaintenanceOrigin;
    private long pageExpires;
    private byte[] publicData;
    private int documentToken;
    private String pendingLink;
    private byte[] requestPayload;
    private TextView status, summary;
    private EditText candidate;
    private CheckBox confirmed;
    private Button publish, retry, discard, cancel;

    @Override protected void onCreate(Bundle bundle) {
        super.onCreate(bundle);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(32, 32, 32, 32);
        setContentView(root);
        status = new TextView(this);
        status.setText("Preparing the device-bound publisher key...");
        root.addView(status);
        candidate = new EditText(this);
        candidate.setSingleLine(true);
        candidate.setHint("Candidate link or id (opened automatically from the QR)");
        root.addView(candidate, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));
        Button load = new Button(this);
        load.setText("Load and verify candidate");
        root.addView(load);
        Button importButton = new Button(this);
        importButton.setText("Set up publisher authority (first device)");
        root.addView(importButton);
        Button recoveryButton = new Button(this);
        recoveryButton.setText("Recovery: replace publisher root");
        root.addView(recoveryButton);
        Button maintenanceButton = new Button(this);
        maintenanceButton.setText("Set trusted Maintenance origin");
        root.addView(maintenanceButton);
        Button maintenanceCaButton = new Button(this);
        maintenanceCaButton.setText("Set trusted Maintenance CA");
        root.addView(maintenanceCaButton);
        Button requestButton = new Button(this);
        requestButton.setText("Export add-device request (same user)");
        root.addView(requestButton);
        summary = new TextView(this);
        summary.setTextSize(12);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(summary);
        root.addView(scroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
        confirmed = new CheckBox(this);
        confirmed.setText("I compared this exact content, revision and target list");
        root.addView(confirmed);
        publish = new Button(this);
        publish.setText("Publish (sign exactly this candidate)");
        publish.setEnabled(false);
        root.addView(publish);
        retry = new Button(this);
        retry.setText("Retry stored approval");
        retry.setEnabled(false);
        root.addView(retry);
        discard = new Button(this);
        discard.setText("Discard stored approval");
        discard.setEnabled(false);
        root.addView(discard);
        cancel = new Button(this);
        cancel.setText("Cancel current review");
        root.addView(cancel);
        worker.execute(this::loadKey);
        load.setOnClickListener(view -> openId(candidate.getText().toString().trim()));
        importButton.setOnClickListener(view -> pickAuthority(false));
        recoveryButton.setOnClickListener(view -> pickAuthority(true));
        maintenanceButton.setOnClickListener(view -> setMaintenanceOrigin());
        maintenanceCaButton.setOnClickListener(view -> setMaintenanceCa());
        requestButton.setOnClickListener(view -> exportRequest());
        publish.setOnClickListener(view -> sign());
        retry.setOnClickListener(view -> retryPending());
        discard.setOnClickListener(view -> discardPending());
        cancel.setOnClickListener(view -> {
            loadToken.incrementAndGet();
            document = null; pageDocument = null; pageFiles = null; publicData = null;
            pageToken = null; pageContentOrigin = null; pageMaintenanceOrigin = null;
            pageExpires = 0;
            confirmed.setChecked(false); publish.setEnabled(false);
            show("Review cancelled. Nothing was signed.");
        });
        handleIntent(getIntent());
    }

    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIntent(intent);
    }

    private void handleIntent(Intent intent) {
        if (intent == null || intent.getData() == null) return;
        Uri uri = intent.getData();
        if (!"kiosk".equals(uri.getScheme()) || !"roaming".equals(uri.getHost())
                || uri.getFragment() == null) return;
        final String raw = uri.toString();
        worker.execute(() -> {
            if (key == null) { pendingLink = raw; return; }
            applyLink(raw);
        });
    }

    private void applyLink(String raw) {
        try {
            Uri uri = Uri.parse(raw);
            Map<String,String> fragment = fragment(uri.getFragment());
            if (authority == null) {
                pendingLink = raw;
                show("Install publisher authority for this device, then reopen the link.");
                return;
            }
            String path = uri.getPath();
            if ("/page".equals(path)) {
                applyNativeTicket(fragment);
            } else if ("/publish".equals(path)) {
                if (!str(authority,"origin").equals(fragment.get("origin"))) {
                    throw new IOException("publisher_origin_refused");
                }
                String plan = fragment.get("plan");
                if (plan == null) throw new IOException("publisher_link_refused");
                runOnUiThread(() -> { candidate.setText(plan); openId(plan); });
            } else if ("/login".equals(path)) {
                login(fragment.get("token"));
            } else {
                throw new IOException("publisher_link_refused");
            }
        } catch (Exception failure) {
            show("Link refused: " + failure.getMessage());
        }
    }

    /**
     * Native Stage 6 handoff. The ticket token is accepted only in the URL fragment,
     * only for the locally configured Maintenance origin, and never displayed.
     */
    private void applyNativeTicket(Map<String,String> fragment) {
        try {
            NativePageProtocol.Handoff handoff = NativePageProtocol.handoff(fragment, now());
            String token = handoff.token();
            String contentOrigin = handoff.contentOrigin();
            String maintenanceOrigin = handoff.maintenanceOrigin();
            need(state != null && !state.maintenanceCa().isEmpty());
            need(str(authority,"origin").equals(contentOrigin));
            need(maintenanceEndpoint().equals(maintenanceOrigin));
            final int ticket = loadToken.incrementAndGet();
            document = null; pageDocument = null; pageFiles = null; publicData = null;
            pageToken = token; pageContentOrigin = contentOrigin; pageMaintenanceOrigin = maintenanceOrigin;
            pageExpires = handoff.expires();
            publish.setEnabled(false);
            worker.execute(() -> openNativePage(ticket, token, contentOrigin, maintenanceOrigin));
        } catch (Exception failure) {
            pageToken = null; pageContentOrigin = null; pageMaintenanceOrigin = null;
            pageExpires = 0;
            show("Native page link refused: " + failure.getMessage());
        }
    }

    /** Open the frozen v2 document, then fetch exact signed bytes from each target route. */
    private void openNativePage(int ticket, String token, String contentOrigin, String maintenanceOrigin) {
        try {
            Map<String,Object> value = NativePageProtocol.openValue(token, contentOrigin, maintenanceOrigin);
            Map<String,Object> approval = PublisherEnvelope.sign(key, "page-review-open", value);
            CandidateClient client = new CandidateClient(maintenanceOrigin, token, state.maintenanceCa());
            Map<String,Object> opened = client.nativeOpen(approval, array(authority.get("chain")));
            if (ticket != loadToken.get()) return;
            Map<String,Object> plan = PublisherReview.reviewPageDocument(opened, now(), state.heads(),
                    PageReleaseProtocol.SHIPPED_JS_SHA256, PageReleaseProtocol.SHIPPED_CSS_SHA256);
            if (ticket != loadToken.get()) return;
            verifyPageAuthority(plan);
            Map<String,PageReleaseProtocol.Files> files = client.nativePageArtifacts(opened);
            if (ticket != loadToken.get()) return;
            Map<String,Object> facts = PublisherReview.pageReviewSummary(opened, files, now(), state.heads(),
                    PageReleaseProtocol.SHIPPED_JS_SHA256, PageReleaseProtocol.SHIPPED_CSS_SHA256);
            if (ticket != loadToken.get()) return;
            need(str(facts,"publisher_device_id").equals(PublisherAuthority.keyId(key.publicKey())));
            document = null; pageDocument = opened; pageFiles = files; publicData = null; documentToken = ticket;
            show(pageSummary(facts));
            runOnUiThread(() -> { confirmed.setChecked(false); publish.setEnabled(true); });
        } catch (Exception failure) {
            if (ticket != loadToken.get()) return;
            pageDocument = null; pageFiles = null;
            show("Native page refused: " + failure.getMessage());
        }
    }

    private static Map<String,String> fragment(String raw) {
        Map<String,String> result = new LinkedHashMap<>();
        if (raw == null) return result;
        for (String pair : raw.split("&")) {
            if (pair.isEmpty()) continue;
            int split = pair.indexOf('=');
            String key = Uri.decode(split < 0 ? pair : pair.substring(0, split));
            String value = split < 0 ? "" : Uri.decode(pair.substring(split + 1));
            if (result.put(key, value) != null) throw new IllegalArgumentException("duplicate");
        }
        return result;
    }

    private void loadKey() {
        try {
            key = KeystorePublisherKey.open();
            state = new PublisherState(getFilesDir());
            String authorityFailure = null;
            try {
                reloadAuthority();
            } catch (Exception failure) {
                authority = null;
                authorityFailure = failure.getMessage();
            }
            StringBuilder text = new StringBuilder("Device ")
                    .append(PublisherAuthority.keyId(key.publicKey()));
            if (authority == null) {
                text.append("\nNo usable publisher authority")
                        .append(authorityFailure == null ? "" : " (" + authorityFailure + ")")
                        .append(". First-device setup requires an administrator bundle and its "
                                + "independently communicated fingerprint.");
            } else {
                text.append("\nUser ").append(str(grant,"user_id"))
                        .append(" publisher authority installed; policy version ").append(policyVersion)
                        .append(". Known heads: ").append(state.heads().size()).append('.');
            }
            Map<String,Object> pending = state.pending();
            if (!pending.isEmpty()) {
                text.append(pagePending(pending)
                        ? "\nA signed page approval is stored, but the ticket is not persisted. "
                                + "Open a fresh native handoff link to retry it, or Discard."
                        : "\nA signed approval is stored and awaiting submission. Use Retry.");
                runOnUiThread(() -> { retry.setEnabled(true); discard.setEnabled(true); });
            }
            show(text.toString());
            if (pendingLink != null) {
                final String link = pendingLink; pendingLink = null;
                applyLink(link);
            }
        } catch (Exception failure) {
            show("Publisher state unavailable: " + failure.getMessage());
        }
    }

    private void reloadAuthority() throws Exception {
        authority = null;
        storedBundle = null;
        File file = new File(getFilesDir(), "publisher-authority.json");
        if (!file.isFile()) return;
        Map<String,Object> value;
        try (InputStream stream = new FileInputStream(file)) {
            value = json(stream.readNBytes(LIMIT), LIMIT);
        }
        storedBundle = value;
        java.security.PublicKey root = PublisherAuthority.publicKey(str(value,"root_spki"));
        policyVersion = num(PublisherAuthority.verified(obj(value,"policy"), root, "policy"),"version");
        authority = verifyBundle(value, state.policyFloor());
    }

    private static final int LIMIT = 65536;

    /** Verify an already-installed bundle; no operator input is needed for reuse. */
    private Map<String,Object> verifyBundle(Map<String,Object> value,long floor)throws Exception{
        keys(value,"root_spki","root_sha256","policy","chain","group_id","origin");
        if (key == null) throw new IOException("publisher_key_not_ready");
        java.security.PublicKey root = PublisherAuthority.publicKey(str(value,"root_spki"));
        need(LocalView.digest(root.getEncoded()).equals(str(value,"root_sha256")));
        Map<String,Object> policy = PublisherAuthority.policy(obj(value,"policy"), root,
                str(value,"group_id"), str(value,"origin"), now(), floor);
        var permission = PublisherAuthority.permission(array(value.get("chain")), root, policy, now());
        need(PublisherAuthority.keyId(permission.key())
                .equals(PublisherAuthority.keyId(key.publicKey())));
        grant = permission.grant();
        return value;
    }

    private void pickAuthority(boolean recovery) {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT)
                .addCategory(Intent.CATEGORY_OPENABLE).setType("application/json");
        startActivityForResult(intent, recovery ? PICK_AUTHORITY + 1 : PICK_AUTHORITY);
    }

    private void exportRequest() {
        if (key == null || state == null) {
            show("Publisher key is not ready.");
            return;
        }
        if (authority != null && grant != null) {
            try {
                prepareRequest(str(authority,"group_id"), str(authority,"origin"), str(grant,"user_id"));
            } catch (Exception failure) {
                show("Device request refused: " + failure.getMessage());
            }
            return;
        }
        try {
            DeliveryClient delivery = new DeliveryClient(this);
            if (!delivery.confirmed()) {
                show("Connect and confirm the server in the display screen before requesting a device.");
                return;
            }
            final String group = delivery.trustedGroup(), origin = delivery.trustedOrigin();
            EditText user = new EditText(this);
            user.setSingleLine(true);
            user.setHint("Same user account id");
            new AlertDialog.Builder(this).setTitle("Add this device to an existing user")
                    .setMessage("Enter the existing user id. An already authorized device of that same "
                            + "user must explicitly approve this request; this device cannot grant itself "
                            + "authority and the request does not delegate further.")
                    .setView(user).setNegativeButton("Cancel", null)
                    .setPositiveButton("Create request", (dialog, which) -> {
                        String id = user.getText().toString().trim();
                        if (id.isEmpty()) { show("A user id is required."); return; }
                        prepareRequest(group, origin, id);
                    }).show();
        } catch (Exception failure) {
            show("Device request refused: " + failure.getMessage());
        }
    }

    private void prepareRequest(String group, String origin, String user) {
        try {
            Map<String,Object> request = PublisherDeviceRequest.create(key, group, origin, user, now());
            requestPayload = PublisherAuthority.canonical(request);
            Intent create = new Intent(Intent.ACTION_CREATE_DOCUMENT)
                    .addCategory(Intent.CATEGORY_OPENABLE).setType("application/json")
                    .putExtra(Intent.EXTRA_TITLE, "kiosk-device-request.json");
            startActivityForResult(create, PICK_AUTHORITY + 2);
        } catch (Exception failure) {
            show("Device request refused: " + failure.getMessage());
        }
    }

    private void writeRequest(Uri target) {
        worker.execute(() -> {
            try {
                byte[] payload = requestPayload;
                requestPayload = null;
                if (payload == null) throw new IOException("publisher_request_missing");
                try (OutputStream stream = getContentResolver().openOutputStream(target, "wt")) {
                    if (stream == null) throw new IOException("publisher_request_output");
                    stream.write(payload);
                    stream.flush();
                }
                show("Device request exported. An already authorized own device must explicitly "
                        + "authorize it; this request grants nothing by itself.");
            } catch (Exception failure) {
                show("Device request refused: " + failure.getMessage());
            }
        });
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (data != null && data.getData() != null && request == PICK_AUTHORITY + 2
                && result == RESULT_OK) {
            writeRequest(data.getData());
            return;
        }
        if ((request != PICK_AUTHORITY && request != PICK_AUTHORITY + 1)
                || result != RESULT_OK || data == null || data.getData() == null) return;
        final boolean recovery = request == PICK_AUTHORITY + 1;
        worker.execute(() -> {
            try (InputStream stream = getContentResolver().openInputStream(data.getData())) {
                byte[] payload = stream.readNBytes(LIMIT + 1);
                need(payload.length <= LIMIT);
                confirmImport(payload, recovery);
            } catch (Exception failure) {
                show("Publisher bundle refused: " + failure.getMessage());
            }
        });
    }

    /** Independent first trust: the operator types the fingerprint from the admin. */
    private void confirmImport(byte[] payload, boolean recovery) {
        try {
            Map<String,Object> value = json(payload, LIMIT);
            keys(value,"root_spki","root_sha256","policy","chain","group_id","origin");
            java.security.PublicKey root = PublisherAuthority.publicKey(str(value,"root_spki"));
            String fingerprint = LocalView.digest(root.getEncoded());
            runOnUiThread(() -> {
                LinearLayout layout = new LinearLayout(this);
                layout.setOrientation(LinearLayout.VERTICAL);
                TextView message = new TextView(this);
                message.setText((recovery ? "Recovery replaces the pinned publisher root and clears "
                        + "local ancestry. " : "")
                        + "Type the SHA-256 fingerprint received through an independent trusted "
                        + "channel. The bundle alone authenticates nothing.");
                EditText typed = new EditText(this);
                typed.setSingleLine(true);
                typed.setHint("64 hex fingerprint " + fingerprint.substring(0, 8) + "...");
                EditText confirmation = new EditText(this);
                confirmation.setSingleLine(true);
                confirmation.setHint(recovery ? "Type REPLACE" : "Not required");
                confirmation.setEnabled(recovery);
                layout.addView(message); layout.addView(typed); layout.addView(confirmation);
                new AlertDialog.Builder(this)
                        .setTitle(recovery ? "Replace publisher root" : "Authenticate publisher pin")
                        .setView(layout).setNegativeButton("Cancel", null)
                        .setPositiveButton("Import", (dialog, which) -> worker.execute(() -> {
                            try {
                                String supplied = typed.getText().toString().replace(":","")
                                        .replace(" ","").trim().toLowerCase(Locale.ROOT);
                                need(supplied.equals(fingerprint));
                                if (recovery) need("REPLACE".equals(confirmation.getText().toString().trim()));
                                install(value, fingerprint, recovery);
                            } catch (Exception failure) {
                                show("Publisher bundle refused: " + failure.getMessage());
                            }
                        })).show();
            });
        } catch (Exception failure) {
            show("Publisher bundle refused: " + failure.getMessage());
        }
    }

    private void install(Map<String,Object> value,String fingerprint,boolean recovery)throws Exception{
        java.security.PublicKey root = PublisherAuthority.publicKey(str(value,"root_spki"));
        need(LocalView.digest(root.getEncoded()).equals(fingerprint));
        Map<String,Object> incomingPolicy = PublisherAuthority.verified(obj(value,"policy"), root, "policy");
        if (storedBundle == null && state.policyFloor() > 0 && !recovery) {
            throw new IOException("publisher_authority_recovery_required");
        }
        if (storedBundle != null) {
            Map<String,Object> oldRoot = storedBundle;
            boolean sameRoot = str(oldRoot,"root_spki").equals(str(value,"root_spki"));
            if (!sameRoot && !recovery) throw new IOException("publisher_root_replacement_requires_recovery");
            if (authority == null && !recovery) {
                // A corrupt/expired pinned bundle is not silently replaceable.
                throw new IOException("publisher_authority_recovery_required");
            }
            if (!recovery) {
                need(str(oldRoot,"group_id").equals(str(value,"group_id")));
                need(str(oldRoot,"origin").equals(str(value,"origin")));
                Map<String,Object> oldPolicy = PublisherAuthority.verified(obj(oldRoot,"policy"),
                        PublisherAuthority.publicKey(str(oldRoot,"root_spki")), "policy");
                long oldVersion = num(oldPolicy,"version"), newVersion = num(incomingPolicy,"version");
                need(newVersion >= oldVersion);
                if (newVersion == oldVersion) {
                    need(Arrays.equals(PublisherAuthority.canonical(oldPolicy),
                            PublisherAuthority.canonical(incomingPolicy)));
                }
            }
        }
        Map<String,Object> verified = verifyBundle(value, recovery ? 0 : state.policyFloor());
        if (recovery) state.resetForRecovery();
        try (FileOutputStream stream = new FileOutputStream(
                new File(getFilesDir(), "publisher-authority.json"))) {
            stream.write(PublisherAuthority.canonical(verified));
            stream.flush(); stream.getFD().sync();
        }
        storedBundle = verified;
        authority = verified;
        policyVersion = num(incomingPolicy,"version");
        state.observePolicy(policyVersion);
        show("Publisher authority installed for this device and user; policy version "
                + policyVersion + ".");
    }

    private void openId(String identity) {
        if (key == null || state == null) { show("Publisher key is not ready."); return; }
        if (authority == null) { show("Publisher authority is not installed."); return; }
        if (identity.startsWith("kiosk://")) { applyLink(identity); return; }
        if (!identity.matches("[a-f0-9]{64}")) { show("Enter the exact candidate link or id."); return; }
        final int token = loadToken.incrementAndGet();
        document = null; pageDocument = null; pageFiles = null; publicData = null; publish.setEnabled(false);
        worker.execute(() -> {
            try {
                CandidateClient client = new CandidateClient(authority);
                Map<String,Object> loaded = client.candidate(identity);
                // Stage 6 pages are never opened through the v1 candidate transport.
                if (pageCandidate(loaded)) throw new IOException("publisher_native_ticket_required");
                byte[] data = client.publicData(identity);
                Map<String,Object> plan = PublisherReview.verify(loaded, data, now(),
                        state.heads(), key.publicKey());
                if (token != loadToken.get()) return;
                document = loaded; pageDocument = null; pageFiles = null; publicData = data; documentToken = token;
                show(summary(plan, loaded));
                runOnUiThread(() -> { confirmed.setChecked(false); publish.setEnabled(true); });
            } catch (Exception failure) {
                if (token != loadToken.get()) return;
                document = null; pageDocument = null; pageFiles = null; publicData = null;
                show("Candidate refused: " + failure.getMessage());
            }
        });
    }

    private static boolean pageCandidate(Map<String,Object> value)throws Exception{
        if (!(value.get("version") instanceof NumberToken) || num(value,"version") != 2) return false;
        return value.get("plan") instanceof Map && value.get("revision") instanceof Map
                && value.get("targets") instanceof List && value.get("ancestry") instanceof List;
    }

    /** Exact immutable v2 facts after every target package byte and projection was re-derived. */
    private String pageSummary(Map<String,Object> facts)throws Exception{
        StringBuilder text = new StringBuilder();
        String plan = str(facts,"plan_id"), revision = str(facts,"revision_sha256");
        text.append("Page plan ").append(plan.substring(0,16).toUpperCase(Locale.ROOT))
                .append(" — group ").append(str(facts,"group_id"))
                .append(" — user ").append(str(facts,"user_id"))
                .append(" — publisher ").append(str(facts,"publisher_device_id").substring(0,16)).append("…\n");
        text.append("Revision ").append(revision).append(" — policy v").append(num(facts,"policy_version"))
                .append(" — expires ").append(num(facts,"expires")).append('\n');
        List<Object> included = array(facts.get("included")), excluded = array(facts.get("excluded"));
        text.append("Included ").append(included.size()).append(":\n");
        for (Object item : included) { Map<String,Object> entry = object(item);
            text.append("  ").append(str(entry,"id")).append(" v").append(num(entry,"version"))
                    .append(" by ").append(str(entry,"author")).append('\n'); }
        text.append("Excluded ").append(excluded.size()).append(":\n");
        for (Object item : excluded) { Map<String,Object> entry = object(item);
            text.append("  ").append(str(entry,"id")).append(" v").append(num(entry,"version"))
                    .append(" by ").append(str(entry,"author")).append(" — ").append(str(entry,"reason")).append('\n'); }
        text.append("Targets:\n");
        for (Object item : array(facts.get("targets"))) { Map<String,Object> target = object(item);
            text.append("  ").append(str(target,"device_id")).append(" — ").append(str(target,"projection"))
                    .append(" — ").append(str(target,"destination")).append(" — ")
                    .append(str(target,"profile_id")).append(" v").append(num(target,"profile_version"))
                    .append(" ").append(str(target,"mode")).append('\n');
            text.append("    content ").append(str(target,"content_sha256"))
                    .append("\n    metadata ").append(str(target,"metadata_sha256"))
                    .append("\n    package ").append(str(target,"package_id"))
                    .append("\n    manifest ").append(str(target,"raw_manifest_sha256"))
                    .append("\n    renderer ").append(str(target,"renderer")).append('\n'); }
        text.append("Renderer assets ")
                .append(org.kiosk.harness.delivery.PageReleaseProtocol.SHIPPED_JS_SHA256.substring(0,16)).append("… / ")
                .append(org.kiosk.harness.delivery.PageReleaseProtocol.SHIPPED_CSS_SHA256.substring(0,16)).append("… (pinned locally)\n");
        text.append("Exact data-only package bytes were fetched and hashed. One Publish signs exactly this plan.\n");
        return text.toString();
    }

    private long now() { return System.currentTimeMillis() / 1000L; }

    private String summary(Map<String,Object> plan,Map<String,Object> loaded)throws Exception{
        StringBuilder text = new StringBuilder();
        text.append("Candidate ").append(str(plan,"id").substring(0,8).toUpperCase(Locale.ROOT))
                .append(" — user ").append(str(plan,"user_id"))
                .append(" — device ").append(str(plan,"device_id").substring(0,16)).append("…\n");
        text.append("Revision ").append(num(loaded,"content_version")).append(" — targets:\n");
        for (Object item : array(plan.get("targets"))) {
            Map<String,Object> target = object(item);
            text.append("  ").append(str(target,"device_id")).append(" — ")
                    .append(str(target,"profile_id")).append(" v").append(num(target,"profile_version"))
                    .append(" — ").append(str(target,"mode")).append('\n');
        }
        Map<String,Object> data = object(parse(publicData,PublisherReview.MAX_PUBLIC_DATA));
        text.append("Events:\n");
        for (Object item : array(data.get("events"))) {
            Map<String,Object> event = object(item);
            text.append("  #").append(num(event,"id")).append(' ').append(str(event,"title"))
                    .append(" (").append(event.get("event_date")==null?"":str(event,"event_date")).append(")\n");
        }
        text.append("Package ").append(str(plan,"publication_sha256").substring(0,32)).append("…\n");
        return text.toString();
    }

    private void sign() {
        if ((document == null && pageDocument == null) || (pageDocument != null && pageFiles == null)
                || documentToken != loadToken.get() || key == null || state == null) {
            show("Load and verify the exact candidate before publishing.");
            return;
        }
        try {
            if (!state.pending().isEmpty()) {
                show("A signed approval is already stored. Retry or discard it before signing "
                        + "another plan.");
                return;
            }
        } catch (Exception failure) {
            show("Publisher state unavailable: " + failure.getMessage());
            return;
        }
        if (!confirmed.isChecked()) {
            Toast.makeText(this,"Confirm the reviewed facts first.",Toast.LENGTH_SHORT).show();
            return;
        }
        publish.setEnabled(false);
        final Map<String,Object> reviewed = document, reviewedPage = pageDocument;
        final Map<String,PageReleaseProtocol.Files> reviewedFiles = pageFiles;
        final String nativeToken = pageToken;
        final String nativeContentOrigin = pageContentOrigin;
        final String nativeMaintenanceOrigin = pageMaintenanceOrigin;
        final long nativeExpires = pageExpires;
        final boolean consented = confirmed.isChecked();
        final byte[] data = publicData;
        final int token = loadToken.get();
        worker.execute(() -> {
            try {
                need(token == loadToken.get());
                if (reviewedPage != null) {
                    need(nativeToken != null && nativeContentOrigin != null && nativeMaintenanceOrigin != null);
                    Map<String,Object> plan = PublisherReview.reviewPage(reviewedPage, reviewedFiles, now(), state.heads(),
                            PageReleaseProtocol.SHIPPED_JS_SHA256, PageReleaseProtocol.SHIPPED_CSS_SHA256);
                    need(token == loadToken.get());
                    verifyPageAuthority(plan);
                    need(token == loadToken.get());
                    requireNativeTicket(nativeToken, nativeContentOrigin, nativeMaintenanceOrigin,
                            nativeExpires);
                    Map<String,Object> approval = PublisherEnvelope.signPage(key, plan);
                    String identity = str(plan,"id");
                    Map<String,Object> body = NativePageProtocol.approveBody(identity, approval,
                            array(authority.get("chain")), consented);
                    state.recordPending(identity,approval,array(authority.get("chain")),
                            LocalView.digest(PublisherAuthority.canonical(reviewedPage)));
                    submitNativePage(body, identity, nativeToken);
                    return;
                }
                Map<String,Object> plan = PublisherReview.verify(reviewed, data, now(),
                        state.heads(), key.publicKey());
                need(token == loadToken.get());
                Map<String,Object> approval = PublisherEnvelope.sign(key,"publication",plan);
                String identity = str(plan,"id");
                Map<String,Object> body = new LinkedHashMap<>();
                body.put("id",identity); body.put("approval",approval);
                body.put("chain",array(authority.get("chain")));
                state.recordPending(identity,approval,array(authority.get("chain")),
                        LocalView.digest(PublisherAuthority.canonical(reviewed)));
                submit(body,identity);
            } catch (Exception failure) {
                publish.setEnabled(true);
                show("Publish refused: " + failure.getMessage());
            }
        });
    }

    /** Recheck installed policy/grant possession, exact local identity and page scope. */
    private void verifyPageAuthority(Map<String,Object> plan)throws Exception{
        if(storedBundle==null)throw new IOException("publisher_authority_missing");
        verifyBundle(storedBundle,state.policyFloor());
        need(str(plan,"group_id").equals(str(authority,"group_id"))
            &&str(plan,"origin").equals(str(authority,"origin"))
            &&str(plan,"user_id").equals(str(grant,"user_id"))
            &&str(plan,"device_id").equals(PublisherAuthority.keyId(key.publicKey()))
            &&num(plan,"policy_version")==policyVersion);
        need(PageReleaseProtocol.scopeAllows(grant,plan));
    }

    private void discardPending() {
        worker.execute(() -> {
            try {
                state.clearPending();
                clearPageSession();
                runOnUiThread(() -> { retry.setEnabled(false); discard.setEnabled(false); });
                show("Stored approval discarded. Nothing was submitted; review again to publish.");
            } catch (Exception failure) {
                show("Discard failed: " + failure.getMessage());
            }
        });
    }

    private void retryPending() {
        worker.execute(() -> {
            try {
                Map<String,Object> pending = state.pending();
                if (pending.isEmpty()) throw new IOException("publisher_retry_empty");
                String identity = str(pending,"id");
                Map<String,Object> approval = obj(pending,"approval");
                List<Object> chain = array(pending.get("chain"));
                if (pageToken != null) {
                    String ticket = NativePageProtocol.retryTicket(pageToken);
                    Map<String,Object> body = NativePageProtocol.approveBody(identity, approval, chain, true);
                    submitNativePage(body, identity, ticket);
                } else if ("page-publication".equals(approvalKind(approval))) {
                    throw new IOException("native_page_ticket_required");
                } else {
                    Map<String,Object> body = new LinkedHashMap<>();
                    body.put("id",identity); body.put("approval",approval);
                    body.put("chain",chain);
                    submit(body,identity);
                }
            } catch (Exception failure) {
                show("Retry refused: " + failure.getMessage());
            }
        });
    }

    /** The token is never persisted; a reopened native handoff supplies a fresh ticket. */
    private static String approvalKind(Map<String,Object> envelope)throws Exception{
        Map<String,Object> outer = object(parse(b64(str(envelope,"payload"),32768),32768));
        return str(outer,"kind");
    }

    private static boolean pagePending(Map<String,Object> pending){
        try{return "page-publication".equals(approvalKind(obj(pending,"approval")));}
        catch(Exception malformed){return false;}
    }

    private void requireNativeTicket(String token,String contentOrigin,String maintenanceOrigin,
            long expires)throws Exception{
        NativePageProtocol.openValue(token, contentOrigin, maintenanceOrigin);
        need(expires > now());
        need(str(authority,"origin").equals(contentOrigin));
        need(maintenanceEndpoint().equals(maintenanceOrigin));
    }

    private void submitNativePage(Map<String,Object> body,String identity,String token) {
        try {
            need(pageMaintenanceOrigin != null);
            String maintenanceCa = state.maintenanceCa();
            need(!maintenanceCa.isEmpty());
            CandidateClient client = new CandidateClient(pageMaintenanceOrigin, token, maintenanceCa);
            Map<String,Object> result = client.nativeApprove(body);
            state.commit(identity,policyVersion);
            Object distribution = result.get("distribution");
            String report = "Maintenance accepted this exact device-signed plan. "
                    + "Activation is acknowledged only by the display client.";
            if (distribution instanceof Map) {
                Map<String,Object> status = object(distribution);
                if ("ready".equals(str(status,"state"))) {
                    report += " Distribution ready for " + num(status,"targets") + " target(s).";
                } else {
                    report += " Distribution pending: " + str(status,"error")
                            + ". Exact retry stays available while this ticket is valid.";
                }
            }
            runOnUiThread(() -> { retry.setEnabled(false); discard.setEnabled(false); publish.setEnabled(false); });
            clearPageSession();
            show(report);
        } catch (Exception failure) {
            String message = failure.getMessage() == null ? "" : failure.getMessage();
            int status = httpStatus(message);
            if (status == 409 || terminalStatus(status)) {
                try { state.clearPending(); } catch (Exception ignored) {}
                clearPageSession();
                runOnUiThread(() -> {
                    retry.setEnabled(false); discard.setEnabled(false); publish.setEnabled(false);
                });
                show("Maintenance refused this review (" + message + "). The reviewed plan changed "
                        + "or the ticket is no longer valid; reopen a new native handoff ticket.");
                return;
            }
            runOnUiThread(() -> { retry.setEnabled(true); discard.setEnabled(true); });
            show("Approval signed and stored, but Maintenance submission failed: " + message
                    + ". Use Retry; the exact signed approval is reused while this ticket is valid.");
        }
    }

    private void clearPageSession() {
        document = null; pageDocument = null; pageFiles = null; publicData = null;
        pageToken = null; pageContentOrigin = null; pageMaintenanceOrigin = null;
        pageExpires = 0;
    }

    /** A definitive refusal can never become the same accepted plan. */
    private static boolean terminalStatus(int status) {
        return status == 400 || status == 401 || status == 403 || status == 404
                || status == 410 || status == 422;
    }

    private static int httpStatus(String message) {
        int at = message == null ? -1 : message.indexOf("publisher_http_");
        if (at < 0) return 0;
        int start = at + "publisher_http_".length();
        int end = start;
        while (end < message.length() && Character.isDigit(message.charAt(end))) end++;
        try {
            return Integer.parseInt(message.substring(start, end));
        } catch (Exception malformed) {
            return 0;
        }
    }

    /** Combined mode defaults to the configured authority origin; separated mode is explicit. */
    private String maintenanceEndpoint()throws Exception{
        String configured = state == null ? "" : state.maintenanceOrigin();
        return configured.isEmpty() ? str(authority,"origin") : configured;
    }

    private void setMaintenanceOrigin() {
        if (state == null) { show("Publisher key is not ready."); return; }
        worker.execute(() -> {
            try {
                String current = state.maintenanceOrigin();
                runOnUiThread(() -> {
                    EditText input = new EditText(this);
                    input.setSingleLine(true);
                    input.setHint("https://maintenance.example:443 (empty clears)");
                    input.setText(current);
                    new AlertDialog.Builder(this).setTitle("Trusted Maintenance origin")
                            .setMessage("Enter the exact HTTPS origin used only for native page tickets. "
                                    + "The origin is never inferred from a link or server response.")
                            .setView(input).setNegativeButton("Cancel", null)
                            .setPositiveButton("Save", (dialog, which) -> worker.execute(() -> {
                                try {
                                    String value = input.getText().toString().trim();
                                    if (!value.isEmpty()) NativePageProtocol.origin(value);
                                    state.setMaintenanceOrigin(value);
                                    show(value.isEmpty()
                                            ? "Maintenance origin cleared; combined mode uses the publisher authority origin."
                                            : "Trusted Maintenance origin saved.");
                                } catch (Exception failure) {
                                    show("Maintenance origin refused: " + failure.getMessage());
                                }
                            })).show();
                });
            } catch (Exception failure) {
                show("Publisher state unavailable: " + failure.getMessage());
            }
        });
    }

    /** One public CA PEM pins the native Maintenance origin; a system/user CA is not used. */
    private void setMaintenanceCa() {
        if (state == null) { show("Publisher key is not ready."); return; }
        worker.execute(() -> {
            try {
                String current = state.maintenanceCa();
                runOnUiThread(() -> {
                    EditText input = new EditText(this);
                    input.setSingleLine(false);
                    input.setMinLines(4);
                    input.setHint("-----BEGIN CERTIFICATE-----\n... (empty clears)");
                    input.setText(current);
                    new AlertDialog.Builder(this).setTitle("Trusted Maintenance CA")
                            .setMessage("Paste exactly one public CA certificate PEM. Native page "
                                    + "tickets trust only this CA, never a user-installed CA. "
                                    + "Compare the SHA256 shown after saving through an independent channel.")
                            .setView(input).setNegativeButton("Cancel", null)
                            .setPositiveButton("Save", (dialog, which) -> worker.execute(() -> {
                                try {
                                    String value = input.getText().toString().trim();
                                    if (value.isEmpty()) {
                                        state.setMaintenanceCa("");
                                        show("Maintenance CA cleared; native page tickets are refused.");
                                    } else {
                                        String fingerprint = MaintenanceTrust.fingerprint(value);
                                        state.setMaintenanceCa(value);
                                        show("Trusted Maintenance CA saved. SHA256 " + fingerprint + ".");
                                    }
                                } catch (Exception failure) {
                                    show("Maintenance CA refused: " + failure.getMessage());
                                }
                            })).show();
                });
            } catch (Exception failure) {
                show("Publisher state unavailable: " + failure.getMessage());
            }
        });
    }

    private void submit(Map<String,Object> body,String identity) {
        try {
            CandidateClient client = new CandidateClient(authority);
            Map<String,Object> result = client.approve(body);
            need("approved".equals(str(result,"state")));
            state.commit(identity,policyVersion);
            Object distribution = result.get("distribution");
            String report = "Signed approval stored; the server accepted this exact device signature.";
            if (distribution instanceof Map) {
                Map<String,Object> status = object(distribution);
                if ("ready".equals(str(status,"state"))) {
                    report += " Distribution ready for " + num(status,"targets") + " display(s).";
                } else {
                    report += " Distribution pending: " + str(status,"error")
                            + ". Retry from the browser session that prepared it.";
                }
            }
            runOnUiThread(() -> { retry.setEnabled(false); discard.setEnabled(false); publish.setEnabled(false); });
            document = null; pageDocument = null; pageFiles = null; publicData = null;
            show(report);
        } catch (Exception failure) {
            runOnUiThread(() -> { retry.setEnabled(true); discard.setEnabled(true); });
            show("Approval signed and stored, but submission failed: " + failure.getMessage()
                    + " Use Retry; the same signed approval is reused.");
        }
    }

    private void login(String token) {
        if (token == null || !token.matches("[a-f0-9]{64}")) { show("Login link refused."); return; }
        worker.execute(() -> {
            try {
                CandidateClient client = new CandidateClient(authority);
                Map<String,Object> context = client.challenge(token);
                need(str(context,"origin").equals(str(authority,"origin")));
                final String message = "Origin: " + str(context,"origin") + "\nBrowser: "
                        + str(context,"summary") + "\nConfirmation: "
                        + str(context,"id").substring(0,8).toUpperCase(Locale.ROOT)
                        + "\n\nAccepting authorizes this browser session as "
                        + str(grant,"user_id") + " with your existing role.";
                runOnUiThread(() -> new AlertDialog.Builder(this)
                        .setTitle("Approve browser login?")
                        .setMessage(message)
                        .setNegativeButton("Cancel", null)
                        .setPositiveButton("Accept", (dialog, which) -> worker.execute(() -> {
                            try {
                                Map<String,Object> approval = PublisherEnvelope.sign(key,"login",context);
                                client.acceptLogin(token,approval,array(authority.get("chain")));
                                show("Browser login accepted. Return to the browser; it now has "
                                        + "your existing role for draft editing.");
                            } catch (Exception failure) {
                                show("Login refused: " + failure.getMessage());
                            }
                        })).show());
            } catch (Exception failure) {
                show("Login refused: " + failure.getMessage());
            }
        });
    }

    private void show(String text) {
        runOnUiThread(() -> status.setText(text));
    }

    @Override protected void onDestroy() {
        worker.shutdownNow();
        super.onDestroy();
    }
}
