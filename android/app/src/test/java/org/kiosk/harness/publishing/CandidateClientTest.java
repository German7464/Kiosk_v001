package org.kiosk.harness.publishing;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.junit.Test;
import static org.junit.Assert.*;
import static org.kiosk.harness.delivery.DeliveryJson.*;
import static org.kiosk.harness.delivery.DeliveryProtocol.*;

public class CandidateClientTest {
    private static final String ID="a".repeat(64);
    private static final String TOKEN="0123456789abcdef".repeat(4);
    private static final String MAINTENANCE="https://maintenance.example:443";

    private static NumberToken n(long value){return new NumberToken(Long.toString(value));}
    private static Map<String,Object> m(Object... values){
        if(values.length%2!=0)throw new IllegalArgumentException("pairs");
        Map<String,Object> result=new LinkedHashMap<>();
        for(int i=0;i<values.length;i+=2)result.put((String)values[i],values[i+1]);
        return result;
    }
    private static List<Object> a(Object... values){return new ArrayList<>(Arrays.asList(values));}
    private static Map<String,Object> metadata()throws Exception{
        try(InputStream stream=CandidateClientTest.class.getResourceAsStream("/stage6/page-release-vectors.json")){
            if(stream==null)throw new IOException("stage6_vector_missing");
            Map<String,Object> vector=json(stream.readAllBytes(),1024*1024);
            return object(parse(str(vector,"metadata_canonical").getBytes(StandardCharsets.UTF_8),1024*1024));
        }
    }
    private static Map<String,Object> copy(Map<String,Object> value)throws Exception{
        return object(parse(PublisherAuthority.canonical(value),1024*1024));
    }
    private static String refused(Throwing action)throws Exception{
        try{action.run();fail("accepted unsafe candidate artifact inventory");return "";}
        catch(Exception failure){return failure.getMessage();}
    }
    private interface Throwing{void run()throws Exception;}

    @Test public void inventoryPreflightRejectsExecutableMissingEntrypointAndTransportGroups()throws Exception{
        List<CandidateClient.Artifact> inventory=CandidateClient.packageInventory(metadata());
        assertEquals(List.of("manifest.json","data/page-release.json"),
            inventory.stream().map(CandidateClient.Artifact::path).toList());

        Map<String,Object> executable=copy(metadata());
        Map<String,Object> executablePackage=obj(obj(executable,"publication"),"package");
        List<Object> rows=new ArrayList<>(array(executablePackage.get("files")));
        rows.add(m("path","evil.js","size",n(8),"sha256","9".repeat(64)));
        executablePackage.put("files",rows);
        assertEquals("page_release_data_only",refused(()->CandidateClient.packageInventory(executable)));

        Map<String,Object> missing=copy(metadata());
        Map<String,Object> missingPackage=obj(obj(missing,"publication"),"package");
        List<Object> missingRows=new ArrayList<>();
        for(Object item:array(missingPackage.get("files")))
            if(!"data/page-release.json".equals(str(object(item),"path")))missingRows.add(item);
        missingRows.add(m("path","static/uploads/card.png","size",n(5),"sha256","9".repeat(64)));
        missingPackage.put("files",missingRows);
        assertEquals("page_release_entrypoint",refused(()->CandidateClient.packageInventory(missing)));

        Map<String,Object> transport=copy(metadata());
        Map<String,Object> publication=obj(transport,"publication");
        obj(publication,"kiosk").put("files",a(m("path","view.json","size",n(1),"sha256","9".repeat(64))));
        assertEquals("publisher_metadata_inventory",refused(()->CandidateClient.packageInventory(transport)));

        Map<String,Object> revision=copy(metadata());
        obj(revision,"publication").put("revision","7".repeat(64));
        assertEquals("publisher_content_substitution",refused(()->CandidateClient.packageInventory(revision)));
    }

    @Test public void artifactUrlPercentEncodesExactSegmentsAndRefusesAliases()throws Exception{
        assertEquals("/editor/native/candidates/"+ID+"/package/static/uploads/card%20one.png",
            CandidateClient.artifactUrl(ID,"static/uploads/card one.png"));
        assertEquals("/editor/native/candidates/"+ID+"/package/static/uploads/caf%C3%A9.png",
            CandidateClient.artifactUrl(ID,"static/uploads/café.png"));
        assertThrows(IOException.class,()->CandidateClient.artifactUrl(ID,"static/uploads/../card.png"));
        assertThrows(IOException.class,()->CandidateClient.artifactUrl(ID,"static/uploads/card.png?raw=1"));
        assertThrows(IOException.class,()->CandidateClient.artifactUrl("not-a-hash","static/uploads/card.png"));
    }

    @Test public void nativeClientRequiresPinnedMaintenanceCa()throws Exception{
        assertThrows(IOException.class,()->new CandidateClient(MAINTENANCE,TOKEN,""));
        assertThrows(IOException.class,()->new CandidateClient(MAINTENANCE,TOKEN,null));
        assertNotNull(new CandidateClient(m("origin",MAINTENANCE)));
    }

    @Test public void approveResponseRequiresExplicitDistribution()throws Exception{
        Map<String,Object> ready=m("version",n(1),"state","approved",
            "distribution",m("state","ready","targets",n(2)));
        assertSame(ready,CandidateClient.approveResponse(ready));
        assertThrows(IOException.class,()->CandidateClient.approveResponse(
            m("version",n(1),"state","approved")));
        assertThrows(IOException.class,()->CandidateClient.approveResponse(
            m("version",n(1),"state","pending","distribution",m("state","pending"))));
    }
}
