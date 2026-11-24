package org.kiosk.harness.delivery;

import android.content.Context;
import android.test.InstrumentationTestCase;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;
import org.kiosk.harness.core.LocalView;

/** Explicitly selected phases against the real app-private encrypted store.
 * No fixture store, clock, wire or authority is injected. Each invocation is a
 * separate instrumentation process; ordinary activity reopening supplies the
 * separate physical renderer observation. Never run against the original app.
 */
@SuppressWarnings("deprecation")
public final class Stage5PersistentRecoveryTest extends InstrumentationTestCase {
    private Context app() {
        Context c = getInstrumentation().getTargetContext();
        assertEquals("org.kiosk.harness.sandbox", c.getPackageName());
        return c;
    }
    private JSONObject facts() throws Exception {
        JSONObject state = new PrivateDeliveryState(app()).read();
        assertTrue("existing enrollment only", state.has("bootstrap"));
        assertTrue("accepted content required", state.getJSONObject("accepted").length() > 0);
        // Compare full accepted associations and identity without exporting secrets.
        return new JSONObject().put("device_sha256", LocalView.digest(
                state.getString("device").getBytes(StandardCharsets.UTF_8)))
            .put("accepted", state.getJSONObject("accepted"))
            .put("diagnostics", new DeliveryClient(app()).diagnostics());
    }
    private void write(String name, JSONObject value) throws Exception {
        try (var out = app().openFileOutput(name, 0)) {
            out.write(value.toString(2).getBytes(StandardCharsets.UTF_8));
        }
    }
    private JSONObject baseline() throws Exception {
        try (var in = app().openFileInput("stage5-persistent-before.json")) {
            return new JSONObject(new String(LocalView.readBounded(in, 131072), StandardCharsets.UTF_8));
        }
    }
    private JSONObject preserved() throws Exception {
        JSONObject before = baseline(), after = facts();
        assertEquals(before.getString("device_sha256"), after.getString("device_sha256"));
        JSONObject prior = before.getJSONObject("accepted"), current = after.getJSONObject("accepted");
        for (var keys = prior.keys(); keys.hasNext();) {
            String id = keys.next();
            assertEquals(prior.getJSONObject(id).toString(), current.getJSONObject(id).toString());
        }
        return after;
    }
    public void test01RecordExistingPersistentState() throws Exception {
        write("stage5-persistent-before.json", facts());
    }
    public void test02ObserveRealRevocation() throws Exception {
        DeliveryClient client = new DeliveryClient(app());
        try {
            client.download();
            fail("expected authenticated server revocation refusal");
        } catch (java.io.IOException expected) {
            assertEquals("credential_revoked", client.credentialRecovery());
        }
        write("stage5-persistent-refused.json", preserved());
    }
    public void test03RefusalSurvivesProcessRestart() throws Exception {
        assertEquals("credential_revoked", new DeliveryClient(app()).credentialRecovery());
        write("stage5-persistent-restarted.json", preserved());
    }
    public void test04RequestExplicitRecovery() throws Exception {
        DeliveryClient client = new DeliveryClient(app());
        assertEquals("credential_revoked", client.credentialRecovery());
        client.reenroll();
        client.authorize();
        JSONObject value = preserved().put("code", client.humanCode());
        assertTrue(client.humanCode().matches("[A-Z2-9]{8}"));
        write("stage5-persistent-pending.json", value);
    }
    public void test05ObserveOrdinaryApproval() throws Exception {
        DeliveryClient client = new DeliveryClient(app());
        assertEquals("approved", client.poll());
        assertTrue(client.enrolled());
        assertEquals("", client.credentialRecovery());
        write("stage5-persistent-approved.json", preserved());
    }
}
