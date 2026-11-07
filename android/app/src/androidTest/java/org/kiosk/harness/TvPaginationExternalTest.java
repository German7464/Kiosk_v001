package org.kiosk.harness;
import java.nio.file.Files;
import org.json.JSONObject;
import org.kiosk.harness.storage.FixturePublicationStore;
/** Default-store driver: select ONLY this method; never a class scan. */
public class TvPaginationExternalTest extends TvPaginationTest {
    public void testSeedNewRendererPrivatePublication()throws Exception{
        external=true;launch(null,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);mode("kiosk");String id=install("two-events");assertEquals("ready",activity.state);assertEquals(id,activity.store.receipt("kiosk"));tap("next");assertEquals("\"2 / 2\"",eval("document.getElementById('counter').textContent"));snap("EXTERNAL-new-renderer-kiosk-next");screen("pagination-EXTERNAL-kiosk-next");
        mode("tv");assertEquals("ready",activity.state);JSONObject s=snap("EXTERNAL-new-renderer-TV-part-one");assertTrue(s.getString("part").contains("1"));JSONObject receipt=new JSONObject(new String(org.kiosk.harness.core.LocalView.readBounded(Files.newInputStream(activity.store.root.resolve("last-ready-tv.json")),4096),java.nio.charset.StandardCharsets.UTF_8));assertEquals("b55c9bdc54af16ce69b6b6b6be15375adc5891dc70b84eb2292de00cd59d49a6",receipt.getString("renderer"));screen("pagination-EXTERNAL-TV-part-one");
    }
}
