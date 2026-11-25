package org.kiosk.harness.storage;

import java.io.IOException;
import java.util.Map;
import org.json.JSONObject;
import org.junit.Test;
import org.kiosk.harness.binding.DevelopmentWitness;
import org.kiosk.harness.delivery.PageReleaseProtocol;
import static org.junit.Assert.*;

public class PageAdmissionRecordTest {
    private interface Attempt{void run()throws Exception;}
    private static void refused(Attempt attempt)throws Exception{
        try{attempt.run();fail("accepted invalid page admission record");}
        catch(IOException expected){}
    }
    private static DevelopmentWitness.Pin pin(String hash){return new DevelopmentWitness.Pin(1,hash);}
    private static AdmissionRecord.Page page(String destination,String projection){
        return new AdmissionRecord.Page("native-page-release-v2","a".repeat(64),"b".repeat(64),
            "c".repeat(64),"d".repeat(64),PageReleaseProtocol.SHIPPED_JS_SHA256,
            PageReleaseProtocol.SHIPPED_CSS_SHA256,destination,projection,"e".repeat(64),
            "f".repeat(64),"{\"plan\":1}","{\"target\":1}","stage6-page-release-v2",Map.of("manifest.json",pin("1".repeat(64))),
            Map.of("view.json",pin("2".repeat(64))),1024,16,16);
    }

    @Test public void pageRecordRoundTripsExactFieldsAndRejectsUntypedData()throws Exception{
        AdmissionRecord.Page source=page("android-pages-v1","kiosk-landscape");
        String encoded=AdmissionRecord.encodePage(source);
        AdmissionRecord decoded=AdmissionRecord.decodePage(encoded);
        assertNotNull(decoded.page);
        assertEquals(source.packageId(),decoded.page.packageId());
        assertEquals(source.revision(),decoded.page.revision());
        assertEquals(source.destination(),decoded.page.destination());
        assertEquals(source.projection(),decoded.page.projection());
        assertEquals(source.metadataSha256(),decoded.page.metadataSha256());
        assertEquals(source.plan(),decoded.page.plan());
        assertEquals(source.target(),decoded.page.target());
        assertEquals(source.packageFiles(),decoded.page.packageFiles());
        assertEquals(source.viewFiles(),decoded.page.viewFiles());

        JSONObject unknown=new JSONObject(encoded).put("authorized",true);
        refused(()->AdmissionRecord.decodePage(unknown.toString()));
        refused(()->AdmissionRecord.decodePage(new JSONObject(encoded).put("schema",1).toString()));
        refused(()->AdmissionRecord.decodePage(new JSONObject(encoded).put("projection","bad").toString()));
        refused(()->AdmissionRecord.decodePage(new JSONObject(encoded).put("identity","A".repeat(64)).toString()));
        refused(()->AdmissionRecord.decodePage(encoded.replace("\"store_bytes\":1024","\"store_bytes\":1.5")));
    }
}
