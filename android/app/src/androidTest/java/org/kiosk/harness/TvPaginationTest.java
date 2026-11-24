package org.kiosk.harness;
import android.content.Intent;
import android.os.SystemClock;
import android.view.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.*;
import org.json.*;
import org.kiosk.harness.binding.*;
import org.kiosk.harness.storage.*;

/** Focused explicit methods; test clock never enters main APK or the persisted renderer source. */
@SuppressWarnings("deprecation")
public class TvPaginationTest extends GenericPlaybackTest {
    private String probe;
    @Override PlaybackInputs.Owned inputs(String name)throws Exception{if(!PaginationInputs.NAMES.contains(name))return super.inputs(name);return PaginationInputs.capture(getInstrumentation().getTargetContext(),PaginationAssets.load(getInstrumentation().getContext(),name),name);}
    private void write(String file,JSONObject value)throws Exception{try(var out=getInstrumentation().getTargetContext().openFileOutput(file,android.content.Context.MODE_APPEND)){out.write((value+"\n").getBytes(java.nio.charset.StandardCharsets.UTF_8));}}
    protected JSONObject snap(String label)throws Exception{
        PaginationUi.drawn(this);if(probe==null)probe=PaginationUi.asset(this,"tv-pagination-probe.js");JSONObject s=PaginationUi.object(this,probe);s.put("label",label).put("elapsed_ms",SystemClock.elapsedRealtime()).put("pointer",activity.store.pointer()).put("visible",activity.visible).put("mode",activity.visibleMode).put("receipt_kiosk",activity.store.receipt("kiosk")).put("receipt_tv",activity.store.receipt("tv")).put("browser_object",System.identityHashCode(activity.active.browser));write("pagination-pages.jsonl",s);return s;
    }
    protected void clock()throws Exception{assertEquals("true",eval(PaginationUi.asset(this,"tv-pagination-clock.js")));Thread.sleep(350);PaginationUi.drawn(this);}
    private int part(JSONObject s){String value=s.optString("part");return value.matches(".*\\d+.*")?Integer.parseInt(value.replaceAll("\\D+","")):0;}
    private void tick()throws Exception{eval("window.__pc2Clock.tick()");}
    private int fieldIndex(String field){return List.of("event-date","event-title","event-description","event-place").indexOf(field);}
    private void geometry(JSONObject s)throws Exception{
        assertTrue("document width",s.getInt("docW")<=s.getInt("w")+1);assertTrue("document height",s.getInt("docH")<=s.getInt("h")+1);
        if(!s.isNull("text")){var box=s.getJSONObject("text");assertTrue("text not clipped horizontally",box.getInt("scrollW")<=box.getInt("clientW")+1);assertTrue("text not clipped vertically",box.getInt("scrollH")<=box.getInt("clientH")+1);}
        assertTrue("image actual load",s.getBoolean("allImages"));
        if(!s.isNull("context")){assertTrue(s.getJSONObject("context").getInt("scrollH")<=s.getJSONObject("copy").getInt("clientH")*.45+1);assertTrue(s.getJSONObject("text").getInt("clientH")>=64);}
    }
    private void sameImage(JSONObject first,JSONObject s)throws Exception{
        assertEquals(first.optString("imageSrc"),s.optString("imageSrc"));if(!first.isNull("image"))for(String key:List.of("x","y","w","h"))assertEquals("fixed image "+key,first.getJSONObject("image").getDouble(key),s.getJSONObject("image").getDouble(key),1.0);
    }
    private JSONObject collectEvent(String label)throws Exception{
        JSONObject first=snap(label+"-part-first");geometry(first);String counter=first.getString("counter");JSONArray expected=first.getJSONArray("expected");Map<String,String> expectedMap=new LinkedHashMap<>();for(int i=0;i<expected.length();i++){var f=expected.getJSONObject(i);expectedMap.put(f.getString("field"),f.getString("text"));}
        boolean fixed=!first.isNull("context");Map<String,StringBuilder> built=new LinkedHashMap<>();for(String key:expectedMap.keySet())built.put(key,new StringBuilder());int lastField=-1,parts=0;JSONObject s=first;screen("pagination-"+label+"-first");
        while(parts<256){
            assertEquals("event cannot advance before all parts",counter,s.getString("counter"));geometry(s);sameImage(first,s);parts++;
            if(s.getString("layout").equals("paginated"))assertEquals("consecutive part",parts,part(s));
            if(fixed){JSONArray context=s.getJSONArray("contextChunks");assertEquals(3,context.length());for(int i=0;i<context.length();i++){var f=context.getJSONObject(i);assertEquals(expectedMap.get(f.getString("field")),f.getString("text"));assertEquals(0,f.getInt("childElements"));}}
            JSONArray chunks=s.getJSONArray("chunks");for(int i=0;i<chunks.length();i++){var f=chunks.getJSONObject(i);String key=f.getString("field"),piece=f.getString("text");assertEquals(0,f.getInt("childElements"));int index=fieldIndex(key);assertTrue("ordered fields",index>=lastField);lastField=index;built.get(key).append(piece);assertTrue("no loss/reorder/prefix mutation",expectedMap.get(key).startsWith(built.get(key).toString()));}
            boolean complete=true;for(String key:expectedMap.keySet())if(!(fixed&&!key.equals("event-description")))complete&=expectedMap.get(key).equals(built.get(key).toString());
            JSONArray pending=s.getJSONArray("pending");if(pending.length()>0){assertEquals("one reading timer",1,pending.length());assertEquals(s.getInt("expectedDuration"),pending.getJSONObject(0).getInt("delay"));}
            if(complete){screen("pagination-"+label+"-last");JSONObject summary=new JSONObject().put("label",label).put("parts",parts).put("fixedContext",fixed).put("counter",counter).put("sourceFields",new JSONObject(expectedMap)).put("reconstructed",new JSONObject());for(String key:built.keySet())summary.getJSONObject("reconstructed").put(key,fixed&&!key.equals("event-description")?expectedMap.get(key):built.get(key).toString());write("pagination-reconstruction.jsonl",summary);
                if(pending.length()==1){tick();JSONObject after=snap(label+"-after-last");if(s.getInt("events")==1){assertEquals(counter,after.getString("counter"));assertEquals("sole oversized loops",1,part(after));}else {int next=Integer.parseInt(counter.split("/")[0].trim())%s.getInt("events")+1;assertEquals("correct next event",next+" / "+s.getInt("events"),after.getString("counter"));}}else{assertEquals(1,s.getInt("events"));assertEquals("single",s.getString("layout"));}return summary;
            }
            assertEquals("incomplete page must schedule next",1,pending.length());tick();s=snap(label+"-part-"+(parts+1));
        }
        throw new AssertionError("bounded traversal did not finish fixture");
    }
    private void matrix(String name)throws Exception{
        setupRoot();String id=install(name);assertEquals("ready",activity.state);
        for(boolean landscape:new boolean[]{true,false}){
            PaginationUi.orient(this,landscape);mode("tv");PaginationUi.expand(this);Thread.sleep(250);clock();JSONObject first=snap(name+"-"+landscape+"-initial");assertEquals(id,activity.visible);assertEquals(id,activity.store.receipt("tv"));
            if(first.getInt("events")==0){assertEquals("0 / 0",first.getString("counter"));assertEquals(0,first.getJSONArray("pending").length());Thread.sleep(200);assertEquals("0 / 0",snap(name+"-empty-stable").getString("counter"));screen("pagination-"+name+"-"+landscape+"-empty");}
            else for(int event=0;event<first.getInt("events");event++)collectEvent(name+"-"+(landscape?"landscape":"portrait")+"-event-"+event);
            mode("kiosk");PaginationUi.expand(this);Thread.sleep(200);JSONObject k=snap(name+"-"+landscape+"-kiosk");assertEquals(id,activity.store.receipt("kiosk"));assertEquals("false",eval("!!document.querySelector('.tv-copy')"));if(k.getInt("events")>1){String before=k.getString("counter");tap("next");assertFalse(before.equals(snap(name+"-kiosk-next").getString("counter")));}screen("pagination-"+name+"-"+landscape+"-kiosk");
        }
    }
    public void testEmptyPagination()throws Exception{matrix("empty");}
    public void testControlPagination()throws Exception{matrix("control");}
    public void testLongFieldsPagination()throws Exception{matrix("long-text-tags");}
    public void testImageShapesPagination()throws Exception{matrix("image-shapes");}
    public void testTwoEventsPagination()throws Exception{matrix("two-events");}
    public void testDescriptionContextPagination()throws Exception{matrix("description-only");}
    public void testSameDocumentReflowAndVisibility()throws Exception{
        setupRoot();install("two-events");PaginationUi.orient(this,true);clock();JSONObject first=snap("reflow-before");tick();assertTrue(part(snap("reflow-part-two"))>1);
        ViewGroup.LayoutParams params=activity.active.browser.getLayoutParams();int oldH=params.height;ui(()->{params.height=600;activity.active.browser.setLayoutParams(params);});Thread.sleep(400);JSONObject resized=snap("same-document-resize");assertEquals(first.getString("documentToken"),resized.getString("documentToken"));assertEquals(first.getInt("browser_object"),resized.getInt("browser_object"));assertEquals(1,part(resized));assertEquals(1,resized.getJSONArray("pending").length());
        ui(()->{params.height=30;activity.active.browser.setLayoutParams(params);});Thread.sleep(400);JSONObject tiny=snap("unusable-viewport");assertEquals("unavailable",tiny.getString("layout"));assertEquals(0,tiny.getJSONArray("pending").length());
        ui(()->{params.height=oldH;activity.active.browser.setLayoutParams(params);});Thread.sleep(400);JSONObject restored=snap("usable-restored");assertEquals(first.getString("documentToken"),restored.getString("documentToken"));assertEquals(1,part(restored));assertEquals(1,restored.getJSONArray("pending").length());
        tick();JSONObject page=snap("visibility-current-part");eval("window.__pc2Clock.simulateHidden(true)");JSONObject hidden=PaginationUi.object(this,probe);assertTrue(hidden.getBoolean("hidden"));assertEquals(0,hidden.getJSONArray("pending").length());eval("window.__pc2Clock.simulateHidden(false)");JSONObject shown=snap("SIMULATED-JS-visibility-return");assertEquals(page.getString("part"),shown.getString("part"));assertEquals(shown.getInt("expectedDuration"),shown.getJSONArray("pending").getJSONObject(0).getInt("delay"));eval("window.__pc2Clock.restoreNativeHidden()");
        AtomicBoolean moved=new AtomicBoolean();ui(()->moved.set(activity.moveTaskToBack(true)));assertTrue(moved.get());until(()->!activity.hasWindowFocus(),5000,"native task background");Thread.sleep(250);JSONObject nativeHidden=PaginationUi.object(this,probe);nativeHidden.put("label","NATIVE-task-background").put("windowVisibility",activity.getWindow().getDecorView().getWindowVisibility()).put("hasFocus",activity.hasWindowFocus());write("pagination-lifecycle.jsonl",nativeHidden);
        ui(()->activity.startActivity(new Intent(activity,StoredHarnessActivity.class).addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT|Intent.FLAG_ACTIVITY_SINGLE_TOP)));until(()->activity.hasWindowFocus(),7000,"native return");Thread.sleep(250);JSONObject nativeShown=snap("NATIVE-task-return");assertEquals(first.getString("documentToken"),nativeShown.getString("documentToken"));assertEquals(page.getString("part"),nativeShown.getString("part"));assertEquals(1,nativeShown.getJSONArray("pending").length());if(nativeHidden.getBoolean("hidden"))assertEquals(0,nativeHidden.getJSONArray("pending").length());assertEquals(nativeShown.getInt("expectedDuration"),nativeShown.getJSONArray("pending").getJSONObject(0).getInt("delay"));
    }
    public void testRealUnacceleratedReadingInterval()throws Exception{
        setupRoot();install("two-events");PaginationUi.orient(this,true);JSONObject first=snap("REAL-no-clock-before");assertFalse(first.getBoolean("clock"));
        eval("window.__pc2Real=[];(()=>{let last=null,lastText='';const capture=()=>{let n=document.querySelector('.tv-part');if(n&&n.textContent&&(n!==last||n.textContent!==lastText)){let c=document.querySelector('.tv-context'),t=document.querySelector('.tv-text'),b=JSON.parse(document.getElementById('bootstrap').textContent);window.__pc2Real.push({at:performance.now(),part:n.textContent,counter:document.getElementById('counter').textContent,expected:eventsSlideDuration({short_description:(c?c.textContent:'')+t.textContent},b.data.settings.tv_slide_duration)});last=n;lastText=n.textContent;}};new MutationObserver(capture).observe(document.getElementById('card'),{subtree:true,childList:true,characterData:true});})()");
        ui(()->{var p=activity.active.browser.getLayoutParams();p.height=activity.active.browser.getHeight()-2;activity.active.browser.setLayoutParams(p);});long start=SystemClock.elapsedRealtime(),end=start+28000;JSONArray samples;
        do{Thread.sleep(150);samples=new JSONArray(new JSONArray("["+eval("JSON.stringify(window.__pc2Real)")+"]").getString(0));}while(samples.length()<2&&SystemClock.elapsedRealtime()<end);
        assertTrue("real timer not accelerated",samples.length()>=2);var a=samples.getJSONObject(0);var b=samples.getJSONObject(1);double delta=b.getDouble("at")-a.getDouble("at");assertEquals(a.getDouble("expected"),delta,1000);assertEquals(a.getString("counter"),b.getString("counter"));write("pagination-real-interval.jsonl",new JSONObject().put("kind","REAL unaccelerated native WebView timers").put("elapsed_start_ms",start).put("elapsed_end_ms",SystemClock.elapsedRealtime()).put("interval_ms",delta).put("samples",samples));snap("REAL-part-two");screen("pagination-real-part-two");
    }
    public void testTextNodesAndUnicodeBoundaries()throws Exception{
        setupRoot();install("control");PaginationUi.orient(this,true);JSONObject result=PaginationUi.object(this,PaginationUi.asset(this,"tv-pagination-text-safety.js"));write("pagination-text-safety.jsonl",result);assertTrue(result.toString(),result.getBoolean("pass"));
    }
}
