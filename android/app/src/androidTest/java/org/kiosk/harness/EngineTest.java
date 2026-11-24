package org.kiosk.harness;

import android.content.Intent;
import android.test.InstrumentationTestCase;
import android.view.KeyEvent;
import android.webkit.WebView;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;
import java.io.InputStream;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import org.json.JSONObject;
import org.json.JSONArray;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.core.OriginPolicy;

/** Real target WebView tests; no fixture packages or Python verifier results are executed here. */
@SuppressWarnings("deprecation")
public class EngineTest extends InstrumentationTestCase {
    private HarnessActivity activity;
    private HarnessActivity launch(String fixture, String expected) throws Exception {
        Intent intent = new Intent(getInstrumentation().getTargetContext(), HarnessActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        intent.putExtra("fixture", fixture);
        activity = (HarnessActivity)getInstrumentation().startActivitySync(intent);
        long deadline = android.os.SystemClock.elapsedRealtime() + 22000;
        while (activity.state.equals("loading") && android.os.SystemClock.elapsedRealtime() < deadline) Thread.sleep(50);
        assertEquals(expected, activity.state);
        long focusDeadline = android.os.SystemClock.elapsedRealtime() + 5000;
        while (!activity.hasWindowFocus() && android.os.SystemClock.elapsedRealtime() < focusDeadline) Thread.sleep(50);
        assertTrue("Activity window focus",activity.hasWindowFocus());
        return activity;
    }
    private String evaluate(String script) throws Exception {
        CountDownLatch done = new CountDownLatch(1);
        AtomicReference<String> result = new AtomicReference<>();
        getInstrumentation().runOnMainSync(() -> activity.prepared.browser.evaluateJavascript(script, value -> { result.set(value);done.countDown(); }));
        assertTrue("JavaScript callback", done.await(5,TimeUnit.SECONDS));
        return result.get();
    }
    private void close() {
        if (activity != null) { getInstrumentation().runOnMainSync(activity::finish);getInstrumentation().waitForIdleSync();activity=null; }
    }
    @Override protected void tearDown() throws Exception { close();super.tearDown(); }
    public void testFourPreparedViews() throws Exception {
        for (String name : FixtureCatalog.NAMES) {
            launch(name,"ready");
            assertEquals("true",evaluate(PreparedWebView.DOM_PROBE));
            assertEquals(name.startsWith("empty-") ? "\"0 / 0\"" : name.startsWith("two-card-") ? "\"1 / 2\"" : "\"1 / 1\"",evaluate("document.getElementById('counter').textContent"));
            assertEquals("true",evaluate("Array.from(document.images).every(i => i.complete && i.naturalWidth > 0)"));
            assertTrue(activity.prepared.served.get() >= 3);
            android.util.Log.i("EventsHarnessTest","view PASS "+name+" served="+activity.prepared.served.get());
            close();
        }
    }
    public void testSafeUnknownFixture() throws Exception { launch("../../unknown","failed");assertNull(activity.prepared); }
    public void testLocalDenialsNoFallback() throws Exception {
        launch("valid-kiosk","ready");
        PreparedWebView p=activity.prepared;
        assertEquals(200,p.response(OriginPolicy.INDEX,"GET",true).getStatusCode());
        for(String address:new String[]{"https://example.com/x",OriginPolicy.ORIGIN+"/missing",OriginPolicy.ORIGIN+"/view.json","file:///etc/hosts","content://local/x",OriginPolicy.INDEX+"?x=1",OriginPolicy.ORIGIN+"/static%2fuploads/card.png"})
            assertEquals(403,p.response(address,"GET",false).getStatusCode());
        assertEquals(403,p.response(OriginPolicy.INDEX,"POST",true).getStatusCode());
        assertEquals(403,p.response(OriginPolicy.ORIGIN+"/events.js","GET",true).getStatusCode());
        assertFalse(activity.getPackageManager().getPackageInfo(activity.getPackageName(),android.content.pm.PackageManager.GET_PERMISSIONS).requestedPermissions != null);
    }
    public void testEngineNavigationAndBridgeDenials() throws Exception {
        launch("valid-kiosk","ready");
        android.util.Log.i("EventsHarnessTest","bridge diagnostic="+evaluate("JSON.stringify({android:typeof window.android,value:String(window.android),names:Object.getOwnPropertyNames(window.android||{}),proto:String(Object.getPrototypeOf(window.android||{})),chrome:typeof window.chrome,webview:typeof window.chrome?.webview})"));
        // This provider exposes a built-in [object Android] namespace; it is not an app Java bridge.
        assertEquals("\"undefined\"",evaluate("typeof window.android?.getClass"));
        assertEquals("\"undefined\"",evaluate("typeof window.chrome?.webview"));
        for(String url:new String[]{"https://example.com/forbidden","https://kiosk.invalid/missing","file:///etc/hosts","content://local/x","intent://untrusted"}) {
            int before=activity.prepared.blockedNavigation.get();
            evaluate("location.href="+org.json.JSONObject.quote(url));
            long end=android.os.SystemClock.elapsedRealtime()+2000;
            while(activity.prepared.blockedNavigation.get()==before && android.os.SystemClock.elapsedRealtime()<end)Thread.sleep(25);
            assertEquals("ready",activity.state);
            assertEquals("\""+OriginPolicy.INDEX+"\"",evaluate("location.href"));
            android.util.Log.i("EventsHarnessTest","navigation refused "+url+" callbackDelta="+(activity.prepared.blockedNavigation.get()-before));
        }
        assertEquals("true",evaluate("window.open('https://example.com') === null"));
        assertEquals("true",evaluate("!('nativeBridge' in window)"));
        getInstrumentation().runOnMainSync(()->{
            assertFalse(activity.prepared.browser.getSettings().getAllowFileAccess());
            assertFalse(activity.prepared.browser.getSettings().getAllowContentAccess());
        });
    }
    public void testDpadKioskFocusAndSelection() throws Exception {
        launch("valid-kiosk","ready");
        // Platform focus traversal only: do not patch renderer tabindex/CSS or add custom key mapping.
        String focus="\"\"";
        for(int key:new int[]{KeyEvent.KEYCODE_DPAD_DOWN,KeyEvent.KEYCODE_DPAD_DOWN,KeyEvent.KEYCODE_DPAD_RIGHT}) {
            getInstrumentation().sendKeyDownUpSync(key);
            getInstrumentation().waitForIdleSync();
            Thread.sleep(150);
            focus=evaluate("document.activeElement.id");
            android.util.Log.i("EventsHarnessTest","focus key="+key+" element="+focus+" diagnostics="+evaluate("JSON.stringify({tag:document.activeElement.tagName,focus:document.hasFocus()})")+" native="+activity.prepared.browser.hasFocus());
        }
        android.util.Log.i("EventsHarnessTest","D-pad focus="+focus);
        assertEquals("\"BUTTON\"",evaluate("document.activeElement.tagName"));
        assertEquals("true",evaluate("document.activeElement.matches(':focus-visible')"));
        getInstrumentation().sendKeyDownUpSync(KeyEvent.KEYCODE_DPAD_CENTER);
        // Native input delivery and the renderer's DOM update need not finish in the same turn.
        long selectionDeadline=android.os.SystemClock.elapsedRealtime()+3000;
        String selected=evaluate("document.activeElement.getAttribute('aria-pressed') === 'true'");
        while(!"true".equals(selected)&&android.os.SystemClock.elapsedRealtime()<selectionDeadline){
            Thread.sleep(25);selected=evaluate("document.activeElement.getAttribute('aria-pressed') === 'true'");
        }
        assertEquals("true",selected);
        assertEquals("true",evaluate(PreparedWebView.DOM_PROBE));
        assertEquals("ready",activity.state);
    }
    public void testSingleCardTvReadinessAndHiddenControls() throws Exception {
        launch("valid-tv","ready");
        getInstrumentation().sendKeyDownUpSync(KeyEvent.KEYCODE_DPAD_DOWN);
        assertEquals("true",evaluate("document.getElementById('home').hidden"));
        assertEquals("true",evaluate(PreparedWebView.DOM_PROBE));
        android.util.Log.i("EventsHarnessTest","TV D-pad observed focus="+evaluate("document.activeElement.id"));
    }
    private LocalView.Source memory(Map<String,byte[]> bytes) {
        return new LocalView.Source() {
            public InputStream open(String name) throws IOException {
                if(!bytes.containsKey(name))throw new IOException("missing");
                return new ByteArrayInputStream(bytes.get(name));
            }
            public Set<String> files() { return bytes.keySet(); }
        };
    }
    private Map<String,byte[]> fixtureBytes() throws Exception {
        AssetViewSource source=new AssetViewSource(getInstrumentation().getTargetContext().getAssets(),"valid-kiosk");
        Map<String,byte[]> bytes=new HashMap<>();
        for(String name:source.files())bytes.put(name,LocalView.readBounded(source.open(name),LocalView.FILE_LIMIT));
        return bytes;
    }
    private LocalView verify(Map<String,byte[]> bytes) throws Exception {
        return LocalView.verify(memory(bytes),FixtureCatalog.identity("valid-kiosk"),"kiosk",FixtureCatalog.JS,FixtureCatalog.CSS);
    }
    public void testAndroidParserAndIntegrityRefusals() throws Exception {
        for(String defect:new String[]{"schema-float","schema-bool","identity","extra","missing","hash","pin","descriptor","trailing"}) {
            Map<String,byte[]> bytes=fixtureBytes();
            JSONObject descriptor=new JSONObject(new String(bytes.get("view.json"),java.nio.charset.StandardCharsets.UTF_8));
            if(defect.equals("identity"))descriptor.put("package_sha256","0".repeat(64));
            if(defect.equals("extra"))bytes.put("extra.png",new byte[0]);
            if(defect.equals("missing"))bytes.remove("events.css");
            if(defect.equals("hash") || defect.equals("pin"))bytes.get("events.js")[0]^=1;
            if(defect.equals("pin")) {
                JSONArray rows=descriptor.getJSONArray("files");
                for(int i=0;i<rows.length();i++)if(rows.getJSONObject(i).getString("path").equals("events.js"))rows.getJSONObject(i).put("sha256",LocalView.digest(bytes.get("events.js")));
            }
            String json=descriptor.toString();
            if(defect.equals("schema-float"))json=json.replace("\"schema_version\":1","\"schema_version\":1.0");
            if(defect.equals("schema-bool"))json=json.replace("\"schema_version\":1","\"schema_version\":true");
            if(defect.equals("descriptor"))json="{";
            if(defect.equals("trailing"))json+=" trailing";
            bytes.put("view.json",json.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            try { verify(bytes);fail("Accepted "+defect); } catch(IOException expected) { assertEquals("invalid_local_view",expected.getMessage()); }
            android.util.Log.i("EventsHarnessTest","Android verifier refused "+defect);
        }
    }
    private void preparationProbe(LocalView view, boolean start, boolean expectedReady) throws Exception {
        launch("valid-kiosk","ready");
        CountDownLatch done=new CountDownLatch(1);
        AtomicReference<Boolean> result=new AtomicReference<>();
        AtomicReference<PreparedWebView> probe=new AtomicReference<>();
        long began=android.os.SystemClock.elapsedRealtime();
        getInstrumentation().runOnMainSync(()->{
            PreparedWebView candidate=new PreparedWebView(activity,view,999,new PreparedWebView.Completion(){
                public void ready(){result.set(true);done.countDown();}
                public void failed(){result.set(false);done.countDown();}
            });
            probe.set(candidate);
            activity.addContentView(candidate.browser,new android.view.ViewGroup.LayoutParams(-1,-1));
            if(start)candidate.start();
        });
        assertTrue("Bounded preparation completion",done.await(18,TimeUnit.SECONDS));
        long elapsed=android.os.SystemClock.elapsedRealtime()-began;
        assertEquals(Boolean.valueOf(expectedReady),result.get());
        if(!start)assertTrue("15s native deadline",elapsed>=14500 && elapsed<18000);
        android.util.Log.i("EventsHarnessTest","preparation start="+start+" ready="+result.get()+" elapsedMs="+elapsed);
        getInstrumentation().runOnMainSync(()->{
            PreparedWebView candidate=probe.get();
            candidate.dispose();
        });
    }
    public void testNavigationCompletionWithoutDomIsRefused() throws Exception {
        Map<String,byte[]> bytes=fixtureBytes();
        byte[] html=new String(bytes.get("index.html"),java.nio.charset.StandardCharsets.UTF_8).replace("id=\"counter\"","id=\"broken-counter\"").getBytes(java.nio.charset.StandardCharsets.UTF_8);
        bytes.put("index.html",html);
        JSONObject descriptor=new JSONObject(new String(bytes.get("view.json"),java.nio.charset.StandardCharsets.UTF_8));
        JSONArray rows=descriptor.getJSONArray("files");
        for(int i=0;i<rows.length();i++)if(rows.getJSONObject(i).getString("path").equals("index.html"))rows.getJSONObject(i).put("sha256",LocalView.digest(html)).put("size",html.length);
        bytes.put("view.json",descriptor.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
        preparationProbe(verify(bytes),true,false);
    }
    public void testPreparationDeadline() throws Exception { preparationProbe(verify(fixtureBytes()),false,false); }
    public void testEngineConnectIsBlockedByCsp() throws Exception {
        launch("valid-kiosk","ready");
        evaluate("document.body.dataset.connect='pending'; fetch('https://example.com/forbidden').then(()=>document.body.dataset.connect='unexpected').catch(()=>document.body.dataset.connect='denied')");
        long deadline=android.os.SystemClock.elapsedRealtime()+3000;
        String result;
        do { result=evaluate("document.body.dataset.connect");if(!result.equals("\"pending\""))break;Thread.sleep(25); } while(android.os.SystemClock.elapsedRealtime()<deadline);
        assertEquals("\"denied\"",result);
    }
}
