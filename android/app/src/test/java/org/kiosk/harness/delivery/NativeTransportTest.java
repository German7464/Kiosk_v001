package org.kiosk.harness.delivery;

import org.junit.Test;
import static org.junit.Assert.*;
import java.io.*;
import java.net.*;
import java.security.*;
import java.security.cert.Certificate;
import javax.net.ssl.*;
import org.json.JSONObject;
import org.kiosk.harness.core.LocalView;

/** Bounded connection adapters exercise production transport guards; not a real TLS handshake. */
public class NativeTransportTest {
    interface Checked {void run()throws Exception;}
    void refused(Checked test)throws Exception{try{test.run();fail("must refuse");}catch(AssertionError failure){throw failure;}catch(Exception expected){}}
    DeliveryProtocol.Bootstrap anchor()throws Exception{byte[] input;try(var in=getClass().getResourceAsStream("/delivery-v1/bootstrap.json")){input=in.readAllBytes();}return DeliveryProtocol.bootstrap(input,new JSONObject(new String(input,java.nio.charset.StandardCharsets.UTF_8)).getLong("issued_at")+1);}
    static class Connection extends HttpsURLConnection {
        int code=200;long length=3;byte[] data={1,2,3};boolean disconnected;final PublicKey key;ByteArrayOutputStream sent=new ByteArrayOutputStream();
        Connection(URL u,PublicKey key){super(u);this.key=key;}
        public void connect(){}public void disconnect(){disconnected=true;}public boolean usingProxy(){return false;}
        public String getCipherSuite(){return "test-adapter";}public Certificate[] getLocalCertificates(){return null;}
        public Certificate[] getServerCertificates(){return new Certificate[]{new Certificate("test-adapter"){
            public byte[] getEncoded(){return key.getEncoded();}public void verify(PublicKey k){}public void verify(PublicKey k,String p){}public PublicKey getPublicKey(){return key;}public String toString(){return "test-certificate";}
        }};}
        public int getResponseCode(){return code;}public long getContentLengthLong(){return length;}
        public InputStream getInputStream(){return new ByteArrayInputStream(data);}public InputStream getErrorStream(){return getInputStream();}
        public OutputStream getOutputStream(){return sent;}
    }
    @Test public void redirectRefusedAndDisconnectedWithNoFollow()throws Exception{
        var b=anchor();Connection c=new Connection(new URL(b.origin()),b.key());c.code=302;
        NativeTransport t=new NativeTransport(b,u->c);refused(()->t.call("/api/version",null,null,100,null));assertTrue(c.disconnected);assertFalse(c.getInstanceFollowRedirects());
    }
    @Test public void exactLengthShortLongPeerAndStatusGuards()throws Exception{
        var b=anchor();String peer=LocalView.digest(b.key().getEncoded());Connection c=new Connection(new URL(b.origin()),b.key());NativeTransport t=new NativeTransport(b,u->c);
        try(var in=t.artifact("/file","a".repeat(64),3,peer)){assertArrayEquals(new byte[]{1,2,3},in.readAllBytes());}assertTrue(c.disconnected);
        c.data=new byte[]{1,2};refused(()->{try(var in=t.artifact("/file","a".repeat(64),3,peer)){in.readAllBytes();}});
        c.data=new byte[]{1,2,3,4};refused(()->{try(var in=t.artifact("/file","a".repeat(64),3,peer)){in.readAllBytes();}});
        c.data=new byte[]{1,2,3};c.length=2;refused(()->t.artifact("/file","a".repeat(64),3,peer));
        c.length=3;refused(()->t.artifact("/file","a".repeat(64),3,"0".repeat(64)));
        c.code=409;refused(()->t.artifact("/file","a".repeat(64),3,peer));
    }
    @Test public void metadataCapOriginEscapeAndExactRequestBody()throws Exception{
        var b=anchor();Connection c=new Connection(new URL(b.origin()),b.key());NativeTransport t=new NativeTransport(b,u->c);
        refused(()->t.call("//other.invalid/",null,null,100,null));refused(()->t.call("/api/version",null,null,2,null));
        byte[] exact="{\"receipt_id\":\"same\"}".getBytes(java.nio.charset.StandardCharsets.UTF_8);
        t.call("/api/v2/client/receipts","a".repeat(64),exact,100,null);assertArrayEquals(exact,c.sent.toByteArray());
        assertEquals("POST",c.getRequestMethod());assertEquals("Bearer "+"a".repeat(64),c.getRequestProperty("Authorization"));
    }
}
