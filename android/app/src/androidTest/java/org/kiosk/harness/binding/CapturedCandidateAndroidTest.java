package org.kiosk.harness.binding;
import android.test.InstrumentationTestCase;
import android.content.res.AssetManager;
import java.nio.file.*;
import java.util.*;
import org.kiosk.harness.core.LocalView;
@SuppressWarnings("deprecation")
public class CapturedCandidateAndroidTest extends InstrumentationTestCase {
    private Path root;
    @Override protected void setUp()throws Exception{super.setUp();root=Files.createTempDirectory(getInstrumentation().getTargetContext().getNoBackupFilesDir().toPath(),"capture-test-");}
    @Override protected void tearDown()throws Exception{try{CaptureFiles.deleteOwned(root);}finally{super.tearDown();}}
    private void collect(AssetManager a,String path,String rel,Map<String,byte[]> all)throws Exception{
        String[] children=a.list(path);if(children.length==0){all.put(rel,LocalView.readBounded(a.open(path),2L*1024*1024));return;}
        for(String child:children)collect(a,path+"/"+child,rel.isEmpty()?child:rel+"/"+child,all);
    }
    private Map<String,byte[]> load()throws Exception{var all=new HashMap<String,byte[]>();collect(getInstrumentation().getContext().getAssets(),"generic-binding","",all);return all;}
    public void testIndependentProviders()throws Exception{CaptureVectors.independent(root,this::load);}
    public void testCorruptionBeforeOpen()throws Exception{CaptureVectors.corruptCaptured(root,this::load);}
    public void testSourceAndCapturedMutations()throws Exception{CaptureVectors.mutations(root,this::load);}
    public void testStreamAndWitnessFailures()throws Exception{CaptureVectors.faultyStreams(root,this::load);}
    public void testCancellationAndPartialCopy()throws Exception{CaptureVectors.cancellation(root,this::load);}
    public void testBudgetsAndSpace()throws Exception{CaptureVectors.budgets(root,this::load);}
    public void testCloseAndTwoOwners()throws Exception{CaptureVectors.lifecycle(root,this::load);}
    public void testUnsupportedBeforePayload()throws Exception{CaptureVectors.earlyCompatibility(root,this::load);}
    public void testPublicContextFactory()throws Exception{
        var d=new BindingVectors.Data(this::load);
        try(var s=CapturedCandidate.capture(getInstrumentation().getTargetContext(),d.p,d.k,d.t,d.pkg,d.renderer,d.kiosk,d.tv,new CapturedCandidate.Budget(8L*1024*1024,100,1024),new CapturedCandidate.Cancellation())){assertEquals(5,s.report().unchecked().size());}
        try(var children=Files.list(getInstrumentation().getTargetContext().getNoBackupFilesDir().toPath().resolve("captured-candidates"))){assertEquals(0,children.count());}
    }
    private Map<String,String> hashes(Path directory)throws Exception{
        Map<String,String> result=new TreeMap<>();try(var walk=Files.walk(directory)){
            for(Path p:walk.filter(Files::isRegularFile).toList())result.put(directory.relativize(p).toString(),LocalView.digest(Files.readAllBytes(p)));
        }return result;
    }
    public void testExistingIsolatedStoreUnchanged()throws Exception{
        // Real store serialization, test-generated receipts only: no new renderer-ready claim.
        var assets=getInstrumentation().getTargetContext().getAssets();
        var f=org.kiosk.harness.storage.PublicationFixtures.A;
        var reads=new java.util.concurrent.atomic.AtomicInteger();
        Path storeRoot=root.toFile().getCanonicalFile().toPath().resolve("existing-store");
        var store=new org.kiosk.harness.storage.FixturePublicationStore(storeRoot);
        store.install("A",new org.kiosk.harness.storage.FixtureAssetSource(assets,f,false,reads),
            new org.kiosk.harness.storage.FixtureAssetSource(assets,f,true,reads),
            new org.kiosk.harness.storage.FixtureAssetSource(assets,f,"kiosk",reads),"kiosk",org.kiosk.harness.storage.FixturePublicationStore.NONE);
        store.saveReady(f.identity(),"tv",org.kiosk.harness.storage.FixturePublicationStore.NONE);
        store.saveReady(f.identity(),"kiosk",org.kiosk.harness.storage.FixturePublicationStore.NONE);
        var before=hashes(storeRoot);Path captures=root.resolve("captures");
        CaptureVectors.faultyStreams(captures,this::load);CaptureVectors.cancellation(captures,this::load);
        CaptureVectors.budgets(captures,this::load);CaptureVectors.independent(captures,this::load);
        assertEquals(before,hashes(storeRoot));assertEquals(f.identity(),store.pointer());assertEquals("kiosk",store.selectedMode());
    }
}
