package org.kiosk.harness;

import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.*;
import org.json.JSONObject;
import org.kiosk.harness.binding.*;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.storage.*;

/** Select only the explicit method on an owned empty emulator. Never configure an alternate store. */
public class DefaultStoreAcceptanceTest extends GenericPlaybackTest {
    private final AtomicReference<String> fault=new AtomicReference<>("");
    private final AtomicInteger faultHits=new AtomicInteger();
    private String a,b;
    private Map<String,String> originalBytes,originalMetadata;
    @Override PlaybackInputs.Owned inputs(String name)throws Exception {
        return PaginationInputs.capture(getInstrumentation().getTargetContext(),PaginationAssets.load(getInstrumentation().getContext(),name),name);
    }
    private Map<String,String> hashes(Path directory)throws Exception {
        Map<String,String> out=new TreeMap<>();try(var files=Files.walk(directory)){
            for(Path p:files.filter(Files::isRegularFile).toList())out.put(directory.relativize(p).toString(),LocalView.digest(Files.readAllBytes(p)));
        }return out;
    }
    private Map<String,String> metadata()throws Exception {
        Map<String,String> out=new TreeMap<>();for(String n:List.of("active.json","selected-mode.json","last-ready-kiosk.json","last-ready-tv.json"))out.put(n,LocalView.digest(Files.readAllBytes(activity.store.root.resolve(n))));return out;
    }
    private void observation(String label,String outcome)throws Exception {
        state(label);JSONObject j=new JSONObject().put("label",label).put("outcome",outcome)
            .put("root",activity.store.root.toString()).put("state",activity.state).put("pointer",activity.store.pointer())
            .put("visible",activity.visible).put("selected",activity.store.selectedMode()).put("visible_mode",activity.visibleMode)
            .put("receipt_kiosk",activity.store.receipt("kiosk")).put("receipt_tv",activity.store.receipt("tv"))
            .put("private_revision_hashes",new JSONObject(hashes(activity.store.root.resolve("revisions").resolve(activity.store.pointer()))))
            .put("fault_hits",faultHits.get());
        try(var out=getInstrumentation().getTargetContext().openFileOutput("default-store-acceptance.jsonl",android.content.Context.MODE_APPEND)){out.write((j+"\n").getBytes(java.nio.charset.StandardCharsets.UTF_8));}
    }
    private void retained(String label,String outcome,PreparedWebView original)throws Exception {
        assertSame("no renderer swap on refused candidate",original,activity.active);
        assertEquals(a,activity.store.pointer());assertEquals(a,activity.visible);assertEquals("kiosk",activity.visibleMode);
        assertEquals(a,activity.store.receipt("kiosk"));assertEquals(a,activity.store.receipt("tv"));
        assertEquals(originalBytes,hashes(activity.store.root.resolve("revisions").resolve(a)));assertEquals(originalMetadata,metadata());
        assertEquals(a,activity.store.startupChoices("kiosk").get(0).id());assertEquals(a,activity.store.startupChoices("tv").get(0).id());
        assertEquals("true",eval("document.images.length>0&&Array.from(document.images).every(i=>i.complete&&i.naturalWidth>0)"));
        tap("home-button");assertEquals("false",eval("document.getElementById('home').hidden"));tap("open-events");
        assertEquals("\"1 / 1\"",eval("document.getElementById('counter').textContent"));
        assertTrue(activity.state.equals("ready")||activity.state.equals("ready_previous_retained"));observation(label,outcome);screen("default-"+label);
    }
    private LocalView.Source source(Map<String,byte[]> all,String root,CapturedCandidate.Cancellation cancellation,boolean cancelOnRead){
        Map<String,byte[]> files=new HashMap<>();for(var e:all.entrySet())if(e.getKey().startsWith(root+"/"))files.put(e.getKey().substring(root.length()+1),e.getValue().clone());
        return new LocalView.Source(){public Set<String> files(){return Set.copyOf(files.keySet());}
            public InputStream open(String name)throws IOException {byte[] bytes=files.get(name);if(bytes==null)throw new FileNotFoundException(name);
                return new FilterInputStream(new ByteArrayInputStream(bytes)){
                    @Override public int read(byte[] block,int offset,int count)throws IOException {int n=super.read(block,offset,count);if(n>0&&cancelOnRead)cancellation.cancel();return n;}
                };}
        };
    }
    private String rejectedCapture(String kind)throws Exception {
        Map<String,byte[]> all=PaginationAssets.load(getInstrumentation().getContext(),"image-shapes");
        var evidence=PaginationInputs.evidence(all,"image-shapes");var renderer=evidence.renderer();
        if(kind.equals("changed-bytes"))all.get(evidence.packageRoot()+"/data/events.json")[0]^=1;
        if(kind.equals("missing-file"))all.remove(evidence.kioskRoot()+"/index.html");
        if(kind.equals("incompatible-renderer"))renderer=new DevelopmentWitness.Renderer("f".repeat(64),renderer.trustedJsSha256(),renderer.trustedCssSha256());
        var cancellation=new CapturedCandidate.Cancellation();
        try(var invalid=CapturedCandidate.capture(getInstrumentation().getTargetContext(),
                source(all,evidence.packageRoot(),cancellation,kind.equals("cancelled")),
                source(all,evidence.kioskRoot(),cancellation,false),source(all,evidence.tvRoot(),cancellation,false),
                evidence.pkg(),renderer,evidence.kiosk(),evidence.tv(),GenericInputs.BUDGET,cancellation)){
            fail("invalid capture reached coordinator input: "+kind);return "unexpected";
        }catch(CaptureFailure refused){
            if(kind.equals("cancelled"))assertEquals(CaptureFailure.Code.CANCELLED,refused.code);
            if(kind.equals("incompatible-renderer"))assertEquals(CaptureFailure.Code.BINDING_FAILED,refused.code);
            return "capture:"+refused.code.name();
        }
    }
    public void testOneDefaultStoreJourney()throws Exception {
        external=true;launch(null,point->{if(point.equals(fault.get())){faultHits.incrementAndGet();throw new IOException("injected_resource_failure");}},PreparedWebView.PLATFORM);
        Path expected=getInstrumentation().getTargetContext().getFilesDir().getCanonicalFile().toPath().resolve("fixture-publications");
        assertEquals(expected,activity.store.root);assertFalse("owned new emulator must start with empty default store",Files.exists(expected.resolve("active.json")));
        mode("kiosk");a=install("control");assertEquals("ready",activity.state);mode("tv");assertEquals("ready",activity.state);mode("kiosk");
        originalBytes=hashes(activity.store.root.resolve("revisions").resolve(a));originalMetadata=metadata();PreparedWebView original=activity.active;
        observation("A-both-modes-ready","ready");screen("default-A-kiosk");
        for(String kind:List.of("changed-bytes","missing-file","incompatible-renderer","cancelled"))retained(kind,rejectedCapture(kind),original);
        for(String point:List.of("development.space_checked","copy_chunk")){
            int before=faultHits.get();fault.set(point);install("image-shapes");assertTrue("injection actually reached",faultHits.get()>before);
            assertEquals("ready_previous_retained",activity.state);retained("resource-"+point,"coordinator:development_candidate_refused",original);
        }
        fault.set("");b=install("image-shapes");assertNotSame(original,activity.active);assertEquals("ready",activity.state);assertEquals(b,activity.store.pointer());
        assertEquals(b,activity.visible);assertEquals(b,activity.store.receipt("kiosk"));assertEquals(a,activity.store.receipt("tv"));observation("B-kiosk-ready-TV-receipt-still-A","ready");
        tap("next");assertEquals("\"2 / 4\"",eval("document.getElementById('counter').textContent"));tap("previous");assertEquals("\"1 / 4\"",eval("document.getElementById('counter').textContent"));screen("default-B-kiosk");
        mode("tv");assertEquals("ready",activity.state);assertEquals(b,activity.store.receipt("tv"));rotation();observation("B-TV-ready-auto-transition","ready");screen("default-B-TV");
        assertEquals(originalBytes,hashes(activity.store.root.resolve("revisions").resolve(a)));
        assertEquals("tv",activity.store.selectedMode());
    }
}
