package org.kiosk.harness.publishing;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import org.junit.Test;
import static org.junit.Assert.*;
import static org.kiosk.harness.delivery.DeliveryJson.*;

public class PublisherStateTest {
    private Path temp()throws Exception{return Files.createTempDirectory("publisher-state-");}

    private Map<String,Object> pending(String id)throws Exception{
        Map<String,Object> value=new LinkedHashMap<>();
        value.put("payload","cGF5bG9hZA==");
        value.put("signature","c2lnbmF0dXJl");
        return value;
    }

    @Test public void signedApprovalSurvivesRestartAndClearsOnlyAfterCommit()throws Exception{
        Path folder=temp();
        String id="a".repeat(64);
        var state=new PublisherState(folder.toFile());
        state.recordPending(id,pending(id),List.of(pending("chain")),"b".repeat(64));
        var reopened=new PublisherState(folder.toFile());
        var stored=reopened.pending();
        assertEquals(id,string(stored.get("id")));
        assertEquals("b".repeat(64),string(stored.get("candidate")));
        assertEquals(1,array(stored.get("chain")).size());
        reopened.commit(id,3);
        var committed=new PublisherState(folder.toFile());
        assertTrue(committed.pending().isEmpty());
        assertEquals(Set.of(id),committed.heads());
        assertEquals(3,committed.policyFloor());
        try{committed.commit("c".repeat(64),2);fail("policy floor cannot decrease");}
        catch(java.io.IOException expected){}
    }

    @Test public void stateRefusesCorruptionInsteadOfResettingAuthority()throws Exception{
        Path folder=temp();
        Files.write(folder.resolve("publisher-state.json"),"{\"version\":1,".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        try{new PublisherState(folder.toFile());fail("corrupt state must refuse");}
        catch(Exception expected){}
        Files.write(folder.resolve("publisher-state.json"),
            "{\"version\":1,\"policy_floor\":0,\"heads\":[],\"pending\":{}}".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        var state=new PublisherState(folder.toFile());
        assertTrue(state.heads().isEmpty());
        assertEquals(0,state.policyFloor());
    }

    @Test public void headsAreBoundedAndRecoveryClearsAncestry()throws Exception{
        Path folder=temp();
        var state=new PublisherState(folder.toFile());
        state.commit("d".repeat(64),1);
        assertEquals(Set.of("d".repeat(64)),state.heads());
        state.resetForRecovery();
        assertTrue(state.heads().isEmpty());
        assertEquals(0,state.policyFloor());
    }

    @Test public void maintenanceCaIsValidatedPersistedAndClearable()throws Exception{
        Path folder=temp();
        String ca;
        try(InputStream stream=PublisherStateTest.class.getResourceAsStream("/stage6/maintenance-ca.pem")){
            assertNotNull(stream);
            ca=new String(stream.readAllBytes(),StandardCharsets.US_ASCII);
        }
        var state=new PublisherState(folder.toFile());
        state.setMaintenanceCa(ca);
        var reopened=new PublisherState(folder.toFile());
        assertEquals(ca.trim(),reopened.maintenanceCa().trim());
        try{state.setMaintenanceCa("not a certificate");fail("malformed CA must refuse");}
        catch(java.io.IOException expected){}
        assertEquals(ca.trim(),state.maintenanceCa().trim());
        reopened.setMaintenanceCa("");
        assertTrue(new PublisherState(folder.toFile()).maintenanceCa().isEmpty());
    }
}
