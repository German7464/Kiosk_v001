package org.kiosk.harness.pairing;

import java.net.URI;
import java.net.URISyntaxException;

/**
 * Exact coordinator QR contract for this Android enrollment request.
 *
 * <p>The payload is only the already trusted origin plus the human user code. It carries no
 * device_code, bearer credential, private key, bootstrap or CA material, so a photographed QR
 * grants nothing by itself. Lookup/scan/login never approve; the administrator still decides
 * through the guarded server routes.
 */
public final class PairingPayload {
    public static final String PATH="/admin/devices/pair";
    /** Same printable user-code alphabet the ordinary admin pairing page accepts (no 0,1,I,O). */
    public static final String USER_CODE="[A-HJ-NP-Z2-9]{8}";
    /** Bounds the encoded QR version; a real origin is far shorter. */
    private static final int MAX_ORIGIN=200;
    private PairingPayload(){}
    /** Returns exactly {@code origin + /admin/devices/pair#v=1&code=CODE}. */
    public static String of(String origin,String code){
        if(origin==null||origin.length()>MAX_ORIGIN||code==null||!code.matches(USER_CODE))throw new IllegalArgumentException("pairing_payload_refused");
        try{
            URI uri=new URI(origin);
            // Already validated with the bootstrap, but never trust an unparsed string: no userinfo,
            // query, fragment, path, non-default scheme or omitted explicit port may reach the QR.
            if(!"https".equals(uri.getScheme())||uri.getHost()==null||uri.getPort()<1||uri.getPort()>65535
                ||uri.getRawUserInfo()!=null||uri.getRawQuery()!=null||uri.getRawFragment()!=null
                ||!"".equals(uri.getRawPath())||!origin.equals("https://"+uri.getHost()+":"+uri.getPort()))
                throw new IllegalArgumentException("pairing_payload_refused");
        }catch(URISyntaxException malformed){throw new IllegalArgumentException("pairing_payload_refused");}
        return origin+PATH+"#v=1&code="+code;
    }
}
