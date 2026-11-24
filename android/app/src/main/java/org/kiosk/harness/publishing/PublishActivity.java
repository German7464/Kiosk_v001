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
        requestButton.setOnClickListener(view -> exportRequest());
        publish.setOnClickListener(view -> sign());
        retry.setOnClickListener(view -> retryPending());
        discard.setOnClickListener(view -> discardPending());
        cancel.setOnClickListener(view -> {
            loadToken.incrementAndGet();
            document = null; publicData = null;
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
            if (!str(authority,"origin").equals(fragment.get("origin"))) {
                throw new IOException("publisher_origin_refused");
            }
            String path = uri.getPath();
            if ("/publish".equals(path)) {
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
                text.append("\nA signed approval is stored and awaiting submission. Use Retry.");
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
        document = null; publicData = null; publish.setEnabled(false);
        worker.execute(() -> {
            try {
                CandidateClient client = new CandidateClient(authority);
                Map<String,Object> loaded = client.candidate(identity);
                byte[] data = client.publicData(identity);
                Map<String,Object> plan = PublisherReview.verify(loaded, data, now(),
                        state.heads(), key.publicKey());
                if (token != loadToken.get()) return;
                document = loaded; publicData = data; documentToken = token;
                show(summary(plan, loaded));
                runOnUiThread(() -> { confirmed.setChecked(false); publish.setEnabled(true); });
            } catch (Exception failure) {
                if (token != loadToken.get()) return;
                document = null;
                show("Candidate refused: " + failure.getMessage());
            }
        });
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
        if (document == null || documentToken != loadToken.get() || key == null || state == null) {
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
        final Map<String,Object> reviewed = document;
        final byte[] data = publicData;
        final int token = loadToken.get();
        worker.execute(() -> {
            try {
                need(token == loadToken.get());
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

    private void discardPending() {
        worker.execute(() -> {
            try {
                state.clearPending();
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
                Map<String,Object> body = new LinkedHashMap<>();
                body.put("id",str(pending,"id")); body.put("approval",obj(pending,"approval"));
                body.put("chain",array(pending.get("chain")));
                submit(body,str(pending,"id"));
            } catch (Exception failure) {
                show("Retry refused: " + failure.getMessage());
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
            document = null;
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
