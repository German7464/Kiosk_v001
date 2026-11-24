package org.kiosk.harness;
import android.os.SystemClock;
import java.nio.charset.StandardCharsets;
import org.json.JSONObject;
import org.kiosk.harness.storage.*;
/** Bounded test-only live-process rendezvous. Host must externally stop this exact package. */
public class LocalAdmissionExternalDriverTest extends GenericPlaybackTest {
    public void testHoldSavedBForExternalStop()throws Exception {
        external=true;HarnessTestRunner.nextAdmissionVerifier.set(()->PreparedTestInputs.TEST_ONLY_ISSUER);
        launch(null,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);
        assertEquals("ready",activity.state);assertEquals("tv",activity.visibleMode);
        assertEquals("a5cd7292f96e8734b394124942a852874a214f4c25a84e8c898a7e93bc468fc6",activity.visible);
        assertFalse(activity.store.developmentAuthorized(activity.visible));state("external-live-B");screen("admitted-live-B");
        try(var out=getInstrumentation().getTargetContext().openFileOutput("admission-external-hold.json",0)){
            out.write(new JSONObject().put("pid",android.os.Process.myPid()).put("identity",activity.visible).put("issuer","TEST_ONLY_ISSUER").toString().getBytes(StandardCharsets.UTF_8));
        }
        long end=SystemClock.elapsedRealtime()+90000;
        while(SystemClock.elapsedRealtime()<end)Thread.sleep(100);
        fail("Host did not perform authorized external force-stop within bounded hold");
    }
}
