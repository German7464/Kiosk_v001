package org.kiosk.harness;
import java.nio.file.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.atomic.*;
import android.content.Intent;
import org.json.*;
import org.kiosk.harness.binding.*;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.storage.*;

/** Same ordinary default store; select explicit provisioning and fresh-start methods separately. */
public class PreparedAdmissionIntegrationTest extends GenericPlaybackTest {
    private final AtomicReference<PreparedAdmission.SourceVerifier> issuer=new AtomicReference<>(PreparedTestInputs.TEST_ONLY_ISSUER);
    private final AtomicReference<String> fault=new AtomicReference<>("");
    private void start()throws Exception {external=true;HarnessTestRunner.nextAdmissionVerifier.set(issuer::get);launch(null,p->{if(p.equals(fault.get()))throw new IOException("injected_resource_failure");},PreparedWebView.PLATFORM);assertEquals(getInstrumentation().getTargetContext().getFilesDir().getCanonicalFile().toPath().resolve("fixture-publications"),activity.store.root);}
    private Map<String,String> hashes(Path path)throws Exception {Map<String,String> out=new TreeMap<>();try(var files=Files.walk(path)){for(Path f:files.filter(Files::isRegularFile).toList())out.put(path.relativize(f).toString(),LocalView.digest(Files.readAllBytes(f)));}return out;}
    private void record(String label)throws Exception {state(label);var j=new JSONObject().put("label",label).put("pointer",activity.store.pointer()).put("visible",activity.visible).put("state",activity.state).put("mode",activity.visibleMode).put("selected",activity.store.selectedMode()).put("kiosk",activity.store.receipt("kiosk")).put("tv",activity.store.receipt("tv")).put("development",activity.store.developmentAuthorized(activity.store.pointer())).put("issuer",activity.store.admissionIssuer(activity.store.pointer()));try(var o=getInstrumentation().getTargetContext().openFileOutput("local-admission.jsonl",android.content.Context.MODE_APPEND)){o.write((j+"\n").getBytes(java.nio.charset.StandardCharsets.UTF_8));}}
    private PreparedTestInputs.Input input(String name)throws Exception{return PreparedTestInputs.capture(getInstrumentation().getTargetContext(),getInstrumentation().getContext(),name);}
    private void submit(PreparedTestInputs.Input in,PreparedAdmission.Request request)throws Exception {int reads=in.providerReads().get();AtomicBoolean accepted=new AtomicBoolean();ui(()->accepted.set(activity.installPrepared(in.capture(),request)));assertTrue(accepted.get());until(()->!activity.busy,24000,"local admission completed");assertEquals(reads,in.providerReads().get());try{in.capture().report();fail("capture ownership not closed");}catch(CaptureFailure closed){assertEquals(CaptureFailure.Code.CLOSED,closed.code);}}
    private void preserve(String a,Map<String,String> bytes,PreparedWebView view,String label)throws Exception {assertEquals("ready_previous_retained",activity.state);assertSame(view,activity.active);assertEquals(a,activity.store.pointer());assertEquals(a,activity.visible);assertEquals(a,activity.store.receipt("kiosk"));assertEquals(a,activity.store.receipt("tv"));assertEquals(bytes,hashes(activity.store.root.resolve("revisions").resolve(a)));assertFalse(activity.store.developmentAuthorized(a));record(label);}
    public void testAdmitRefuseReplaceInDefaultStore()throws Exception {
        start();assertFalse(Files.exists(activity.store.root.resolve("active.json")));mode("kiosk");var first=input("control");submit(first,first.request());assertEquals("ready",activity.state);String a=activity.store.pointer();mode("tv");mode("kiosk");var bytes=hashes(activity.store.root.resolve("revisions").resolve(a));PreparedWebView view=activity.active;record("A-ready");screen("admitted-A");
        var tests=getInstrumentation().getContext();byte[] oracle=PreparedTestInputs.asset(tests,"image-sources/pillow-oracle.json");assertEquals("266e7589cf00c906e187a92468dd7e07ca7c66b9e81511ea18136bad86c64571",LocalView.digest(oracle));
        JSONObject row=null;JSONArray rows=new JSONObject(new String(oracle,java.nio.charset.StandardCharsets.UTF_8)).getJSONArray("cases");for(int i=0;i<rows.length();i++)if(rows.getJSONObject(i).getString("id").equals("png-truncated-idat-png"))row=rows.getJSONObject(i);assertNotNull(row);assertEquals("invalid_image",row.getString("verifier_result"));
        byte[] truncated=PreparedTestInputs.asset(tests,"image-corpus/vectors/png-truncated-idat.png");assertEquals(row.getString("sha256"),LocalView.digest(truncated));
        var bad=PreparedTestInputs.capture(getInstrumentation().getTargetContext(),tests,"control",truncated);LocalImageProbe.decodeCaptured(bad.capture(),bad.request());submit(bad,bad.request());preserve(a,bytes,view,"negative-Windows-truncated-PNG-despite-Android-decode");
        var missing=input("image-shapes");submit(missing,PreparedTestInputs.replace(missing.request(),Map.of(),PreparedTestInputs.IMAGES,missing.request().renderer()));preserve(a,bytes,view,"missing-Windows-evidence");
        var mismatch=input("image-shapes");var wrong=new HashMap<>(mismatch.request().windowsImages());String n=wrong.keySet().iterator().next();wrong.put(n,new PreparedAdmission.WindowsImage("0".repeat(64),PreparedAdmission.WindowsResult.VERIFIED));submit(mismatch,PreparedTestInputs.replace(mismatch.request(),wrong,PreparedTestInputs.IMAGES,mismatch.request().renderer()));preserve(a,bytes,view,"Windows-bytes-mismatch");
        var renderer=input("image-shapes");submit(renderer,PreparedTestInputs.replace(renderer.request(),renderer.request().windowsImages(),PreparedTestInputs.IMAGES,new DevelopmentWitness.Renderer("f".repeat(64),renderer.request().renderer().trustedJsSha256(),renderer.request().renderer().trustedCssSha256())));preserve(a,bytes,view,"unsupported-renderer");
        issuer.set(null);var absent=input("image-shapes");submit(absent,absent.request());preserve(a,bytes,view,"no-issuer");issuer.set(PreparedTestInputs.TEST_ONLY_ISSUER);
        var budget=input("image-shapes");submit(budget,PreparedTestInputs.replace(budget.request(),budget.request().windowsImages(),new PreparedAdmission.ImageBudget(1,32L*1024*1024,5000,15000),budget.request().renderer()));preserve(a,bytes,view,"pixel-budget-refused");
        var noBudget=input("image-shapes");submit(noBudget,PreparedTestInputs.replace(noBudget.request(),noBudget.request().windowsImages(),null,noBudget.request().renderer()));preserve(a,bytes,view,"absent-budget-refused");
        fault.set("admission.space_checked");var resource=input("image-shapes");submit(resource,resource.request());preserve(a,bytes,view,"resource-failure");fault.set("");
        var bypass=GenericInputs.capture(getInstrumentation().getTargetContext(),tests,"B");ui(()->assertTrue(activity.installDevelopment(bypass.capture(),bypass.permit(),GenericInputs.BUDGET)));until(()->!activity.busy,24000,"legacy bypass refused");preserve(a,bytes,view,"DevelopmentPlaybackAuthority-cannot-bypass");
        assertFalse(Files.exists(activity.store.root.resolve("development-authority")));
        var second=input("image-shapes");submit(second,second.request());assertEquals("ready",activity.state);String b=activity.store.pointer();assertFalse(a.equals(b));assertEquals(a,activity.store.receipt("tv"));record("B-kiosk-ready-old-TV-receipt");tap("next");assertEquals("\"2 / 4\"",eval("document.getElementById('counter').textContent"));mode("tv");rotation();record("B-ready-both");screen("admitted-B-TV");assertEquals(bytes,hashes(activity.store.root.resolve("revisions").resolve(a)));assertFalse(activity.store.developmentAuthorized(b));
    }
    public void testPrivateRestartWithTestOnlyIssuer()throws Exception {
        start();assertEquals("ready",activity.state);assertEquals("TEST_ONLY_ISSUER",activity.store.admissionIssuer(activity.store.pointer()));assertFalse(activity.store.developmentAuthorized(activity.store.pointer()));assertEquals("tv",activity.store.selectedMode());record("fresh-private-B-TV");rotation();screen("admitted-fresh-B-TV");mode("kiosk");tap("next");assertEquals("\"2 / 4\"",eval("document.getElementById('counter').textContent"));record("fresh-private-B-kiosk");screen("admitted-fresh-B-kiosk");mode("tv");record("fresh-private-final-TV");
    }
    public void testTargetedImageGuardsOnCapturedBytes()throws Exception {
        // Targeted decoder seam checks, not additional source authority or a parity corpus rerun.
        var valid=input("control");try(var captured=valid.capture()){
            var tiny=PreparedTestInputs.replace(valid.request(),valid.request().windowsImages(),new PreparedAdmission.ImageBudget(2_000_000,1,5000,15000),valid.request().renderer());
            try{LocalImageProbe.decodeCaptured(captured,tiny);fail("live budget accepted");}catch(IOException expected){}
            try{LocalImageProbe.decodeCaptured(captured,valid.request(),p->{throw new IOException("explicit cancellation");});fail("cancel ignored");}catch(IOException expected){}
            var timed=PreparedTestInputs.replace(valid.request(),valid.request().windowsImages(),new PreparedAdmission.ImageBudget(2_000_000,32L*1024*1024,5,5),valid.request().renderer());
            try{LocalImageProbe.decodeCaptured(captured,timed,p->{try{Thread.sleep(20);}catch(InterruptedException e){Thread.currentThread().interrupt();}});fail("deadline ignored");}catch(IOException expected){assertEquals("image_deadline_exceeded",expected.getMessage());}
            AtomicBoolean refused=new AtomicBoolean();ui(()->{try{LocalImageProbe.decodeCaptured(captured,valid.request());}catch(Exception expected){refused.set(expected.getMessage().equals("image_check_on_ui_thread"));}});assertTrue(refused.get());
        }
        for(String name:List.of("empty.png","png-truncated-ihdr.png")){
            var negative=PreparedTestInputs.capture(getInstrumentation().getTargetContext(),getInstrumentation().getContext(),"control",PreparedTestInputs.asset(getInstrumentation().getContext(),"image-corpus/vectors/"+name));
            try(var captured=negative.capture()){try{LocalImageProbe.decodeCaptured(captured,negative.request());fail("bad image accepted: "+name);}catch(IOException expected){}}
        }
    }
}
