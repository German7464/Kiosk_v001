package org.kiosk.harness.publishing;

import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;
import static org.kiosk.harness.delivery.DeliveryProtocol.need;

/** Canonical roaming-publish-v1 envelope. Only explicit native review may call this. */
public final class PublisherEnvelope {
    private PublisherEnvelope() {}

    public static Map<String,Object> sign(PublisherKey key,String kind,Map<String,Object> value)throws Exception{
        need(kind.length()>=1&&kind.length()<=32);
        Map<String,Object> outer=new LinkedHashMap<>();
        outer.put("kind",kind);outer.put("value",value);outer.put("version",1L);
        byte[] payload=PublisherAuthority.canonical(outer);
        need(payload.length<=32768);
        byte[] signature=key.sign(PublisherAuthority.DOMAIN,payload);
        need(signature.length==384);
        Map<String,Object> envelope=new LinkedHashMap<>();
        envelope.put("payload",Base64.getEncoder().encodeToString(payload));
        envelope.put("signature",Base64.getEncoder().encodeToString(signature));
        return envelope;
    }

    /** Page-release-v2 domain; the caller must already hold an independent page review. */
    public static Map<String,Object> signPage(PublisherKey key,Map<String,Object> value)throws Exception{
        Map<String,Object> outer=new LinkedHashMap<>();
        outer.put("kind",org.kiosk.harness.delivery.PageReleaseProtocol.KIND);
        outer.put("value",value);
        outer.put("version",org.kiosk.harness.delivery.PageReleaseProtocol.ENVELOPE_VERSION);
        byte[] payload=PublisherAuthority.canonical(outer);
        need(payload.length<=org.kiosk.harness.delivery.PageReleaseProtocol.MAX_ENVELOPE);
        byte[] signature=key.sign(org.kiosk.harness.delivery.PageReleaseProtocol.DOMAIN,payload);
        need(signature.length==384);
        Map<String,Object> envelope=new LinkedHashMap<>();
        envelope.put("payload",Base64.getEncoder().encodeToString(payload));
        envelope.put("signature",Base64.getEncoder().encodeToString(signature));
        return envelope;
    }
}
