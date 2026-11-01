package org.kiosk.harness;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Build;
import android.os.SystemClock;
import android.test.InstrumentationTestCase;
import android.webkit.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.json.*;

/** Measurement only: no production decoder policy and no assertion of Pillow parity. */
@SuppressWarnings("deprecation")
public final class ImageParityTest extends InstrumentationTestCase {
    private static final String ORIGIN="https://image-test.invalid";
    private byte[] asset(String path) throws Exception {
        try(InputStream in=getInstrumentation().getContext().getAssets().open(path)) {
            byte[] result=in.readNBytes(2*1024*1024+1);
            assertTrue("small corpus bound",result.length<=2*1024*1024);
            return result;
        }
    }
    private static String hash(byte[] bytes) throws Exception {
        StringBuilder out=new StringBuilder();
        for(byte b:MessageDigest.getInstance("SHA-256").digest(bytes))out.append(String.format(Locale.ROOT,"%02x",b&255));
        return out.toString();
    }
    private JSONObject decode(byte[] bytes, boolean bounds) throws Exception {
        JSONObject out=new JSONObject();Bitmap bitmap=null;
        BitmapFactory.Options options=new BitmapFactory.Options();
        options.inJustDecodeBounds=bounds; options.inScaled=false;
        long start=SystemClock.elapsedRealtime();
        try {
            bitmap=BitmapFactory.decodeByteArray(bytes,0,bytes.length,options);
            out.put("result",bounds?(options.outWidth>0&&options.outHeight>0?"bounds_available":"bounds_unavailable"):(bitmap==null?"null":"decoded"));
            out.put("width",options.outWidth).put("height",options.outHeight).put("mime",options.outMimeType==null?JSONObject.NULL:options.outMimeType);
            if(bitmap!=null)out.put("bitmap_width",bitmap.getWidth()).put("bitmap_height",bitmap.getHeight()).put("allocation_bytes",bitmap.getAllocationByteCount());
        } catch(RuntimeException error) { out.put("result","exception").put("exception_type",error.getClass().getSimpleName()); }
        finally { if(bitmap!=null)bitmap.recycle(); }
        return out.put("elapsed_ms",SystemClock.elapsedRealtime()-start);
    }
    private JSONObject web(byte[] bytes,String path) throws Exception {
        AtomicReference<WebView> owned=new AtomicReference<>();AtomicInteger served=new AtomicInteger(),denied=new AtomicInteger();
        String imageUrl=ORIGIN+"/"+path;
        String html="<!doctype html><meta charset='utf-8'><img id='i'><script>window.observation=null;let i=document.getElementById('i');function record(e){window.observation={event:e,naturalWidth:i.naturalWidth,naturalHeight:i.naturalHeight,complete:i.complete};}i.onload=()=>record('load');i.onerror=()=>record('error');i.src="+JSONObject.quote(imageUrl)+";</script>";
        long start=SystemClock.elapsedRealtime();
        try {
            getInstrumentation().runOnMainSync(()->{
                WebView view=new WebView(getInstrumentation().getTargetContext());owned.set(view);
                WebSettings settings=view.getSettings();settings.setJavaScriptEnabled(true);
                settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);settings.setBlockNetworkLoads(true);
                settings.setSupportMultipleWindows(false);settings.setJavaScriptCanOpenWindowsAutomatically(false);
                settings.setCacheMode(WebSettings.LOAD_NO_CACHE);settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
                view.setWebViewClient(new WebViewClient(){
                    @Override public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest request){return true;}
                    @Override public WebResourceResponse shouldInterceptRequest(WebView v,WebResourceRequest request){
                        String url=request.getUrl().toString();
                        if(request.getMethod().equals("GET")&&url.equals(ORIGIN+"/index.html"))
                            return response("text/html",html.getBytes(StandardCharsets.UTF_8),200);
                        if(request.getMethod().equals("GET")&&url.equals(imageUrl)){
                            served.incrementAndGet();return response("application/octet-stream",bytes,200);
                        }
                        denied.incrementAndGet();return response("text/plain",new byte[0],403);
                    }
                });
                view.loadUrl(ORIGIN+"/index.html");
            });
            long deadline=start+8000;
            while(SystemClock.elapsedRealtime()<deadline){
                CountDownLatch done=new CountDownLatch(1);AtomicReference<String> value=new AtomicReference<>();
                getInstrumentation().runOnMainSync(()->owned.get().evaluateJavascript("window.observation || null",s->{value.set(s);done.countDown();}));
                assertTrue("bounded JS response",done.await(2,TimeUnit.SECONDS));
                if(value.get()!=null&&!value.get().equals("null")) {
                    return new JSONObject(value.get()).put("image_requests",served.get()).put("denied_requests",denied.get()).put("elapsed_ms",SystemClock.elapsedRealtime()-start);
                }
                Thread.sleep(40);
            }
            return new JSONObject().put("event","timeout").put("image_requests",served.get()).put("denied_requests",denied.get());
        } finally {
            getInstrumentation().runOnMainSync(()->{
                WebView v=owned.getAndSet(null);
                if(v!=null){
                    if(v.getParent() instanceof android.view.ViewGroup)((android.view.ViewGroup)v.getParent()).removeView(v);
                    v.destroy(); // No WebView call after destroy; this test never attaches it.
                }
            });
        }
    }
    private static WebResourceResponse response(String mime,byte[] bytes,int code){
        return new WebResourceResponse(mime,"UTF-8",code,code==200?"OK":"Forbidden",Map.of("Cache-Control","no-store"),new ByteArrayInputStream(bytes));
    }
    public void testTwentyOneMeasurements() throws Exception {
        byte[] manifestBytes=asset("image-corpus/manifest.json");
        JSONObject manifest=new JSONObject(new String(manifestBytes,StandardCharsets.UTF_8));
        byte[] oracleBytes=asset("image-sources/pillow-oracle.json");
        JSONObject oracle=new JSONObject(new String(oracleBytes,StandardCharsets.UTF_8));
        Map<String,JSONObject> pillow=new HashMap<>();
        JSONArray pc1=oracle.getJSONArray("cases");for(int i=0;i<pc1.length();i++){JSONObject c=pc1.getJSONObject(i);assertNull(pillow.put(c.getString("id"),c));}
        JSONArray vectors=manifest.getJSONArray("vectors"),results=new JSONArray();assertEquals(21,vectors.length());assertEquals(21,pillow.size());
        JSONObject report=new JSONObject().put("scope","measurements_only_not_admission").put("manifest_sha256",hash(manifestBytes)).put("pillow_oracle_sha256",hash(oracleBytes))
            .put("fingerprint",Build.FINGERPRINT).put("api",Build.VERSION.SDK_INT).put("pillow_environment",oracle).put("cases",results);
        try {
            for(int i=0;i<vectors.length();i++){
                JSONObject vector=vectors.getJSONObject(i);String id=vector.getString("id"),path=vector.getString("path");
                assertTrue(path.matches("vectors/[A-Za-z0-9.-]+"));byte[] bytes=asset("image-corpus/"+path);
                String digest=hash(bytes);assertEquals(vector.getString("sha256"),digest);assertEquals(vector.getLong("size_bytes"),bytes.length);
                JSONObject oracleCase=pillow.get(id);assertNotNull(oracleCase);assertEquals(digest,oracleCase.getString("sha256"));
                JSONObject row=new JSONObject().put("id",id).put("sha256",digest).put("pillow",oracleCase)
                    .put("android_bounds",decode(bytes,true)).put("android_full",decode(bytes,false)).put("webview",web(bytes,path));
                results.put(row);android.util.Log.i("ImageParity",row.toString());
            }
            getInstrumentation().runOnMainSync(()->{});
            android.content.pm.PackageInfo provider=WebView.getCurrentWebViewPackage();
            report.put("webview_provider",provider==null?"unavailable":provider.packageName+"/"+provider.versionName);
        } finally {
            try(FileOutputStream out=getInstrumentation().getTargetContext().openFileOutput("image-parity-results.json",0)){out.write(report.toString(2).getBytes(StandardCharsets.UTF_8));}
        }
        assertEquals(21,results.length());
        for(int i=0;i<results.length();i++)assertFalse("WebView observation timeout",results.getJSONObject(i).getJSONObject("webview").getString("event").equals("timeout"));
    }
}
