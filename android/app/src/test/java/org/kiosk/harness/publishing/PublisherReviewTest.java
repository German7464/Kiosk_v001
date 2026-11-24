package org.kiosk.harness.publishing;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.*;
import java.util.*;
import org.junit.Test;
import static org.junit.Assert.*;
import static org.kiosk.harness.delivery.DeliveryJson.*;
import static org.kiosk.harness.delivery.DeliveryProtocol.*;

public class PublisherReviewTest {
    @Test public void legacyNullableDateAndIndependentImageVariantsArePreserved()throws Exception {
        var payload=new TreeMap<String,Object>();
        payload.putAll(Map.of("title","Legacy","short_description","","full_description","","place","",
            "sort_order",0L,"status","active","tags",List.of("Tag with spaces")));
        payload.put("event_date",null);
        payload.put("sort_order",new NumberToken("0"));
        payload.put("images",Arrays.asList("/static/uploads/card.jpg","/static/uploads/card.jpg",null));
        var result=PublisherReview.derive(Map.of("1",Map.of("payload",payload)),Map.of(),7L);
        var event=object(array(result.get("events")).get(0));
        assertNull(event.get("event_date")); assertNull(event.get("image_thumb"));
        assertEquals("/static/uploads/card.jpg",event.get("image_tv"));
        assertEquals("/static/uploads/card.jpg",event.get("image_kiosk"));
    }
    private byte[] fixtureBytes()throws Exception{
        return Files.readAllBytes(Path.of(System.getProperty("publishingCandidateFixture")));
    }
    private Map<String,Object> fixture()throws Exception{return json(fixtureBytes(),262144);}
    private Map<String,Object> document()throws Exception{return obj(fixture(),"document");}
    private byte[] publicData(Map<String,Object> fixture)throws Exception{
        return Base64.getDecoder().decode(str(fixture,"data_base64"));
    }
    private PublicKey deviceKey(Map<String,Object> fixture)throws Exception{
        return PublisherAuthority.publicKey(str(fixture,"device_spki"));
    }

    private static final class SoftwareKey implements PublisherKey{
        private final KeyPair pair;
        SoftwareKey()throws Exception{
            KeyPairGenerator generator=KeyPairGenerator.getInstance("RSA");
            generator.initialize(3072);pair=generator.generateKeyPair();
        }
        public PublicKey publicKey(){return pair.getPublic();}
        public byte[] sign(byte[] domain,byte[] payload)throws Exception{
            Signature signer=Signature.getInstance("SHA256withRSA");
            signer.initSign(pair.getPrivate());signer.update(domain);signer.update(payload);
            return signer.sign();
        }
        public String label(){return "test-software";}
    }

    @Test public void mappingMatchesPythonDerivationAndUiFacts()throws Exception{
        var fixture=fixture();var data=object(parse(publicData(fixture),PublisherReview.MAX_PUBLIC_DATA));
        var derived=PublisherReview.derive(obj(document(),"objects"),obj(document(),"settings"),
            num(document(),"content_version"));
        assertArrayEquals(PublisherAuthority.canonical(derived),PublisherAuthority.canonical(data));
        var events=array(derived.get("events"));
        assertEquals(2,events.size());
        assertEquals("Alpha",str(object(events.get(0)),"title"));
        assertEquals("Zebra",str(object(events.get(1)),"title"));
        assertEquals(List.of(1L,2L),array(object(events.get(1)).get("tag_ids")));
        assertEquals("/static/uploads/z.jpg",str(object(events.get(1)),"image_thumb"));
    }

    @Test public void exactCandidateVerifiesAndResolvesTheSignedPlan()throws Exception{
        var fixture=fixture();var plan=PublisherReview.verify(document(),publicData(fixture),
            num(fixture,"now"),Set.of(),deviceKey(fixture));
        assertEquals(str(obj(document(),"plan"),"id"),str(plan,"id"));
        assertEquals(1,array(plan.get("targets")).size());
    }

    @Test public void substitutedDraftOrEventsBytesAreRefused()throws Exception{
        var fixture=fixture();
        var changed=document();
        obj(changed,"objects").put("1",obj(document(),"objects").get("1"));
        var entry=object(obj(changed,"objects").get("1"));
        var payload=obj(entry,"payload");payload.put("title","Substituted");
        try{
            PublisherReview.verify(changed,publicData(fixture),num(fixture,"now"),Set.of(),deviceKey(fixture));
            fail("substituted draft must be refused");
        }catch(IOException expected){}
        var data=object(parse(publicData(fixture),PublisherReview.MAX_PUBLIC_DATA));
        var first=object(array(data.get("events")).get(0));first.put("title","Substituted");
        try{
            PublisherReview.verify(document(),PublisherAuthority.canonical(data),num(fixture,"now"),Set.of(),deviceKey(fixture));
            fail("substituted package bytes must be refused");
        }catch(IOException expected){}
    }

    @Test public void envelopeIsCanonicalAndBindsTheExactValue()throws Exception{
        var key=new SoftwareKey();
        Map<String,Object> value=new LinkedHashMap<>();value.put("b","Ä");value.put("a",List.of(1L,2L));
        var envelope=PublisherEnvelope.sign(key,"publication",value);
        assertArrayEquals(PublisherAuthority.canonical(value),PublisherAuthority.canonical(PublisherAuthority.verified(envelope,key.publicKey(),"publication")));
        var tampered=new LinkedHashMap<>(envelope);tampered.put("signature",
            Base64.getEncoder().encodeToString(new byte[384]));
        try{PublisherAuthority.verified(tampered,key.publicKey(),"publication");fail();}
        catch(java.io.IOException expected){}
    }

    @Test public void reviewRefusesAKeyThatDidNotPrepareThePlan()throws Exception{
        var fixture=fixture();
        try{
            PublisherReview.verify(document(),publicData(fixture),num(fixture,"now"),Set.of(),
                new SoftwareKey().publicKey());
            fail("other device key must be refused");
        }catch(IOException expected){}
    }

    @Test public void durableKnownHeadBlocksAnUnprovedBranch()throws Exception{
        var fixture=fixture();
        try{
            PublisherReview.verify(document(),publicData(fixture),num(fixture,"now"),
                Set.of("9".repeat(64)),deviceKey(fixture));
            fail("known head must require ancestry");
        }catch(IOException expected){}
    }
}
