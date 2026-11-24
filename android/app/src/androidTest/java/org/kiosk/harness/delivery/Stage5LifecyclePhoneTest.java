package org.kiosk.harness.delivery;

import android.content.Context;
import android.os.SystemClock;
import android.provider.Settings;
import android.test.InstrumentationTestCase;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.json.JSONObject;
import org.kiosk.harness.binding.CapturedCandidate;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.storage.PreparedAdmission;

/**
 * Physical Android lifecycle acceptance against the retained isolated pilot.
 *
 * <p>Uses an in-memory store: no retained installation data, trust or credential is
 * modified. The test still performs real native TLS, real administrator approval, a real
 * publication capture and a real server revocation refusal, then proves the accepted
 * offline content reopens without network. The pairing code is written to an app file so
 * an independent administrator can approve it; the test itself never approves anything.</p>
 */
@SuppressWarnings("deprecation")
public final class Stage5LifecyclePhoneTest extends InstrumentationTestCase {
    private static final class Memory implements DeliveryIO.Store {
        JSONObject saved = new JSONObject();
        public JSONObject read() throws Exception { return new JSONObject(saved.toString()); }
        public void write(JSONObject value) throws Exception { saved = new JSONObject(value.toString()); }
    }
    private Context app() { return getInstrumentation().getTargetContext(); }
    private final DeliveryIO.Clock clock = new DeliveryIO.Clock() {
        public long now() { return System.currentTimeMillis() / 1000; }
        public long elapsed() { return SystemClock.elapsedRealtime(); }
        public int boot() { return Settings.Global.getInt(app().getContentResolver(), Settings.Global.BOOT_COUNT, -1); }
        public boolean automatic() { return Settings.Global.getInt(app().getContentResolver(), Settings.Global.AUTO_TIME, 0) == 1; }
    };
    private void report(String name, JSONObject value) throws Exception {
        try (java.io.FileOutputStream out = app().openFileOutput(name, 0)) {
            out.write(value.toString(2).getBytes(StandardCharsets.UTF_8));
        }
        System.out.println("STAGE5 " + name + " " + value.toString());
    }
    private boolean waitFor(File sentinel, long seconds) throws Exception {
        long deadline = SystemClock.elapsedRealtime() + seconds * 1000;
        while (SystemClock.elapsedRealtime() < deadline) {
            if (sentinel.isFile()) return true;
            Thread.sleep(1000);
        }
        return false;
    }
    public void testEnrollmentSyncRevocationAndOfflineReopen() throws Exception {
        byte[] bootstrap;
        try (java.io.InputStream in = getInstrumentation().getContext().getAssets()
                .open("delivery-bootstrap-pilot.json")) {
            bootstrap = LocalView.readBounded(in, 16384);
        }
        Memory store = new Memory();
        DeliveryClient client = new DeliveryClient(app(), store, NativeTransport::new, clock,
                (r, p, k, t) -> CapturedCandidate.capture(app(), p, k, t, r.pkg(), r.renderer(),
                        r.kiosk(), r.tv(), r.storage(), new CapturedCandidate.Cancellation()));
        client.confirm(bootstrap);
        client.authorize();
        String code = client.humanCode();
        assertTrue("pairing code", code.matches("[A-Z2-9]{8}"));
        report("phone-stage5-stage1.json", new JSONObject()
                .put("phase", "pending_approval").put("code", code)
                .put("origin", client.trustedOrigin())
                .put("bootstrap_sha256", LocalView.digest(bootstrap)));

        long deadline = SystemClock.elapsedRealtime() + 240000;
        String approval = "pending";
        while (SystemClock.elapsedRealtime() < deadline) {
            approval = client.poll();
            if ("approved".equals(approval)) break;
            if ("denied".equals(approval) || "expired".equals(approval)) break;
            Thread.sleep(5000);
        }
        assertEquals("approved", approval);

        DeliveryClient.Download downloaded = client.download();
        assertNotNull("first real publication must be captured", downloaded);
        PreparedAdmission.Request request;
        String packageId;
        try (var captured = downloaded.capture()) {
            request = downloaded.request();
            packageId = captured.report().callerAttestedCanonicalPackageIdentity();
            client.verify(request, PreparedAdmission.Phase.NEW_ACTIVATION);
        }
        client.queueReady(packageId, "tv", "stage5-physical-session");
        JSONObject ready = new JSONObject()
                .put("phase", "ready_then_expect_revocation").put("package_id", packageId)
                .put("generation", store.saved.getLong("assignment_generation"))
                .put("device_sha256", LocalView.digest(store.saved.getString("device").getBytes(StandardCharsets.UTF_8)))
                .put("credential_expires", store.saved.getLong("credential_expires"))
                .put("trust_generation", store.saved.getLong("trust_generation"))
                .put("trust_issuer", store.saved.getString("trust_issuer"))
                .put("accepted_count", store.saved.getJSONObject("accepted").length());
        report("phone-stage5-stage2.json", ready);

        // The administrator revokes this device from the authenticated panel while the
        // test waits. Nothing in the client is changed to fake the refusal.
        File release = new File(app().getFilesDir(), "phone-stage5-continue");
        waitFor(release, 60);
        if (release.isFile()) release.delete();

        String refusal = "none";
        try {
            client.download();
            refusal = "unexpected_success";
        } catch (Exception expected) {
            refusal = String.valueOf(expected.getMessage());
        }
        JSONObject refused = new JSONObject()
                .put("phase", "refusal").put("reason", refusal)
                .put("recovery", client.credentialRecovery())
                .put("server_error", client.credentialError())
                .put("credential_retained", store.saved.has("credential"))
                .put("identity_retained", store.saved.has("device"))
                .put("accepted_retained", store.saved.getJSONObject("accepted").has(packageId));
        report("phone-stage5-stage3.json", refused);
        assertEquals("credential_revoked", client.credentialRecovery());
        assertEquals("invalid_credential", client.credentialError());
        assertTrue(store.saved.has("credential"));
        assertTrue(store.saved.getJSONObject("accepted").has(packageId));

        // Accepted offline content is still admissible with no network authority.
        client.verify(request, PreparedAdmission.Phase.PRIVATE_REOPEN);
        report("phone-stage5-stage4.json", new JSONObject()
                .put("phase", "offline_reopen_after_revocation")
                .put("package_id", packageId).put("verified", true)
                .put("diagnostics", client.diagnostics()));
    }
}
