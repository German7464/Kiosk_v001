package org.kiosk.harness.visualtest;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.view.ViewGroup;
import android.webkit.*;
import android.widget.FrameLayout;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.Map;

/** Disposable test-host APK only. Never linked into :app or its display/catalog. */
public final class VisualHostActivity extends Activity {
    static final String ORIGIN="https://visual-test.invalid";
    WebView browser;
    private FrameLayout root;
    private boolean disposed;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        root=new FrameLayout(this);setContentView(root);
        try {
            browser=new WebView(this);
            WebSettings settings=browser.getSettings();
            settings.setJavaScriptEnabled(true);
            settings.setAllowFileAccess(false);settings.setAllowContentAccess(false);
            settings.setBlockNetworkLoads(true);settings.setSupportMultipleWindows(false);
            settings.setJavaScriptCanOpenWindowsAutomatically(false);
            settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
            settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
            browser.setBackgroundColor(Color.rgb(32,64,96));
            root.addView(browser,new FrameLayout.LayoutParams(-1,-1));
        } catch(RuntimeException failure) { dispose();throw failure; }
    }

    void show(String label,byte[] image,String mime,int width,int height,boolean pixelated) {
        if(disposed)throw new IllegalStateException("host disposed");
        if(!label.matches("[A-Za-z0-9.-]+"))throw new IllegalArgumentException("test ID");
        String html="<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'>"
            +"<style>html,body{margin:0;background:rgb(32,64,96);color:white;font:14px sans-serif}"
            +"p{position:absolute;left:24px;top:20px;margin:0}img{position:absolute;left:24px;top:80px;width:"
            +width+"px;height:"+height+"px;"+(pixelated?"image-rendering:pixelated;":"")+"}</style>"
            +"<p>TEST ONLY: "+label+"</p><img id='image'><script>window.loaded='pending';let i=document.getElementById('image');"
            +"i.onload=()=>window.loaded='load';i.onerror=()=>window.loaded='error';i.src='/image';</script>";
        byte[] page=html.getBytes(StandardCharsets.UTF_8);
        browser.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest r){return true;}
            @Override public WebResourceResponse shouldInterceptRequest(WebView v,WebResourceRequest r){
                String url=r.getUrl().toString();
                if(r.getMethod().equals("GET")&&url.equals(ORIGIN+"/index.html"))return response("text/html",page,200);
                if(r.getMethod().equals("GET")&&url.equals(ORIGIN+"/image"))return response(mime,image,200);
                return response("text/plain",new byte[0],403);
            }
        });
        browser.loadUrl(ORIGIN+"/index.html");
    }
    private static WebResourceResponse response(String mime,byte[] bytes,int status){
        return new WebResourceResponse(mime,"UTF-8",status,status==200?"OK":"Forbidden",
            Map.of("Cache-Control","no-store"),new ByteArrayInputStream(bytes));
    }
    void dispose() {
        if(disposed)return;
        disposed=true;
        WebView owned=browser;browser=null;
        if(owned!=null){
            if(owned.getParent() instanceof ViewGroup)((ViewGroup)owned.getParent()).removeView(owned);
            owned.destroy(); // UI thread; no WebView calls after this point.
        }
    }
    @Override protected void onDestroy(){dispose();super.onDestroy();}
}
