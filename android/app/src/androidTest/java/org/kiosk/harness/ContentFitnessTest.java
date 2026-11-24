package org.kiosk.harness;
import android.content.pm.ActivityInfo;
import android.content.res.Configuration;
import android.os.SystemClock;
import android.view.*;
import android.webkit.WebView;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.json.*;
import org.kiosk.harness.binding.*;
import org.kiosk.harness.storage.*;

/** Select explicit methods only: inherited generic suites are not part of this content matrix. */
@SuppressWarnings("deprecation")
public class ContentFitnessTest extends GenericPlaybackTest {
    private String probe;
    @Override PlaybackInputs.Owned inputs(String name)throws Exception{if(!FitnessInputs.NAMES.contains(name))return super.inputs(name);return FitnessInputs.capture(getInstrumentation().getTargetContext(),ContentFitnessInputs.load(getInstrumentation().getContext(),name),name);}
    private JSONObject object(String script)throws Exception{return new JSONObject(new JSONArray("["+eval(script)+"]").getString(0));}
    private void write(String file,JSONObject value)throws Exception{try(var out=getInstrumentation().getTargetContext().openFileOutput(file,android.content.Context.MODE_APPEND)){out.write((value+"\n").getBytes(java.nio.charset.StandardCharsets.UTF_8));}}
    private void nativeOnlyWebView(){ui(()->{ViewGroup frame=(ViewGroup)activity.active.browser.getParent(),root=(ViewGroup)frame.getParent();for(int i=0;i<root.getChildCount();i++)if(root.getChildAt(i)!=frame)root.getChildAt(i).setVisibility(View.GONE);activity.active.browser.requestFocus();});}
    private void visual()throws Exception{
        CountDownLatch done=new CountDownLatch(1);AtomicReference<ViewTreeObserver.OnDrawListener> listener=new AtomicReference<>();WebView browser=activity.active.browser;
        ui(()->{assertTrue(browser.isAttachedToWindow());browser.postVisualStateCallback(SystemClock.elapsedRealtimeNanos(),new WebView.VisualStateCallback(){public void onComplete(long id){ViewTreeObserver.OnDrawListener draw=()->done.countDown();listener.set(draw);browser.getViewTreeObserver().addOnDrawListener(draw);browser.invalidate();}});});
        try{assertTrue("visual draw bounded",done.await(5,TimeUnit.SECONDS));getInstrumentation().waitForIdleSync();Thread.sleep(100);}finally{ui(()->{if(listener.get()!=null&&browser.getViewTreeObserver().isAlive())browser.getViewTreeObserver().removeOnDrawListener(listener.get());});}
    }
    private void orient(boolean landscape)throws Exception{
        int desired=landscape?Configuration.ORIENTATION_LANDSCAPE:Configuration.ORIENTATION_PORTRAIT;
        if(activity.getResources().getConfiguration().orientation!=desired){
            var monitor=getInstrumentation().addMonitor(StoredHarnessActivity.class.getName(),null,false);
            HarnessTestRunner.nextStoreAdapters.set(new HarnessTestRunner.StoreAdapters(FixturePublicationStore.NONE,PreparedWebView.PLATFORM,root));
            ui(()->activity.setRequestedOrientation(landscape?ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE:ActivityInfo.SCREEN_ORIENTATION_PORTRAIT));
            var next=getInstrumentation().waitForMonitorWithTimeout(monitor,12000);getInstrumentation().removeMonitor(monitor);assertNotNull("Activity orientation recreation",next);activity=(StoredHarnessActivity)next;
            until(()->activity.active!=null&&!activity.busy&&activity.state.equals("ready"),24000,"recreated private ready");
        }
        nativeOnlyWebView();visual();JSONObject v=object("JSON.stringify({w:innerWidth,h:innerHeight})");assertEquals("measured viewport shape",landscape,v.getInt("w")>v.getInt("h"));
    }
    private JSONObject measure(String label)throws Exception{
        visual();if(probe==null)try(var in=getInstrumentation().getContext().getAssets().open("content-fitness-probe.js")){probe=new String(org.kiosk.harness.core.LocalView.readBounded(in,64*1024),java.nio.charset.StandardCharsets.UTF_8);}
        JSONObject result=object(probe);result.put("label",label).put("elapsed_ms",SystemClock.elapsedRealtime()).put("pointer",activity.store.pointer()).put("visible",activity.visible).put("mode",activity.visibleMode).put("receipt_kiosk",activity.store.receipt("kiosk")).put("receipt_tv",activity.store.receipt("tv")).put("state",activity.state);
        ui(()->{try{result.put("attached",activity.active.browser.isAttachedToWindow()).put("native_width",activity.active.browser.getWidth()).put("native_height",activity.active.browser.getHeight());}catch(Exception e){throw new AssertionError(e);}});
        write("fitness-observations.jsonl",result);return result;
    }
    private void swipe(float x1,float y1,float x2,float y2)throws Exception{
        float density=activity.getResources().getDisplayMetrics().density;long start=SystemClock.uptimeMillis();
        for(int i=0;i<=8;i++){int n=i;ui(()->{float f=n/8f;MotionEvent event=MotionEvent.obtain(start,start+n*25,n==0?MotionEvent.ACTION_DOWN:n==8?MotionEvent.ACTION_UP:MotionEvent.ACTION_MOVE,(x1+(x2-x1)*f)*density,(y1+(y2-y1)*f)*density,0);try{activity.active.browser.dispatchTouchEvent(event);}finally{event.recycle();}});Thread.sleep(25);}Thread.sleep(150);
    }
    private void reachableLongContent(String label,String mode)throws Exception{
        boolean desc=false,place=false;JSONArray attempts=new JSONArray();
        for(int i=0;i<65;i++){
            JSONObject x=object(probe);JSONObject v=x.getJSONObject("viewport"),elements=x.getJSONObject("elements");
            JSONObject d=elements.getJSONObject(".event-description").optJSONObject("lastText"),p=elements.getJSONObject(".event-place").optJSONObject("lastText");
            desc|=d!=null&&d.optBoolean("hitContent");place|=p!=null&&p.optBoolean("hitContent");attempts.put(new JSONObject().put("step",i).put("scrollY",v.getDouble("scrollY")).put("description_end_accessible",desc).put("place_end_accessible",place));if(desc&&place)break;
            if(mode.equals("tv")){getInstrumentation().sendKeyDownUpSync(KeyEvent.KEYCODE_DPAD_DOWN);Thread.sleep(40);}else swipe((float)v.getDouble("width")*.5f,(float)v.getDouble("height")*.75f,(float)v.getDouble("width")*.5f,(float)v.getDouble("height")*.40f);
        }
        write("fitness-access.jsonl",new JSONObject().put("label",label).put("method",mode.equals("tv")?"native D-pad Down":"native touch swipes").put("description_end_accessible",desc).put("place_end_accessible",place).put("attempts",attempts));measure(label+"-after-scroll");screen("fitness-"+label+"-after-scroll");
        // A failed accessibility observation is evidence to review, not a reason to modify renderer.
    }
    private void tags(String label)throws Exception{
        JSONObject start=measure(label+"-tags-before");JSONArray attempts=new JSONArray();boolean visible=false;
        for(int i=0;i<65;i++){
            JSONObject v=object(probe).getJSONObject("viewport"),r=object("JSON.stringify((()=>{let n=document.querySelector('#tags button:last-child'),r=n.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,scroll:document.getElementById('tags').scrollLeft}})())");
            visible=r.getDouble("x")>=0&&r.getDouble("x")+r.getDouble("w")<=v.getDouble("width");attempts.put(r);if(visible)break;
            swipe((float)v.getDouble("width")*.85f,(float)(r.getDouble("y")+r.getDouble("h")/2),(float)v.getDouble("width")*.15f,(float)(r.getDouble("y")+r.getDouble("h")/2));
        }
        if(visible){
            // Native scrolling can still be flinging: its first down only stops the fling.
            double last=-1;int stable=0;long settle=SystemClock.elapsedRealtime()+3000;
            while(stable<3&&SystemClock.elapsedRealtime()<settle){double x=Double.parseDouble(eval("document.getElementById('tags').scrollLeft"));stable=Math.abs(x-last)<.5?stable+1:0;last=x;Thread.sleep(100);}
            visual();String point=eval("JSON.stringify((()=>{let r=document.querySelector('#tags button:last-child').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})())");JSONArray a=new JSONArray(new JSONArray("["+point+"]").getString(0));
            ui(()->{float density=activity.getResources().getDisplayMetrics().density,x=(float)a.optDouble(0)*density,y=(float)a.optDouble(1)*density;long now=SystemClock.uptimeMillis();MotionEvent down=MotionEvent.obtain(now,now,MotionEvent.ACTION_DOWN,x,y,0),up=MotionEvent.obtain(now,now+30,MotionEvent.ACTION_UP,x,y,0);try{activity.active.browser.dispatchTouchEvent(down);activity.active.browser.dispatchTouchEvent(up);}finally{down.recycle();up.recycle();}});
            long end=SystemClock.elapsedRealtime()+3000;while(!eval("document.querySelector('#tags button:last-child').getAttribute('aria-pressed')").equals("\"true\"")&&SystemClock.elapsedRealtime()<end)Thread.sleep(50);
        }
        write("fitness-access.jsonl",new JSONObject().put("label",label).put("tag_count",start.getInt("tagCount")).put("last_tag_visible",visible).put("last_tag_selected",eval("document.querySelector('#tags button:last-child').getAttribute('aria-pressed')")).put("attempts",attempts));measure(label+"-tags-after");screen("fitness-"+label+"-tags-after");assertTrue("last tag reached",visible);assertEquals("\"true\"",eval("document.querySelector('#tags button:last-child').getAttribute('aria-pressed')"));
    }
    private void matrix(String name)throws Exception{
        setupRoot();String identity=install(name);assertEquals("ready",activity.state);
        for(boolean landscape:new boolean[]{true,false}){
            orient(landscape);
            for(String mode:new String[]{"kiosk","tv"}){
                mode(mode);nativeOnlyWebView();String label=name+"-"+(landscape?"landscape":"portrait")+"-"+mode;
                assertEquals(identity,activity.visible);assertEquals(identity,activity.store.receipt(mode));JSONObject first=measure(label+"-initial");screen("fitness-"+label+"-initial");
                if(name.equals("empty")){assertEquals("0 / 0",first.getString("counter"));assertTrue(first.getJSONObject("elements").getJSONObject("#next").getBoolean("disabled"));}
                if(name.equals("long-text-tags")){assertEquals(61,first.getInt("tagCount"));assertTrue(first.getBoolean("descriptionEqualsSelectedSource"));if(mode.equals("kiosk"))tags(label);reachableLongContent(label,mode);}
                if(name.equals("image-shapes")){
                    String prior=eval("document.getElementById('counter').textContent");long priorAt=SystemClock.elapsedRealtime();
                    for(int card=1;card<4;card++){
                        if(mode.equals("kiosk"))tap("next");else{
                            String old=prior;long end=SystemClock.elapsedRealtime()+26000;while(eval("document.getElementById('counter').textContent").equals(old)&&SystemClock.elapsedRealtime()<end)Thread.sleep(200);
                            assertFalse("actual automatic TV transition",old.equals(eval("document.getElementById('counter').textContent")));
                        }
                        String next=eval("document.getElementById('counter').textContent");long now=SystemClock.elapsedRealtime();write("fitness-transitions.jsonl",new JSONObject().put("label",label).put("from",prior).put("to",next).put("elapsed_ms",now).put("interval_ms",now-priorAt).put("method",mode.equals("tv")?"automatic original timer":"native next touch"));prior=next;priorAt=now;
                        JSONObject m=measure(label+"-card-"+card);assertEquals("true",eval("Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)"));screen("fitness-"+label+"-card-"+card);
                    }
                }
            }
        }
    }
    public void testEmptyMatrix()throws Exception{matrix("empty");}
    public void testControlMatrix()throws Exception{matrix("control");}
    public void testLongTextTagsMatrix()throws Exception{matrix("long-text-tags");}
    public void testImageShapesMatrix()throws Exception{matrix("image-shapes");}
    private void tapReachable(String id)throws Exception{
        boolean visible=false;
        for(int step=0;step<20;step++){
            JSONObject point=object("JSON.stringify((()=>{let n=document.getElementById('"+id+"'),r=n.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,w:innerWidth,h:innerHeight}})())");
            visible=point.getDouble("x")>=0&&point.getDouble("x")<point.getDouble("w")&&point.getDouble("y")>=0&&point.getDouble("y")<point.getDouble("h");if(visible)break;
            float w=(float)point.getDouble("w"),h=(float)point.getDouble("h");if(point.getDouble("y")>h)swipe(w*.5f,h*.8f,w*.5f,h*.35f);else swipe(w*.5f,h*.3f,w*.5f,h*.8f);
        }
        assertTrue("native reachable control "+id,visible);visual();tap(id);
    }
    public void testShortAndShapeAccessibilityFollowup()throws Exception{
        setupRoot();
        for(String name:List.of("control","image-shapes")){
            install(name);
            for(boolean landscape:new boolean[]{true,false}){
                orient(landscape);
                for(String mode:new String[]{"kiosk","tv"}){
                    mode(mode);nativeOnlyWebView();
                    if(mode.equals("kiosk")){tapReachable("home-button");assertEquals("false",eval("document.getElementById('home').hidden"));measure(name+"-followup-home-"+landscape);screen("fitness-"+name+"-home-"+landscape);tapReachable("open-events");assertEquals("true",eval("document.getElementById('home').hidden"));}
                    int total=name.equals("control")?1:4;
                    for(int card=0;card<total;card++){
                        String label=name+"-access-"+(landscape?"landscape":"portrait")+"-"+mode+"-"+card;
                        measure(label+"-before");reachableLongContent(label,mode);
                        if(card+1<total){String old=eval("document.getElementById('counter').textContent");if(mode.equals("kiosk"))tap("next");else{long end=SystemClock.elapsedRealtime()+26000;while(eval("document.getElementById('counter').textContent").equals(old)&&SystemClock.elapsedRealtime()<end)Thread.sleep(200);}assertFalse(old.equals(eval("document.getElementById('counter').textContent")));}
                    }
                }
            }
        }
    }
    public void testImagesFullObjectAccessibility()throws Exception{
        setupRoot();install("image-shapes");
        for(boolean landscape:new boolean[]{true,false}){
            orient(landscape);
            for(String mode:new String[]{"kiosk","tv"}){
                mode(mode);nativeOnlyWebView();
                for(int card=0;card<4;card++){
                    String label="full-image-"+(landscape?"landscape":"portrait")+"-"+mode+"-"+card;
                    JSONObject before=measure(label+"-before"),last=before;boolean accessible=false;int steps=0;
                    for(;steps<20;steps++){
                        JSONObject img=last.getJSONArray("images").getJSONObject(0),draw=img.getJSONObject("drawnContent");accessible=draw.getBoolean("inViewport");if(accessible)break;
                        JSONObject v=last.getJSONObject("viewport");
                        if(mode.equals("tv")){getInstrumentation().sendKeyDownUpSync(draw.getDouble("y")<0?KeyEvent.KEYCODE_DPAD_UP:KeyEvent.KEYCODE_DPAD_DOWN);Thread.sleep(80);}
                        else{float w=(float)v.getDouble("width"),h=(float)v.getDouble("height");if(draw.getDouble("y")<0)swipe(w*.5f,h*.3f,w*.5f,h*.45f);else swipe(w*.5f,h*.75f,w*.5f,h*.6f);}
                        last=object(probe);
                    }
                    write("fitness-image-access.jsonl",new JSONObject().put("label",label).put("elapsed_ms",SystemClock.elapsedRealtime()).put("full_drawn_image_accessible",accessible).put("steps",steps).put("initial_image",before.getJSONArray("images").getJSONObject(0)).put("final_image",last.getJSONArray("images").getJSONObject(0)));measure(label+"-after");screen("fitness-"+label+"-after");
                    if(card<3){String old=eval("document.getElementById('counter').textContent");if(mode.equals("kiosk"))tap("next");else{long end=SystemClock.elapsedRealtime()+26000;while(eval("document.getElementById('counter').textContent").equals(old)&&SystemClock.elapsedRealtime()<end)Thread.sleep(200);}assertFalse(old.equals(eval("document.getElementById('counter').textContent")));}
                }
            }
        }
    }
    public void testUnicodeTitleAndPortraitJpegEdgeProbe()throws Exception{
        setupRoot();install("long-text-tags");
        for(boolean landscape:new boolean[]{true,false}){
            orient(landscape);
            for(String mode:new String[]{"kiosk","tv"}){
                mode(mode);nativeOnlyWebView();String label="unicode-"+(landscape?"landscape":"portrait")+"-"+mode;measure(label+"-before");boolean shown=false;
                for(int step=0;step<35;step++){
                    JSONObject x=object(probe),r=x.getJSONObject("elements").getJSONObject(".event-title").getJSONObject("lastText"),v=x.getJSONObject("viewport");shown=r.getBoolean("hitContent");if(shown)break;
                    if(mode.equals("tv")){getInstrumentation().sendKeyDownUpSync(r.getDouble("y")<0?KeyEvent.KEYCODE_DPAD_UP:KeyEvent.KEYCODE_DPAD_DOWN);Thread.sleep(60);}
                    else{float w=(float)v.getDouble("width"),h=(float)v.getDouble("height");if(r.getDouble("y")<0)swipe(w*.5f,h*.3f,w*.5f,h*.4f);else swipe(w*.5f,h*.7f,w*.5f,h*.6f);}
                }
                assertTrue("Unicode title suffix reachable",shown);assertEquals("true",eval("document.querySelector('.event-title').textContent===JSON.parse(document.getElementById('bootstrap').textContent).data.events[0].title"));measure(label+"-suffix-visible");screen("fitness-"+label+"-suffix-visible");
            }
        }
        install("image-shapes");orient(false);mode("kiosk");nativeOnlyWebView();for(int i=0;i<3;i++)tap("next");JSONObject x=measure("portrait-jpeg-corrected-mid-edge-probe");assertTrue(x.getJSONArray("images").getJSONObject(0).getJSONObject("drawnContent").getBoolean("inViewport"));write("fitness-image-access.jsonl",new JSONObject().put("label","portrait-jpeg-corrected-mid-edge-probe").put("elapsed_ms",SystemClock.elapsedRealtime()).put("full_drawn_image_accessible",true).put("final_image",x.getJSONArray("images").getJSONObject(0)));screen("fitness-portrait-jpeg-corrected-mid-edge-probe");
    }
    private JSONObject ownership(String label)throws Exception{return new JSONObject().put("label",label).put("elapsed_ms",SystemClock.elapsedRealtime()).put("pointer",activity.store.pointer()).put("visible",activity.visible==null?JSONObject.NULL:activity.visible).put("mode",activity.visibleMode==null?JSONObject.NULL:activity.visibleMode).put("selected",activity.store.selectedMode()).put("receipt_kiosk",activity.store.receipt("kiosk")).put("receipt_tv",activity.store.receipt("tv")).put("state",activity.state);}
    public void testRejectedCaptureAndResourceFaultsRetainWorkingPublication()throws Exception{
        AtomicReference<String> fault=new AtomicReference<>("");root=getInstrumentation().getTargetContext().getFilesDir().getCanonicalFile().toPath().resolve("fitness-fault-"+UUID.randomUUID());Files.createDirectory(root);launch(root,p->{if(p.equals(fault.get()))throw new IOException("injected_resource_failure");},PreparedWebView.PLATFORM);
        mode("kiosk");String good=install("control");mode("tv");mode("kiosk");PreparedWebView previous=activity.active;write("fitness-faults.jsonl",ownership("working-before"));
        var bad=ContentFitnessInputs.load(getInstrumentation().getContext(),"image-shapes");var evidence=FitnessInputs.evidence(bad,"image-shapes");bad.get(evidence.kioskRoot()+"/index.html")[0]^=1;
        try{LocalPreparation.capture(getInstrumentation().getTargetContext(),bad,evidence);fail("tampered candidate captured");}catch(IOException expected){}
        assertSame(previous,activity.active);assertEquals(good,activity.store.pointer());write("fitness-faults.jsonl",ownership("tampered-candidate-refused"));
        Path temp=getInstrumentation().getTargetContext().getNoBackupFilesDir().getCanonicalFile().toPath().resolve("fitness-cancel-"+UUID.randomUUID());Files.createDirectory(temp);try{FitnessInputs.cancelledCapture(temp,ContentFitnessInputs.load(getInstrumentation().getContext(),"image-shapes"),"image-shapes");}finally{Files.delete(temp);}
        assertSame(previous,activity.active);assertEquals(good,activity.store.pointer());write("fitness-faults.jsonl",ownership("real-capture-cancellation"));
        for(String point:List.of("development.space_checked","copy_chunk")){fault.set(point);install("image-shapes");assertSame(previous,activity.active);assertEquals(good,activity.visible);assertEquals(good,activity.store.pointer());assertEquals(good,activity.store.receipt("kiosk"));assertEquals(good,activity.store.receipt("tv"));write("fitness-faults.jsonl",ownership("injected-resource-"+point));}
        fault.set("");assertEquals(good,activity.store.startupChoices("kiosk").get(0).id());assertEquals(good,activity.store.startupChoices("tv").get(0).id());write("fitness-faults.jsonl",ownership("working-private-bytes-revalidated-both-modes"));assertEquals("true",eval("document.images[0].complete&&document.images[0].naturalWidth>0"));measure("working-preserved-after-faults");screen("fitness-working-preserved-after-faults");
    }
    public void testActualRendererFailureDoesNotRollbackPublishedPointer()throws Exception{
        setupRoot();mode("kiosk");String previous=install("control");mode("tv");mode("kiosk");String next=install("image-shapes");write("fitness-faults.jsonl",ownership("replacement-ready-before-renderer-terminate"));
        AtomicBoolean terminated=new AtomicBoolean();ui(()->{var renderer=activity.active.browser.getWebViewRenderProcess();assertNotNull(renderer);terminated.set(renderer.terminate());});assertTrue(terminated.get());until(()->activity.active==null&&!activity.busy,10000,"actual renderer gone");assertEquals("failed",activity.state);assertEquals(next,activity.store.pointer());assertEquals(next,activity.store.receipt("kiosk"));assertEquals(previous,activity.store.receipt("tv"));Thread.sleep(800);assertNull(activity.active);write("fitness-faults.jsonl",ownership("actual-renderer-gone-pointer-not-rolled-back"));screen("fitness-renderer-gone-safe-message");closeActivity();launch(root,FixturePublicationStore.NONE,PreparedWebView.PLATFORM);assertEquals("ready",activity.state);assertEquals(next,activity.visible);write("fitness-faults.jsonl",ownership("explicit-revalidated-recovery"));
    }
}
