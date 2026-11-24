package org.kiosk.harness.publishing;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import org.junit.Test;
import static org.junit.Assert.*;
import static org.kiosk.harness.delivery.DeliveryProtocol.*;
import static org.kiosk.harness.delivery.DeliveryJson.*;

public class PublisherAuthorityTest {
    private Map<String,Object> signed(java.security.PrivateKey key,String kind,Map<String,Object> value)throws Exception{
        byte[] payload=PublisherAuthority.canonical(Map.of("version",1L,"kind",kind,"value",value));
        var signature=java.security.Signature.getInstance("SHA256withRSA");
        signature.initSign(key);signature.update(PublisherAuthority.DOMAIN);signature.update(payload);
        return Map.of("payload",Base64.getEncoder().encodeToString(payload),"signature",Base64.getEncoder().encodeToString(signature.sign()));
    }
    @Test public void ninetyDayMaintenanceHasBoundedFourteenDayAuthorityOverlap()throws Exception{
        var generator=java.security.KeyPairGenerator.getInstance("RSA");generator.initialize(3072);
        var root=generator.generateKeyPair();var device=generator.generateKeyPair();
        long issued=2_000_000_000L, expires=issued+104L*86400L;
        String origin="https://192.168.1.124:28443",group="group-stage5";
        Map<String,Object> policy=new TreeMap<>(Map.of("group_id",group,"origin",origin,"version",1L,
            "issued",issued,"expires",expires,"revoked_devices",List.of(),"revoked_users",List.of()));
        var envelope=signed(root.getPrivate(),"policy",policy);
        var current=PublisherAuthority.policy(envelope,root.getPublic(),group,origin,issued+90L*86400L,0);
        Map<String,Object> grant=new TreeMap<>(Map.of("group_id",group,"origin",origin,"user_id","admin",
            "role","administrator","device_key",Base64.getEncoder().encodeToString(device.getPublic().getEncoded()),
            "issued",issued,"expires",expires,"can_delegate",true));
        var chain=List.<Object>of(signed(root.getPrivate(),"device",grant));
        assertEquals("admin",str(PublisherAuthority.permission(chain,root.getPublic(),current,issued+90L*86400L).grant(),"user_id"));
        try{PublisherAuthority.policy(envelope,root.getPublic(),group,origin,expires,0);fail("Expired overlap must fail closed");}
        catch(java.io.IOException expected){}
        policy.put("expires",expires+1);
        try{PublisherAuthority.policy(signed(root.getPrivate(),"policy",policy),root.getPublic(),group,origin,issued,0);fail("Unbounded extension must fail closed");}
        catch(java.io.IOException expected){}
    }
    private Map<String,Object> fixture()throws Exception{return json(Files.readAllBytes(Path.of(System.getProperty("publishingFixture"))),131072);}
    @Test public void pythonSignedApprovalAndCanonicalUnicodeAgree()throws Exception{
        var f=fixture();var root=PublisherAuthority.publicKey(str(f,"root_spki"));
        var result=PublisherAuthority.assignment(obj(f,"proof"),obj(f,"assignment"),root,str(f,"origin"),num(f,"now"),0,Set.of());
        assertEquals(str(f,"plan_id"),str(result.plan(),"id"));
        for(Object item:array(f.get("canonical"))){var vector=object(item);StringBuilder hex=new StringBuilder();
            for(byte b:PublisherAuthority.canonical(vector.get("value")))hex.append(String.format(Locale.ROOT,"%02x",b&255));
            assertEquals(str(vector,"hex"),hex.toString());
        }
    }
    @Test public void targetTamperKnownConflictExpiryAndPolicyRollbackRefused()throws Exception{
        for(String scenario:List.of("target","conflict","expiry","policy")){
            var f=fixture();var assignment=obj(f,"assignment");
            if(scenario.equals("target"))assignment.put("device_id","other");
            try{
                PublisherAuthority.assignment(obj(f,"proof"),assignment,PublisherAuthority.publicKey(str(f,"root_spki")),
                    str(f,"origin"),num(f,"now")+(scenario.equals("expiry")?86400:0),scenario.equals("policy")?2:0,
                    scenario.equals("conflict")?Set.of("5".repeat(64)):Set.of());
                fail(scenario+" must be refused");
            }catch(java.io.IOException expected){}
        }
    }

    private Map<String,Object> ancestryFixture()throws Exception{return json(Files.readAllBytes(Path.of(System.getProperty("publishingAncestryFixture"))),131072);}

    @Test public void missedExpiredAncestorUsesCurrentAuthorizationAndHashEdges()throws Exception{
        var f=ancestryFixture();Set<String> heads=Set.of(string(array(f.get("known_heads")).get(0)));
        var result=PublisherAuthority.assignment(obj(f,"proof"),obj(f,"assignment"),PublisherAuthority.publicKey(str(f,"root_spki")),str(f,"origin"),num(f,"now"),0,heads);
        assertEquals(str(f,"plan_id"),str(result.plan(),"id"));
        // Expired historical data cannot extend current admission validity.
        try{PublisherAuthority.assignment(obj(f,"proof"),obj(f,"assignment"),PublisherAuthority.publicKey(str(f,"root_spki")),str(f,"origin"),num(f,"now")+86400,0,heads);fail();}
        catch(java.io.IOException expected){}
    }

    @Test public void omittedForgedAndRehashedEdgesCannotEraseKnownFork()throws Exception{
        for(String scenario:List.of("missing","tampered","rehashed","fork","duplicate","over_limit")){
            var f=ancestryFixture();var proof=obj(f,"proof");var ancestry=array(proof.get("ancestry"));
            Set<String> heads=Set.of(string(array(f.get("known_heads")).get(0)));
            if(scenario.equals("missing"))proof.remove("ancestry");
            if(scenario.equals("tampered")||scenario.equals("rehashed")){
                var node=object(ancestry.get(0));node.put("parents",List.of("9".repeat(64)));
                if(scenario.equals("rehashed")){var body=new TreeMap<>(node);body.remove("id");node.put("id",org.kiosk.harness.core.LocalView.digest(PublisherAuthority.canonical(body)));}
            }
            if(scenario.equals("fork"))heads=Set.of("9".repeat(64));
            if(scenario.equals("duplicate"))ancestry.add(ancestry.get(0));
            if(scenario.equals("over_limit"))while(ancestry.size()<129)ancestry.add(ancestry.get(0));
            try{
                PublisherAuthority.assignment(proof,obj(f,"assignment"),PublisherAuthority.publicKey(str(f,"root_spki")),str(f,"origin"),num(f,"now"),0,heads);
                fail(scenario+" must be refused");
            }catch(java.io.IOException expected){}
        }
    }
}
