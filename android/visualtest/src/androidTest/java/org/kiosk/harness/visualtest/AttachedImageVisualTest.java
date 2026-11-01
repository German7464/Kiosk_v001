package org.kiosk.harness.visualtest;

import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.os.Build;
import android.os.SystemClock;
import android.test.InstrumentationTestCase;
import android.webkit.WebView;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.json.*;

/** Screen-compositor pixels, not a View.draw substitute or decoder-admission test. */
@SuppressWarnings("deprecation")
public final class AttachedImageVisualTest extends InstrumentationTestCase {
    private VisualHostActivity activity;
    private static final int[] BACKGROUND={32,64,96};
    private static final int TOLERANCE=3; // sRGB source-over rounding/premultiplication, center of nearest-neighbor tiles.

    private byte[] asset(String name) throws Exception {
        try(InputStream input=getInstrumentation().getTargetContext().getAssets().open(name)){
            byte[] bytes=input.readNBytes(2*1024*1024+1);
            assertTrue(bytes.length<=2*1024*1024);return bytes;
        }
    }
    private String hash(byte[] bytes) throws Exception {
        StringBuilder result=new StringBuilder();
        for(byte b:MessageDigest.getInstance("SHA-256").digest(bytes))result.append(String.format(Locale.ROOT,"%02x",b&255));
        return result.toString();
    }
    private String evaluate(String script) throws Exception {
        CountDownLatch done=new CountDownLatch(1);AtomicReference<String> result=new AtomicReference<>();
        getInstrumentation().runOnMainSync(()->activity.browser.evaluateJavascript(script,s->{result.set(s);done.countDown();}));
        assertTrue("JS callback within3s",done.await(3,TimeUnit.SECONDS));return result.get();
    }
    private void save(String name,byte[] bytes) throws Exception {
        try(FileOutputStream out=getInstrumentation().getTargetContext().openFileOutput(name,0)){out.write(bytes);}
    }
    private void close() {
        if(activity!=null){
            getInstrumentation().runOnMainSync(()->{activity.dispose();activity.dispose();assertNull(activity.browser);activity.finish();});
            activity=null;
        }
    }
    @Override protected void tearDown() throws Exception {try{close();}finally{super.tearDown();}}

    public void testRGB() throws Exception {check("rgb","generated-3x2-rgb.png",3,2,96,64,false);}
    public void testRGBA() throws Exception {check("rgba","generated-7x5-rgba.png",7,5,168,120,true);}
    public void testProgressiveJPEG() throws Exception {check("jpeg","progressive.jpg",1400,875,280,175,false);}

    private void check(String id,String file,int naturalWidth,int naturalHeight,int cssWidth,int cssHeight,boolean alpha) throws Exception {
        byte[] image=asset("image-corpus/vectors/"+file);String digest=hash(image);
        JSONObject manifest=new JSONObject(new String(asset("image-corpus/manifest.json"),StandardCharsets.UTF_8));
        JSONArray vectors=manifest.getJSONArray("vectors");boolean found=false;
        for(int n=0;n<vectors.length();n++){
            JSONObject v=vectors.getJSONObject(n);
            if(v.getString("path").equals("vectors/"+file)){assertEquals(v.getString("sha256"),digest);found=true;}
        }
        assertTrue("fixed manifest source",found);
        JSONObject report=new JSONObject().put("id",id).put("sha256",digest).put("fingerprint",Build.FINGERPRINT)
            .put("api",Build.VERSION.SDK_INT).put("screen_source","UiAutomation.takeScreenshot")
            .put("tolerance_per_srgb_channel",TOLERANCE).put("expected_css_left",24).put("expected_css_top",80);
        Bitmap screen=null;
        long started=SystemClock.elapsedRealtime();
        try {
            Intent intent=new Intent(getInstrumentation().getTargetContext(),VisualHostActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            activity=(VisualHostActivity)getInstrumentation().startActivitySync(intent);
            getInstrumentation().runOnMainSync(()->activity.show(id,image,id.equals("jpeg")?"image/jpeg":"image/png",cssWidth,cssHeight,!id.equals("jpeg")));
            assertNull("no device/network permissions",activity.getPackageManager().getPackageInfo(activity.getPackageName(),android.content.pm.PackageManager.GET_PERMISSIONS).requestedPermissions);
            long until=SystemClock.elapsedRealtime()+10000;
            while(!"\"load\"".equals(evaluate("window.loaded"))&&SystemClock.elapsedRealtime()<until)Thread.sleep(40);
            assertEquals("\"load\"",evaluate("window.loaded"));
            CountDownLatch visual=new CountDownLatch(1),draw=new CountDownLatch(1);
            getInstrumentation().runOnMainSync(()->{
                assertTrue(activity.browser.isAttachedToWindow());assertTrue(activity.browser.isShown());
                activity.browser.postVisualStateCallback(1,new WebView.VisualStateCallback(){
                    @Override public void onComplete(long request){
                        if(activity==null||activity.browser==null)return;
                        visual.countDown();
                        activity.browser.invalidate();
                        // Observe a real draw after visual-state readiness, then cross another frame.
                        activity.browser.getViewTreeObserver().addOnDrawListener(new android.view.ViewTreeObserver.OnDrawListener(){
                            boolean seen;
                            @Override public void onDraw(){
                                if(seen)return;seen=true;
                                activity.browser.post(()->{
                                    if(activity==null||activity.browser==null)return;
                                    activity.browser.getViewTreeObserver().removeOnDrawListener(this);
                                    activity.browser.postOnAnimation(draw::countDown);
                                });
                            }
                        });
                    }
                });
            });
            assertTrue("visual-state callback5s",visual.await(5,TimeUnit.SECONDS));
            assertTrue("draw after callback5s",draw.await(5,TimeUnit.SECONDS));
            long focusEnd=SystemClock.elapsedRealtime()+5000;AtomicBoolean focused=new AtomicBoolean();
            do {getInstrumentation().runOnMainSync(()->focused.set(activity.hasWindowFocus()));if(!focused.get())Thread.sleep(40);}
            while(!focused.get()&&SystemClock.elapsedRealtime()<focusEnd);
            assertTrue("foreground window",focused.get());
            JSONObject geometry=new JSONObject(evaluate("(()=>{let i=document.getElementById('image'),r=i.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,naturalWidth:i.naturalWidth,naturalHeight:i.naturalHeight,dpr:devicePixelRatio,viewportWidth:innerWidth,viewportHeight:innerHeight}})()"));
            assertEquals(naturalWidth,geometry.getInt("naturalWidth"));assertEquals(naturalHeight,geometry.getInt("naturalHeight"));
            assertEquals(24.0,geometry.getDouble("x"),0.01);assertEquals(80.0,geometry.getDouble("y"),0.01);
            assertEquals((double)cssWidth,geometry.getDouble("width"),0.01);assertEquals((double)cssHeight,geometry.getDouble("height"),0.01);
            int[] location=new int[2],nativeSize=new int[2];
            getInstrumentation().runOnMainSync(()->{activity.browser.getLocationOnScreen(location);nativeSize[0]=activity.browser.getWidth();nativeSize[1]=activity.browser.getHeight();});
            geometry.put("view_screen_x",location[0]).put("view_screen_y",location[1]).put("view_native_width",nativeSize[0]).put("view_native_height",nativeSize[1]);
            report.put("geometry",geometry).put("visual_callback_and_subsequent_draw",true).put("attached_visible_focused",true);
            screen=getInstrumentation().getUiAutomation(android.app.UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES).takeScreenshot();
            assertNotNull("real compositor screenshot",screen);
            try(FileOutputStream out=getInstrumentation().getTargetContext().openFileOutput(id+"-screen.png",0)){assertTrue(screen.compress(Bitmap.CompressFormat.PNG,100,out));}
            report.put("screen_width",screen.getWidth()).put("screen_height",screen.getHeight())
                .put("screen_color_space",screen.getColorSpace()==null?"unknown":screen.getColorSpace().getName());
            double dpr=geometry.getDouble("dpr");assertEquals(nativeSize[0],geometry.getDouble("viewportWidth")*dpr,2.0);
            double left=location[0]+24*dpr,top=location[1]+80*dpr;
            report.put("screen_image_rect",new JSONArray(new double[]{left,top,cssWidth*dpr,cssHeight*dpr}));
            JSONArray samples=new JSONArray();report.put("samples",samples);
            // Uncovered background immediately to the left of the image.
            sample(screen,(int)(left-8*dpr),(int)(top+8*dpr),BACKGROUND,samples,"background");
            if(!id.equals("jpeg")){
                for(int y=0;y<naturalHeight;y++)for(int x=0;x<naturalWidth;x++){
                    int a=alpha?(x+y)*63%256:255;
                    int[] src={x*31%256,y*47%256,123},expected=new int[3];
                    for(int c=0;c<3;c++)expected[c]=(int)Math.round((src[c]*a+BACKGROUND[c]*(255-a))/255.0);
                    int sx=(int)Math.round(left+(x+0.5)*cssWidth*dpr/naturalWidth);
                    int sy=(int)Math.round(top+(y+0.5)*cssHeight*dpr/naturalHeight);
                    sample(screen,sx,sy,expected,samples,"source("+x+","+y+") alpha="+a);
                }
            }else{
                // No cross-engine bit equality: non-background, varied interior plus actual human review.
                java.util.Set<Integer> colors=new java.util.HashSet<>();int different=0;
                for(int y=0;y<8;y++)for(int x=0;x<12;x++){
                    int pixel=screen.getPixel((int)(left+(x+0.5)*cssWidth*dpr/12),(int)(top+(y+0.5)*cssHeight*dpr/8));
                    colors.add(pixel);if(pixel!=Color.rgb(32,64,96))different++;
                }
                report.put("jpeg_grid_unique_colors",colors.size()).put("jpeg_grid_nonbackground",different);
                assertTrue("JPEG visible varied content",colors.size()>16&&different>80);
            }
            android.content.pm.PackageInfo provider=WebView.getCurrentWebViewPackage();
            report.put("webview",provider.packageName+"/"+provider.versionName).put("result","PASS");
        } finally {
            report.put("elapsed_ms",SystemClock.elapsedRealtime()-started);
            try {save(id+"-results.json",report.toString(2).getBytes(StandardCharsets.UTF_8));}
            finally {try{if(screen!=null)screen.recycle();}finally{close();}}
        }
    }
    private void sample(Bitmap screen,int x,int y,int[] expected,JSONArray samples,String label) throws Exception {
        JSONObject row=new JSONObject().put("label",label).put("center_screen_xy",new JSONArray(new int[]{x,y}))
            .put("expected_rgb",new JSONArray(expected)).put("sample_region","3x3 center pixels");samples.put(row);
        int max=0;JSONArray actual=new JSONArray();
        for(int dy=-1;dy<=1;dy++)for(int dx=-1;dx<=1;dx++){
            int value=screen.getPixel(x+dx,y+dy);int[] rgb={Color.red(value),Color.green(value),Color.blue(value)};
            actual.put(new JSONArray(rgb));for(int c=0;c<3;c++)max=Math.max(max,Math.abs(rgb[c]-expected[c]));
        }
        row.put("actual_rgb_3x3",actual).put("max_channel_error",max);
        assertTrue(label+" max channel error "+max,max<=TOLERANCE);
    }
}
