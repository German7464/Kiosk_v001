package org.kiosk.harness;

import android.test.InstrumentationTestCase;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import org.kiosk.harness.publishing.PublisherAuthority;

/** Real Android crypto/validator boundary. No app preferences or clocks changed. */
@SuppressWarnings("deprecation")
public final class AuthorityWindowPhoneTest extends InstrumentationTestCase {
    public void testLegacyImageVariantsAndNullableDate() throws Exception {
        var payload=new TreeMap<String,Object>();
        payload.putAll(Map.of("title","Legacy","short_description","","full_description","","place","",
            "sort_order",0L,"status","active","tags",List.of("Tag with spaces")));
        payload.put("event_date",null);
        payload.put("sort_order",new org.kiosk.harness.delivery.DeliveryJson.NumberToken("0"));
        payload.put("images",java.util.Arrays.asList("/static/uploads/card.jpg","/static/uploads/card.jpg",null));
        var result=org.kiosk.harness.publishing.PublisherReview.derive(Map.of("1",Map.of("payload",payload)),Map.of(),7L);
        var event=(Map<?,?>)((List<?>)result.get("events")).get(0);
        assertNull(event.get("event_date")); assertNull(event.get("image_thumb"));
        assertEquals("/static/uploads/card.jpg",event.get("image_tv"));
    }
    private Map<String,Object> signed(java.security.PrivateKey key, String kind, Map<String,Object> value) throws Exception {
        byte[] raw = PublisherAuthority.canonical(Map.of("version",1L,"kind",kind,"value",value));
        var signature = java.security.Signature.getInstance("SHA256withRSA");
        signature.initSign(key); signature.update(PublisherAuthority.DOMAIN); signature.update(raw);
        return Map.of("payload",Base64.getEncoder().encodeToString(raw),"signature",Base64.getEncoder().encodeToString(signature.sign()));
    }
    public void testNinetyDayWindowOverlapExpiryAndUnboundedRefusal() throws Exception {
        var generator=java.security.KeyPairGenerator.getInstance("RSA"); generator.initialize(3072);
        var root=generator.generateKeyPair(); var device=generator.generateKeyPair();
        long issued=2_000_000_000L, expires=issued+104L*86400L;
        String group="stage5-phone-window", origin="https://192.168.1.124:28443";
        Map<String,Object> policy=new TreeMap<>(Map.of("group_id",group,"origin",origin,"version",1L,
            "issued",issued,"expires",expires,"revoked_devices",List.of(),"revoked_users",List.of()));
        var envelope=signed(root.getPrivate(),"policy",policy);
        var current=PublisherAuthority.policy(envelope,root.getPublic(),group,origin,issued+90L*86400L,0);
        var grant=Map.<String,Object>of("group_id",group,"origin",origin,"user_id","admin","role","administrator",
            "device_key",Base64.getEncoder().encodeToString(device.getPublic().getEncoded()),"issued",issued,"expires",expires,"can_delegate",true);
        PublisherAuthority.permission(List.of(signed(root.getPrivate(),"device",grant)),root.getPublic(),current,issued+90L*86400L);
        try { PublisherAuthority.policy(envelope,root.getPublic(),group,origin,expires,0); fail("expiry accepted"); }
        catch(java.io.IOException expected) { }
        policy.put("expires",expires+1);
        try { PublisherAuthority.policy(signed(root.getPrivate(),"policy",policy),root.getPublic(),group,origin,issued,0); fail("extension accepted"); }
        catch(java.io.IOException expected) { }
    }
}
