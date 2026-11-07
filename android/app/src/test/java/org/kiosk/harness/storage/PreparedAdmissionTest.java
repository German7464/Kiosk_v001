package org.kiosk.harness.storage;
import java.util.*;
import java.io.IOException;
import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;
import org.kiosk.harness.binding.*;

public class PreparedAdmissionTest {
    interface Attempt {void run()throws Exception;}
    private void refused(Attempt run)throws Exception {try{run.run();fail("accepted invalid typed input");}catch(IOException expected){}}
    private PreparedAdmission.Request request(){
        String hash="a".repeat(64);Map<String,DevelopmentWitness.Pin> pins=Map.of("manifest.json",new DevelopmentWitness.Pin(10,hash));
        return new PreparedAdmission.Request(new DevelopmentWitness.Package(hash,hash,pins),new DevelopmentWitness.Renderer(hash,hash,hash),new DevelopmentWitness.Artifact("kiosk",hash,hash,pins),new DevelopmentWitness.Artifact("tv",hash,hash,pins),"independent-reference",Map.of("image.png",new PreparedAdmission.WindowsImage(hash,PreparedAdmission.WindowsResult.VERIFIED)),new PreparedAdmission.ImageBudget(100,1000,10,100),new CapturedCandidate.Budget(10000,100,0));
    }
    @Test public void explicitBudgetsAndCheckedArithmetic()throws Exception {
        assertEquals(804,new PreparedAdmission.ImageBudget(100,1000,10,100).estimatedLive(10,10,4));
        refused(()->new PreparedAdmission.ImageBudget(0,1000,10,100).check());refused(()->new PreparedAdmission.ImageBudget(100,1000,0,100).check());
        refused(()->new PreparedAdmission.ImageBudget(100,1000,101,100).check());refused(()->new PreparedAdmission.ImageBudget(99,1000,10,100).estimatedLive(10,10,0));
        refused(()->new PreparedAdmission.ImageBudget(Long.MAX_VALUE,Long.MAX_VALUE,10,100).estimatedLive(Integer.MAX_VALUE,Integer.MAX_VALUE,100));
        refused(()->new PreparedAdmission.ImageBudget(100,800,10,100).estimatedLive(10,10,1));
    }
    @Test public void internalRecordIsDataNotAuthorityAndDoesNotCoerce()throws Exception {
        var r=request();var encoded=new AdmissionRecord(r,"TEST_ONLY_ISSUER").encode();var decoded=AdmissionRecord.decode(encoded);
        assertEquals(r,decoded.request);assertEquals(r.factsFingerprint(),decoded.request.factsFingerprint());
        refused(()->PreparedAdmission.require(PreparedAdmission.UNAVAILABLE));
        refused(()->AdmissionRecord.decode(new JSONObject(encoded).put("authorized",true).toString()));
        refused(()->AdmissionRecord.decode(new JSONObject(encoded).put("pixels",true).toString()));
        refused(()->AdmissionRecord.decode(encoded.replace("\"pixels\":100","\"pixels\":1.0")));
        refused(()->new PreparedAdmission.Request(r.pkg(),r.renderer(),r.kiosk(),r.tv(),r.preparationReference(),r.windowsImages(),null,r.storage()).checkBudgets());
    }
    @Test public void evidenceChangesCannotPreserveIndependentBinding()throws Exception {
        var r=request();var changed=new PreparedAdmission.Request(r.pkg(),r.renderer(),r.kiosk(),r.tv(),r.preparationReference(),Map.of("image.png",new PreparedAdmission.WindowsImage("b".repeat(64),PreparedAdmission.WindowsResult.VERIFIED)),r.images(),r.storage());
        assertNotEquals(r.factsFingerprint(),changed.factsFingerprint());
        var rejected=new PreparedAdmission.Request(r.pkg(),r.renderer(),r.kiosk(),r.tv(),r.preparationReference(),Map.of("image.png",new PreparedAdmission.WindowsImage("a".repeat(64),PreparedAdmission.WindowsResult.REJECTED)),r.images(),r.storage());
        assertNotEquals(r.factsFingerprint(),rejected.factsFingerprint());
    }
}
