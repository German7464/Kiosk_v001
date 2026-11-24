package org.kiosk.harness.binding;
import java.nio.file.*;
import java.util.*;
import org.junit.*;
public class CapturedCandidateTest {
    private Path root;
    @Before public void setup()throws Exception{root=Files.createTempDirectory("capture-tests-");}
    @After public void cleanup()throws Exception{CaptureFiles.deleteOwned(root);}
    private Map<String,byte[]> load()throws Exception{
        Path dir=Path.of(System.getProperty("bindingFixtureRoot"));Map<String,byte[]> all=new HashMap<>();
        try(var walk=Files.walk(dir)){for(Path p:walk.filter(Files::isRegularFile).toList())all.put(dir.relativize(p).toString().replace('\\','/'),Files.readAllBytes(p));}return all;
    }
    @Test public void independentProviders()throws Exception{CaptureVectors.independent(root,this::load);}
    @Test public void corruptionBeforeOpen()throws Exception{CaptureVectors.corruptCaptured(root,this::load);}
    @Test public void sourceAndCapturedMutations()throws Exception{CaptureVectors.mutations(root,this::load);}
    @Test public void streamAndWitnessFailures()throws Exception{CaptureVectors.faultyStreams(root,this::load);}
    @Test public void cancellationAndPartialCopy()throws Exception{CaptureVectors.cancellation(root,this::load);}
    @Test public void budgetsAndSpace()throws Exception{CaptureVectors.budgets(root,this::load);}
    @Test public void closeAndTwoOwners()throws Exception{CaptureVectors.lifecycle(root,this::load);}
    @Test public void unsupportedBeforePayload()throws Exception{CaptureVectors.earlyCompatibility(root,this::load);}
}
