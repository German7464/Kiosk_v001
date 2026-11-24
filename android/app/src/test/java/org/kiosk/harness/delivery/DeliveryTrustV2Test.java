package org.kiosk.harness.delivery;

import org.junit.Test;
import static org.junit.Assert.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.JSONObject;
import org.kiosk.harness.core.LocalView;

/**
 * lan-trust-lifecycle-v2 published vectors: root-signed group trust that pins the intermediate
 * issuer SPKI (so a legitimate serving-leaf rotation needs no re-enrollment) and stays distinct
 * from legacy v1 leaf-pin trust. Fixtures are the public handoff files, byte-identical.
 */
public class DeliveryTrustV2Test {
    static final String ISSUER="229dfab19434b72bdd1b0677811ee353649a7b24008451f66bf74c8a6165b3fd";
    static final String ROOT_DER_SHA256="c2d15228fde7727692fe5b933a53935ac5cc26b9369f8763908525bb4d2ea863";
    static final String BOOTSTRAP_FILE_SHA256="7e21ff357eaa6fa4cec1d1b3fbcf72fd9eaa5e8cbc49f5315c92b247694974b3";
    static final String PAYLOAD_SHA256="442443a92cbea9c07fbdd2bbfc6b5191754c11e38b01436592c3031c02b8dc94";

    interface Checked{void run()throws Exception;}
    static void refused(Checked work)throws Exception{try{work.run();fail("must refuse");}catch(AssertionError failure){throw failure;}catch(Exception expected){}}
    static byte[] resource(String path)throws Exception{try(var in=DeliveryTrustV2Test.class.getResourceAsStream(path)){return in.readAllBytes();}}
    static String text(byte[] bytes){return new String(bytes,StandardCharsets.UTF_8);}
    static byte[] jsonBytes(JSONObject value){return value.toString().getBytes(StandardCharsets.UTF_8);}
    static JSONObject json(String path)throws Exception{return new JSONObject(text(resource(path)));}
    static DeliveryProtocol.Bootstrap bootstrap(String path)throws Exception{
        byte[] input=resource(path);return DeliveryProtocol.bootstrap(input,new JSONObject(text(input)).getLong("issued_at")+1);
    }
    static DeliveryProtocol.Bootstrap anchor()throws Exception{return bootstrap("/delivery-v2/bootstrap.json");}
    static JSONObject envelope()throws Exception{return json("/delivery-v2/trust.json");}
    static String payloadText(JSONObject envelope)throws Exception{return text(Base64.getDecoder().decode(envelope.getString("payload_base64")));}
    static byte[] repack(JSONObject envelope,String payload){
        try{return jsonBytes(envelope.put("payload_base64",Base64.getEncoder().encodeToString(payload.getBytes(StandardCharsets.US_ASCII))));}
        catch(Exception unusable){throw new IllegalStateException(unusable);}
    }

    @Test public void publishedVectorVerifiesWithIssuerPin()throws Exception{
        var b=anchor();long now=b.issued()+1;
        var accepted=DeliveryProtocol.trustV2(resource("/delivery-v2/trust.json"),b,ISSUER,now,0,"");
        JSONObject vectors=json("/delivery-v2/vectors.json").getJSONObject("trust_valid");
        assertEquals(1,accepted.trust().generation());
        assertEquals(PAYLOAD_SHA256,accepted.trust().digest());
        assertEquals(vectors.getString("payload_sha256"),PAYLOAD_SHA256);
        assertEquals(vectors.getString("payload_utf8"),payloadText(envelope()));
        assertEquals(ISSUER,accepted.issuerPin());
        assertEquals(b.expires(),accepted.trust().expires());
        assertEquals("4b696f736b2f47726f757054727573742f763200",vectors.getString("domain_hex"));
    }

    @Test public void envelopeVersionSelectsTheVerifierAndV1IsNotReinterpreted()throws Exception{
        var b=anchor();long now=b.issued()+1;
        byte[] v2=resource("/delivery-v2/trust.json");
        assertEquals(2,DeliveryProtocol.envelopeVersion(v2));
        byte[] downgraded=jsonBytes(envelope().put("version",1));
        assertEquals(1,DeliveryProtocol.envelopeVersion(downgraded));
        refused(()->DeliveryProtocol.trustV2(downgraded,b,ISSUER,now,0,""));
        refused(()->DeliveryProtocol.trust(v2,b,ISSUER,now,0,""));

        // The legacy v1 fixture still verifies through the untouched v1 verifier only.
        var legacyBootstrap=bootstrap("/delivery-v1/bootstrap.json");
        byte[] legacyTrust=resource("/delivery-v1/trust.json");
        JSONObject legacyPayload=new JSONObject(text(Base64.getDecoder().decode(new JSONObject(text(legacyTrust)).getString("payload_base64"))));
        String leafPin=legacyPayload.getJSONArray("servers").getJSONObject(0).getString("tls_spki_sha256");
        long legacyNow=legacyPayload.getLong("issued_at")+1;
        assertEquals(1,DeliveryProtocol.envelopeVersion(legacyTrust));
        assertEquals(legacyPayload.getLong("generation"),DeliveryProtocol.trust(legacyTrust,legacyBootstrap,leafPin,legacyNow,0,"").generation());
        refused(()->DeliveryProtocol.trustV2(legacyTrust,legacyBootstrap,ISSUER,legacyNow,0,""));
    }

    @Test public void payloadVersionRewriteWithoutResigningIsRefused()throws Exception{
        var b=anchor();long now=b.issued()+1;JSONObject e=envelope();
        byte[] attacked=repack(e,payloadText(e).replace("\"version\":2","\"version\":1"));
        refused(()->DeliveryProtocol.trustV2(attacked,b,ISSUER,now,0,""));
    }

    @Test public void nonCanonicalPayloadIsRefused()throws Exception{
        var b=anchor();long now=b.issued()+1;JSONObject e=envelope();
        refused(()->DeliveryProtocol.trustV2(repack(e,new JSONObject(payloadText(e)).toString(2)),b,ISSUER,now,0,""));
    }

    @Test public void wrongOrMissingIssuerPinIsRefused()throws Exception{
        var b=anchor();long now=b.issued()+1;byte[] trust=resource("/delivery-v2/trust.json");
        refused(()->DeliveryProtocol.trustV2(trust,b,"",now,0,""));
        refused(()->DeliveryProtocol.trustV2(trust,b,"0".repeat(64),now,0,""));
        // The serving leaf SPKI is a v1 pin; pinning it must not satisfy the v2 issuer rule.
        refused(()->DeliveryProtocol.trustV2(trust,b,"e6e533fa00c51c545028e61194833aebdd393776f0bee264d5de47ccdaf888ca",now,0,""));
    }

    @Test public void rollbackAndSameGenerationConflictAreRefused()throws Exception{
        var b=anchor();long now=b.issued()+1;byte[] trust=resource("/delivery-v2/trust.json");
        refused(()->DeliveryProtocol.trustV2(trust,b,ISSUER,now,2,""));
        refused(()->DeliveryProtocol.trustV2(trust,b,ISSUER,now,1,"b".repeat(64)));
        assertEquals(PAYLOAD_SHA256,DeliveryProtocol.trustV2(trust,b,ISSUER,now,1,PAYLOAD_SHA256).trust().digest());
    }

    @Test public void expiredFutureAndEdgeWindowsAreEnforced()throws Exception{
        var b=anchor();byte[] trust=resource("/delivery-v2/trust.json");
        long issued=b.issued(),expires=b.expires();
        refused(()->DeliveryProtocol.trustV2(trust,b,ISSUER,expires,0,""));
        refused(()->DeliveryProtocol.trustV2(trust,b,ISSUER,issued-1,0,""));
        assertEquals(ISSUER,DeliveryProtocol.trustV2(trust,b,ISSUER,issued,0,"").issuerPin());
        assertEquals(ISSUER,DeliveryProtocol.trustV2(trust,b,ISSUER,expires-1,0,"").issuerPin());
    }

    @Test public void mismatchedBootstrapIdentityIsRefused()throws Exception{
        JSONObject source=json("/delivery-v2/bootstrap.json");long issued=source.getLong("issued_at");
        for(String field:List.of("group_id","server_id","origin")){
            JSONObject changed=new JSONObject(text(resource("/delivery-v2/bootstrap.json")))
                .put(field,field.equals("origin")?"https://192.168.1.125:19443":"ffffffff-ffff-ffff-ffff-ffffffffffff");
            try{
                DeliveryProtocol.Bootstrap b=DeliveryProtocol.bootstrap(jsonBytes(changed),issued+1);
                refused(()->DeliveryProtocol.trustV2(resource("/delivery-v2/trust.json"),b,ISSUER,issued+1,0,""));
            }catch(java.io.IOException expected){/* rejected even earlier, also acceptable */}
        }
    }

    @Test public void bootstrapAcceptsExactlyOneRootAndRejectsAnAppendedIntermediate()throws Exception{
        byte[] input=resource("/delivery-v2/bootstrap.json");long issued=new JSONObject(text(input)).getLong("issued_at");
        String root=text(resource("/delivery-v2/root-ca.pem")).trim(),intermediate=text(resource("/delivery-v2/intermediate.pem")).trim();
        DeliveryProtocol.Bootstrap single=DeliveryProtocol.bootstrap(input,issued+1);
        assertEquals(ROOT_DER_SHA256,single.caFingerprint());
        assertTrue(new NativeTransport(single)!=null);
        String mixed=root+"\n"+intermediate+"\n";
        DeliveryProtocol.Bootstrap appended=DeliveryProtocol.bootstrap(jsonBytes(new JSONObject(text(input)).put("tls_ca_pem",mixed)),issued+1);
        refused(appended::caFingerprint);
        refused(()->new NativeTransport(appended));
    }

    @Test public void publishedBootstrapFixtureIsTheExactHandoffFile()throws Exception{
        byte[] input=resource("/delivery-v2/bootstrap.json");JSONObject source=new JSONObject(text(input));
        assertEquals(BOOTSTRAP_FILE_SHA256,LocalView.digest(input));
        assertEquals("5b4727ba-06f3-4d39-8f2d-cbff796510cb",source.getString("bootstrap_id"));
        assertEquals("https://192.168.1.124:19443",source.getString("origin"));
        assertEquals(1,source.getInt("version"));
        assertEquals(10,source.length());
        JSONObject vectors=json("/delivery-v2/vectors.json");
        assertEquals("lan-trust-lifecycle-v2",vectors.getString("contract"));
        assertEquals(source.getString("group_spki_base64"),vectors.getString("group_spki_base64"));
        assertEquals(source.getString("group_key_id"),vectors.getJSONObject("trust_valid").getJSONObject("envelope").getString("key_id"));
        assertEquals(source.getString("group_id"),new JSONObject(payloadText(envelope())).getString("group_id"));
    }
}
