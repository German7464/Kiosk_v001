package org.kiosk.harness.publishing;

import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.PublicKey;
import java.security.Signature;
import java.util.*;
import org.junit.Test;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.delivery.DeliveryJson;
import static org.junit.Assert.*;
import static org.kiosk.harness.delivery.DeliveryProtocol.*;
import static org.kiosk.harness.delivery.DeliveryJson.*;

/** Display-side scope enforcement must not depend on a content-server role. */
public class PublisherScopeTest {
    private static Object number(long v){return new DeliveryJson.NumberToken(Long.toString(v));}
    private static final String GROUP="group-lab", ORIGIN="https://127.0.0.1:24443";
    private static final long NOW=1_800_000_000L;

    private static final class Key implements PublisherKey {
        private final KeyPair pair;
        Key()throws Exception{KeyPairGenerator g=KeyPairGenerator.getInstance("RSA");g.initialize(3072);pair=g.generateKeyPair();}
        public PublicKey publicKey(){return pair.getPublic();}
        public byte[] sign(byte[] domain,byte[] payload)throws Exception{
            Signature s=Signature.getInstance("SHA256withRSA");s.initSign(pair.getPrivate());s.update(domain);s.update(payload);return s.sign();
        }
        public String label(){return "test";}
        String encoded(){return Base64.getEncoder().encodeToString(pair.getPublic().getEncoded());}
        String id(){return PublisherAuthority.keyId(pair.getPublic());}
    }

    private static Map<String,Object> scope(List<String> targets){
        Map<String,Object> value=new LinkedHashMap<>();
        value.put("version",number(1));value.put("groups",List.of(GROUP));
        value.put("targets",targets);value.put("permissions",List.of("publish"));return value;
    }

    private static Map<String,Object> grant(String user,String role,String key,boolean delegate,
                                             Map<String,Object> scope){
        Map<String,Object> value=new LinkedHashMap<>();
        value.put("group_id",GROUP);value.put("origin",ORIGIN);value.put("user_id",user);
        value.put("role",role);value.put("device_key",key);value.put("issued",number(NOW-60));
        value.put("expires",number(NOW+86400));value.put("can_delegate",delegate);
        if(scope!=null)value.put("scope",scope);
        return value;
    }

    private record Fixture(Map<String,Object> policyEnvelope,List<Object> chain,Key alice,Key root) {}

    private Fixture fixture(List<String> scopeTargets,boolean scopedChild)throws Exception{
        Key root=new Key(),admin=new Key(),alice=new Key();
        Map<String,Object> policy=new LinkedHashMap<>();
        policy.put("group_id",GROUP);policy.put("origin",ORIGIN);policy.put("version",number(1));
        policy.put("issued",number(NOW-120));policy.put("expires",number(NOW+80*86400));
        policy.put("revoked_devices",List.of());policy.put("revoked_users",List.of());
        var policyEnvelope=PublisherEnvelope.sign(root,"policy",policy);
        var adminGrant=PublisherEnvelope.sign(root,"device",
            grant("admin","administrator",admin.encoded(),true,null));
        var child=grant("alice","user",alice.encoded(),false,
            scopedChild?scope(scopeTargets):null);
        var childGrant=PublisherEnvelope.sign(admin,"device",child);
        return new Fixture(policyEnvelope,List.of(adminGrant,childGrant),alice,root);
    }

    private Map<String,Object> proof(Fixture f)throws Exception{
        Map<String,Object> proof=new LinkedHashMap<>();
        proof.put("chain",f.chain());proof.put("policy",f.policyEnvelope());return proof;
    }

    private Map<String,Object> publication(String build)throws Exception{
        Map<String,Object> renderer=new LinkedHashMap<>();renderer.put("build_id",build);
        Map<String,Object> value=new LinkedHashMap<>();value.put("version",number(1));value.put("renderer",renderer);
        return value;
    }

    private Map<String,Object> plan(Fixture f,List<String> displays,Map<String,Object> publication)throws Exception{
        Map<String,Object> display=new LinkedHashMap<>();
        display.put("version",number(1));display.put("profile_id","events-lab-tv");
        display.put("revision",number(3));display.put("mode","tv");
        String config=LocalView.digest(PublisherAuthority.canonical(display));
        List<Object> targets=new ArrayList<>();
        for(String device:displays){
            Map<String,Object> target=new LinkedHashMap<>();
            target.put("device_id",device);target.put("profile_id","events-lab-tv");
            target.put("profile_version",number(3));target.put("mode","tv");
            target.put("configuration_sha256",config);targets.add(target);
        }
        Map<String,Object> value=new LinkedHashMap<>();
        value.put("group_id",GROUP);value.put("origin",ORIGIN);value.put("user_id","alice");
        value.put("device_id",f.alice().id());value.put("policy_version",number(1));
        value.put("issued",number(NOW));value.put("expires",number(NOW+3600));
        value.put("publication_sha256",LocalView.digest(PublisherAuthority.canonical(publication)));
        value.put("dependencies_sha256","1".repeat(64));value.put("renderer","2".repeat(64));
        value.put("targets",targets);value.put("parents",List.of());
        value.put("id",LocalView.digest(PublisherAuthority.canonical(value)));
        return value;
    }

    @Test public void scopedGrantAcceptsOnlyItsTargets()throws Exception{
        Fixture f=fixture(List.of("displayA"),true);
        var publication=publication("2".repeat(64));
        var allowedPlan=plan(f,List.of("displayA"),publication);
        var proof=proof(f);
        proof.put("approval",PublisherEnvelope.sign(f.alice(),"publication",allowedPlan));
        Map<String,Object> display=new LinkedHashMap<>();
        display.put("version",number(1));display.put("profile_id","events-lab-tv");
        display.put("revision",number(3));display.put("mode","tv");
        Map<String,Object> assignment=new LinkedHashMap<>();
        assignment.put("version",number(3));assignment.put("group_id",GROUP);
        assignment.put("device_id","displayA");assignment.put("profile","events-phone-lab-v1");
        assignment.put("generation",number(1));
        assignment.put("metadata_sha256",LocalView.digest(PublisherAuthority.canonical(publication)));
        assignment.put("publication",publication);assignment.put("display",display);
        assignment.put("publisher",proof);
        PublisherAuthority.assignment(proof,assignment,f.root().publicKey(),ORIGIN,NOW,0,Set.of());

        var widePlan=plan(f,List.of("displayA","displayB"),publication);
        var wideProof=proof(f);
        wideProof.put("approval",PublisherEnvelope.sign(f.alice(),"publication",widePlan));
        try{
            PublisherAuthority.permission(List.of(f.chain().get(1)),f.root().publicKey(),
                PublisherAuthority.policy(f.policyEnvelope(),f.root().publicKey(),GROUP,ORIGIN,NOW,0),NOW);
            fail("child must not verify without its administrator parent");
        }catch(java.io.IOException expected){}
        try{
            PublisherAuthority.assignment(wideProof,assignment,f.root().publicKey(),ORIGIN,NOW,0,Set.of());
            fail("target outside signed scope must be refused");
        }catch(java.io.IOException expected){}
    }
}
