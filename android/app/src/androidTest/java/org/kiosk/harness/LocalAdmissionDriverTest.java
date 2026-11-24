package org.kiosk.harness;
import org.kiosk.harness.storage.FixturePublicationStore;
/** External ADB driver: select ONLY these individual methods. */
public class LocalAdmissionDriverTest extends LocalAdmissionTest {
    public void testSeedConfirmedC()throws Exception{
        external=true;launch(null,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);mode("kiosk");String c=install("C");assertEquals("ready",activity.state);assertEquals(c,activity.store.receipt("kiosk"));tap("home-button");screen("confirmed-C-home");tap("open-events");tap("next");assertEquals("\"2 / 2\"",eval("document.getElementById('counter').textContent"));screen("confirmed-C-two");mode("tv");rotation();screen("confirmed-C-tv");state("confirmed-C-ready");
    }
    public void testReplaceConfirmedB()throws Exception{
        external=true;launch(null,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);assertEquals("ready",activity.state);String b=install("B");assertEquals(b,activity.store.receipt("tv"));mode("kiosk");tap("next");assertEquals("\"2 / 2\"",eval("document.getElementById('counter').textContent"));screen("confirmed-B-two");state("confirmed-B-ready");
    }
}
