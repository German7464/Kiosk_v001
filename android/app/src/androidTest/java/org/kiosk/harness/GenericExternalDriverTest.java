package org.kiosk.harness;
import org.kiosk.harness.storage.FixturePublicationStore;
/** Explicit external ADB driver only; select individual methods, never a regression class scan. */
@SuppressWarnings("deprecation")
public class GenericExternalDriverTest extends GenericPlaybackTest {
    public void testSeedGenericC()throws Exception{
        external=true;launch(null,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);mode("kiosk");String c=install("C");assertEquals("ready",activity.state);assertEquals(c,activity.store.receipt("kiosk"));
        tap("home-button");assertEquals("false",eval("document.getElementById('home').hidden"));screen("external-C-home");tap("open-events");tap("next");assertEquals("\"2 / 2\"",eval("document.getElementById('counter').textContent"));screen("external-C-two");state("external-C-kiosk-ready");
    }
    public void testNextGenericBAndTV()throws Exception{
        external=true;launch(null,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);assertEquals("ready",activity.state);
        mode("tv");rotation();screen("external-C-tv-rotation");String b=install("B");assertEquals("ready",activity.state);assertEquals(b,activity.store.pointer());assertEquals(b,activity.store.receipt("tv"));state("external-B-tv-ready");
        mode("kiosk");tap("next");assertEquals("\"2 / 2\"",eval("document.getElementById('counter').textContent"));screen("external-B-kiosk-two");state("external-B-kiosk-ready");
    }
}
