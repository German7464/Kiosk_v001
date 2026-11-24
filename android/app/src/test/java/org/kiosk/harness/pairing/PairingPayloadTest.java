package org.kiosk.harness.pairing;

import io.nayuki.qrcodegen.QrCode;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.junit.Test;
import static org.junit.Assert.*;

/** Contract exactness and a pinned regression vector for the locally generated QR. */
public class PairingPayloadTest {
    static final String ORIGIN="https://192.168.1.165:18543";
    static final String CODE="ABCD2345";
    static final String PAYLOAD=ORIGIN+"/admin/devices/pair#v=1&code="+CODE;
    static void refused(String origin,String code){
        try{PairingPayload.of(origin,code);fail("must refuse "+origin+" / "+code);}catch(IllegalArgumentException expected){}
    }
    @Test public void exactCoordinatorContract(){
        assertEquals("https://192.168.1.165:18543/admin/devices/pair#v=1&code=ABCD2345",PairingPayload.of(ORIGIN,CODE));
        // Only the two contract fields: no device_code, credential, key, bootstrap or CA payload.
        String fragment=PairingPayload.of(ORIGIN,CODE).substring((ORIGIN+"/admin/devices/pair#").length());
        assertEquals("v=1&code="+CODE,fragment);
    }
    @Test public void refusesAmbiguousOrUntrustedOrigins(){
        for(String origin:new String[]{
            "http://192.168.1.165:18543","https://192.168.1.165","https://192.168.1.165:18543/",
            "https://192.168.1.165:18543/admin/devices/pair","https://192.168.1.165:18543?next=pair",
            "https://192.168.1.165:18543#v=1","https://admin:secret@192.168.1.165:18543",
            "HTTPS://192.168.1.165:18543","https://192.168.1.165:0","https://192.168.1.165:65536",
            "","https://","https://192.168.1.165:18543 "+"x"})refused(origin,CODE);
        refused(ORIGIN.repeat(6),CODE);
    }
    @Test public void refusesNonContractCodes(){
        for(String code:new String[]{"ABCD234","ABCD23456","abcd2345","ABCD 345","ABCD2340","ABCD2341","ABCDI345","ABCDO345","","ABCD23４5"})refused(ORIGIN,code);
        refused(ORIGIN,null);refused(null,CODE);
    }
    /**
     * Regression pin for the exact reviewed generator: version/size/ECC/mask plus every module.
     * The physical camera decode during the journey is the independent check; this vector only
     * proves the payload-to-module mapping did not drift.
     */
    @Test public void qrVectorForExactPayload()throws Exception{
        QrCode qr=QrCode.encodeText(PAYLOAD,QrCode.Ecc.MEDIUM);
        assertEquals(5,qr.version);assertEquals(37,qr.size);assertEquals(2,qr.mask);
        assertEquals(QrCode.Ecc.MEDIUM,qr.errorCorrectionLevel);
        StringBuilder modules=new StringBuilder();
        for(int y=0;y<qr.size;y++)for(int x=0;x<qr.size;x++)modules.append(qr.getModule(x,y)?'1':'0');
        assertEquals("463cb00f16fdb890b10c18775bdec8170e0dd2dc13bfae0368aa8e573258ccac",
            java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(modules.toString().getBytes(StandardCharsets.US_ASCII))));
    }
}
