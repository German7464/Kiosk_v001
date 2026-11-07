package org.kiosk.harness;

import android.content.ContextWrapper;
import android.test.AndroidTestCase;
import java.io.*;
import java.nio.file.*;
import java.security.cert.X509Certificate;
import java.util.*;
import javax.net.ssl.*;
import org.json.JSONObject;
import org.kiosk.harness.delivery.*;

/** New native boundaries only. Never provisions, resets, approves or emits a display receipt. */
@SuppressWarnings("deprecation")
public final class NativeDeliveryBoundaryTest extends AndroidTestCase {
    public void testAuthenticatedPrivateStateAndInterruptedWrite()throws Exception {
        File owned=new File(getContext().getNoBackupFilesDir(),"delivery-boundary-"+UUID.randomUUID());assertTrue(owned.mkdir());
        var context=new ContextWrapper(getContext()){@Override public File getNoBackupFilesDir(){return owned;}};
        try {
            PrivateDeliveryState first=new PrivateDeliveryState(context);assertEquals(0,first.read().length());
            first.write(new JSONObject().put("association","accepted-test-facts").put("outbox",new org.json.JSONArray().put(new JSONObject().put("receipt_id","stable-id").put("session","actual-test-session"))));
            byte[] original=Files.readAllBytes(new File(owned,"delivery-v1.enc").toPath());
            assertFalse(new String(original,java.nio.charset.StandardCharsets.ISO_8859_1).contains("accepted-test-facts"));
            var reopened=new PrivateDeliveryState(context);assertEquals("stable-id",reopened.read().getJSONArray("outbox").getJSONObject(0).getString("receipt_id"));
            Files.move(new File(owned,"delivery-v1.enc").toPath(),new File(owned,"delivery-v1.enc.bak").toPath());
            assertEquals("accepted-test-facts",new PrivateDeliveryState(context).read().getString("association"));
            byte[] corrupt=original.clone();corrupt[corrupt.length-1]^=1;Files.write(new File(owned,"delivery-v1.enc").toPath(),corrupt);
            try{new PrivateDeliveryState(context).read();fail("tampered association authorized");}catch(java.security.GeneralSecurityException expected){}
            Files.write(new File(owned,"delivery-v1.enc").toPath(),Arrays.copyOf(original,15));
            try{new PrivateDeliveryState(context).read();fail("partial state authorized");}catch(IOException expected){}
        }finally {try(var files=Files.walk(owned.toPath())){for(Path p:files.sorted(Comparator.reverseOrder()).toList())Files.delete(p);}}
    }
    public void testNativeStrictTLSAndWrongRoot()throws Exception {
        byte[] bytes=org.kiosk.harness.core.LocalView.readBounded(getContext().getAssets().open("delivery-bootstrap.json"),16384);
        var b=DeliveryProtocol.bootstrap(bytes,System.currentTimeMillis()/1000);var wire=new NativeTransport(b);
        var response=wire.call("/api/version",null,null,2*1024*1024,null);assertEquals(200,response.status());assertTrue(response.peer().matches("[a-f0-9]{64}"));
        TrustManagerFactory tm=TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());tm.init((java.security.KeyStore)null);
        X509Certificate unrelated=((X509TrustManager)tm.getTrustManagers()[0]).getAcceptedIssuers()[0];
        String pem="-----BEGIN CERTIFICATE-----\n"+Base64.getMimeEncoder(64,new byte[]{10}).encodeToString(unrelated.getEncoded())+"\n-----END CERTIFICATE-----\n";
        var wrong=new DeliveryProtocol.Bootstrap(b.id(),b.group(),b.server(),b.origin(),pem,b.keyId(),b.key(),b.issued(),b.expires());
        try{new NativeTransport(wrong).call("/api/version",null,null,10000,null);fail("wrong root accepted");}catch(SSLHandshakeException expected){}
        try{wire.call("/api/version",null,null,10000,"0".repeat(64));fail("wrong peer pin accepted");}catch(IOException expected){}
        try{wire.call("//other.invalid/",null,null,10000,null);fail("origin-relative escape accepted");}catch(IOException expected){}
    }
}
