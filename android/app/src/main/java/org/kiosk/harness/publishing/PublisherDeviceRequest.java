package org.kiosk.harness.publishing;

import java.security.SecureRandom;
import java.util.*;
import static org.kiosk.harness.delivery.DeliveryProtocol.*;

/**
 * Same-user new-device request: proves possession of the new key, binds the exact
 * group/origin/user and a short deadline. It grants nothing until an already
 * authorized device or the administrator explicitly authorizes it.
 */
public final class PublisherDeviceRequest {
    private PublisherDeviceRequest() {}

    public static Map<String,Object> create(PublisherKey key,String group,String origin,
            String user,long now)throws Exception{
        id(group);id(user);
        java.net.URI uri=new java.net.URI(origin);
        need("https".equals(uri.getScheme())&&uri.getHost()!=null&&uri.getPort()>0
            &&uri.getRawUserInfo()==null&&uri.getRawQuery()==null&&uri.getRawFragment()==null
            &&"".equals(uri.getRawPath())&&origin.equals("https://"+uri.getHost()+":"+uri.getPort()));
        byte[] nonce=new byte[32];
        new SecureRandom().nextBytes(nonce);
        StringBuilder hex=new StringBuilder();
        for(byte value:nonce)hex.append(String.format(Locale.ROOT,"%02x",value&255));
        Map<String,Object> request=new LinkedHashMap<>();
        request.put("device_key",Base64.getEncoder().encodeToString(key.publicKey().getEncoded()));
        request.put("device_id",PublisherAuthority.keyId(key.publicKey()));
        request.put("group_id",group);request.put("origin",origin);request.put("user_id",user);
        request.put("action","add-device");request.put("nonce",hex.toString());
        request.put("issued",now);request.put("expires",now+90);
        Map<String,Object> result=new LinkedHashMap<>();
        result.put("request",request);
        result.put("proof",PublisherEnvelope.sign(key,"device-request",request));
        return result;
    }
}
