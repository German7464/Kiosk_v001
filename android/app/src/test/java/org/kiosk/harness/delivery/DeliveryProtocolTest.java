package org.kiosk.harness.delivery;

import org.junit.Test;
import static org.junit.Assert.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.*;

public class DeliveryProtocolTest {
    private byte[] fixture(String name)throws Exception {try(var in=getClass().getResourceAsStream("/delivery-v1/"+name+".json")){return in.readAllBytes();}}
    private byte[] bytes(String s){return s.getBytes(StandardCharsets.UTF_8);}
    private void refused(Checked test)throws Exception {try{test.run();fail("must refuse");}catch(AssertionError e){throw e;}catch(Exception expected){}}
    private interface Checked {void run()throws Exception;}
    @Test public void strictMalformedJson()throws Exception {
        for(String invalid:List.of("{\"a\":1,\"a\":2}","{}x","\ufeff{}","{\"x\":NaN}","{\"x\":\"\\ud800\"}"))refused(()->DeliveryProtocol.json(bytes(invalid),200));
        for(String number:List.of("true","1.0","1e0","-1","9223372036854775808"))refused(()->DeliveryJson.integer(DeliveryJson.parse(bytes(number),100)));
        refused(()->DeliveryProtocol.json(new byte[]{(byte)0xc0,(byte)0xaf},100));
    }
    @Test public void bootstrapIsIndependentBoundExactSchema()throws Exception {
        byte[] input=fixture("bootstrap");JSONObject j=new JSONObject(new String(input,StandardCharsets.UTF_8));long now=j.getLong("issued_at")+1;
        var b=DeliveryProtocol.bootstrap(input,now);assertEquals(j.getString("group_id"),b.group());
        refused(()->DeliveryProtocol.bootstrap(input,j.getLong("expires_at")));
        refused(()->DeliveryProtocol.bootstrap(bytes(j.toString().replace("https://","http://")),now));
        refused(()->DeliveryProtocol.bootstrap(bytes(new JSONObject(j.toString()).put("extra",true).toString()),now));
        refused(()->DeliveryProtocol.bootstrap(bytes(new JSONObject(j.toString()).put("group_key_id","0".repeat(64)).toString()),now));
        refused(()->DeliveryProtocol.bootstrap(bytes(new JSONObject(j.toString()).put("origin",b.origin()+"/").toString()),now));
    }
    @Test public void realV1SignatureBindingAndRollback()throws Exception {
        JSONObject j=new JSONObject(new String(fixture("bootstrap"),StandardCharsets.UTF_8));long now=j.getLong("issued_at")+1;
        var b=DeliveryProtocol.bootstrap(fixture("bootstrap"),now);byte[] envelope=fixture("trust");
        JSONObject e=new JSONObject(new String(envelope,StandardCharsets.UTF_8));JSONObject p=new JSONObject(new String(Base64.getDecoder().decode(e.getString("payload_base64")),StandardCharsets.UTF_8));
        String peer=p.getJSONArray("servers").getJSONObject(0).getString("tls_spki_sha256");now=Math.max(now,p.getLong("issued_at"));final long time=now;
        var t=DeliveryProtocol.trust(envelope,b,peer,time,0,"");
        assertEquals(t.digest(),DeliveryProtocol.trust(envelope,b,peer,time,t.generation(),t.digest()).digest());
        refused(()->DeliveryProtocol.trust(envelope,b,peer,time,t.generation()+1,t.digest()));
        refused(()->DeliveryProtocol.trust(envelope,b,peer,time,t.generation(),"0".repeat(64)));
        refused(()->DeliveryProtocol.trust(envelope,b,"0".repeat(64),time,0,""));
        refused(()->DeliveryProtocol.trust(envelope,b,peer,p.getLong("expires_at"),0,""));
        refused(()->DeliveryProtocol.trust(bytes(new JSONObject(e.toString()).put("algorithm","RSA-SHA256").toString()),b,peer,time,0,""));
        refused(()->DeliveryProtocol.trust(bytes(new JSONObject(e.toString()).put("payload_base64",Base64.getEncoder().encodeToString(bytes(p.toString()+" "))).toString()),b,peer,time,0,""));
        var other=new DeliveryProtocol.Bootstrap(b.id(),"wrong-group",b.server(),b.origin(),b.ca(),b.keyId(),b.key(),b.issued(),b.expires());
        refused(()->DeliveryProtocol.trust(envelope,other,peer,time,0,""));
        var wrongServer=new DeliveryProtocol.Bootstrap(b.id(),b.group(),"wrong-server",b.origin(),b.ca(),b.keyId(),b.key(),b.issued(),b.expires());
        refused(()->DeliveryProtocol.trust(envelope,wrongServer,peer,time,0,""));
    }
    @Test public void canonicalSortedUtf8AndBase64()throws Exception {
        assertEquals("{\"a\":\"Пример\",\"z\":1}",DeliveryProtocol.canonical(DeliveryJson.parse(bytes("{\"z\":1,\"a\":\"Пример\"}"),200)));
        refused(()->DeliveryProtocol.b64("YQ",3));refused(()->DeliveryProtocol.b64("YQ==\n",3));
    }
    private byte[] assignment(JSONObject publication,long generation,String device)throws Exception {
        String digest=org.kiosk.harness.core.LocalView.digest(bytes(DeliveryProtocol.canonical(DeliveryJson.parse(bytes(publication.toString()),2*1024*1024))));
        JSONObject b=new JSONObject(new String(fixture("bootstrap"),StandardCharsets.UTF_8));
        return bytes(new JSONObject().put("version",1).put("group_id",b.getString("group_id")).put("device_id",device).put("profile",DeliveryProtocol.PROFILE)
            .put("generation",generation).put("metadata_sha256",digest).put("publication",publication).toString());
    }
    @Test public void assignmentBindsExactSupportedInventoryAndProfile()throws Exception {
        JSONObject j=new JSONObject(new String(fixture("bootstrap"),StandardCharsets.UTF_8));var b=DeliveryProtocol.bootstrap(fixture("bootstrap"),j.getLong("issued_at")+1);
        JSONObject publication=new JSONObject(new String(fixture("publication"),StandardCharsets.UTF_8));byte[] input=assignment(publication,2,"device-1");
        var a=DeliveryProtocol.assignment(input,b,"device-1",0,"");assertEquals(2,a.generation());assertEquals(15,a.request().pkg().files().size());
        refused(()->DeliveryProtocol.assignment(input,b,"device-2",0,""));
        refused(()->DeliveryProtocol.assignment(input,b,"device-1",3,""));
        refused(()->DeliveryProtocol.assignment(input,b,"device-1",2,"0".repeat(64)));
        for(String field:List.of("build_id","js_sha256","css_sha256")){
            JSONObject p=new JSONObject(publication.toString());p.getJSONObject("renderer").put(field,"0".repeat(64));
            refused(()->DeliveryProtocol.assignment(assignment(p,3,"device-1"),b,"device-1",2,a.metadata()));
        }
        JSONObject badProfile=new JSONObject(publication.toString()).put("resource_profile","unsupported");
        refused(()->DeliveryProtocol.assignment(assignment(badProfile,3,"device-1"),b,"device-1",2,a.metadata()));
        JSONObject budget=new JSONObject(publication.toString());budget.getJSONObject("limits").put("max_pixels",2000001);
        refused(()->DeliveryProtocol.assignment(assignment(budget,3,"device-1"),b,"device-1",2,a.metadata()));
        JSONObject negative=new JSONObject(publication.toString());negative.getJSONObject("windows_images").getJSONObject("resources/static/img/site_icon.png").put("result","REJECTED");
        refused(()->DeliveryProtocol.assignment(assignment(negative,3,"device-1"),b,"device-1",2,a.metadata()));
        JSONObject duplicate=new JSONObject(publication.toString());JSONArray files=duplicate.getJSONObject("package").getJSONArray("files");files.put(new JSONObject(files.getJSONObject(0).toString()).put("path","DATA/events.json"));
        refused(()->DeliveryProtocol.assignment(assignment(duplicate,3,"device-1"),b,"device-1",2,a.metadata()));
        JSONObject traversal=new JSONObject(publication.toString());traversal.getJSONObject("package").getJSONArray("files").getJSONObject(0).put("path","../private");
        refused(()->DeliveryProtocol.assignment(assignment(traversal,3,"device-1"),b,"device-1",2,a.metadata()));
        JSONObject partial=new JSONObject(publication.toString());JSONArray k=partial.getJSONObject("kiosk").getJSONArray("files");k.remove(k.length()-1);
        refused(()->DeliveryProtocol.assignment(assignment(partial,3,"device-1"),b,"device-1",2,a.metadata()));
        JSONObject raw=new JSONObject(publication.toString()).put("raw_manifest_sha256","0".repeat(64));
        refused(()->DeliveryProtocol.assignment(assignment(raw,3,"device-1"),b,"device-1",2,a.metadata()));
    }
    @Test public void clockUncertaintyExpiryAndRollback()throws Exception {
        DeliveryClock.check(100,99,90,10000,0,1,200,200,2,2,true);
        refused(()->DeliveryClock.check(98,99,90,10000,0,1,200,200,2,2,true));
        refused(()->DeliveryClock.check(95,90,90,10000,0,1,200,200,2,2,true));
        refused(()->DeliveryClock.check(100,99,90,10000,0,1,100,200,2,2,true));
        refused(()->DeliveryClock.check(100,99,90,10000,0,1,200,100,2,2,true));
        refused(()->DeliveryClock.check(100,99,90,10000,0,1,200,200,3,2,true));
        refused(()->DeliveryClock.check(100,99,90,10000,0,1,200,200,-1,-1,true));
        refused(()->DeliveryClock.check(100,99,90,10000,0,1,200,200,2,2,false));
    }
}
