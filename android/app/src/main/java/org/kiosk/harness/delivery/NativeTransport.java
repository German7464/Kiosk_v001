package org.kiosk.harness.delivery;

import java.io.*;
import java.net.*;
import java.security.*;
import java.security.cert.*;
import javax.net.ssl.*;
import org.kiosk.harness.core.LocalView;

/** One bootstrap origin, bootstrap CA only, platform hostname validation, no redirects/cookies. */
public final class NativeTransport implements DeliveryIO.Wire {
    /** Bounded reply; both peer identities are reported so the caller pins exactly the one its trust model uses. */
    public record Response(int status,byte[] body,String leafSha256,String issuerSha256,String retryAfter){
        public Response(int status,byte[] body,String leaf,String issuer){this(status,body,leaf,issuer,null);}
    }
    /**
     * Expected peer identity for one request. Exactly one pin is set: legacy v1 pins the serving leaf
     * SPKI, v2 pins the intermediate issuer SPKI so a legitimate leaf rotation needs no re-enrollment.
     */
    public record PeerPin(String leafSha256,String issuerSha256){
        public static PeerPin leaf(String value){return value!=null&&value.matches("[a-f0-9]{64}")?new PeerPin(value,null):null;}
        public static PeerPin issuer(String value){return value!=null&&value.matches("[a-f0-9]{64}")?new PeerPin(null,value):null;}
        void require(String leaf,String issuer)throws Exception {
            DeliveryProtocol.need(leafSha256!=null||issuerSha256!=null);
            if(leafSha256!=null)DeliveryProtocol.need(leafSha256.equals(leaf));
            if(issuerSha256!=null)DeliveryProtocol.need(issuerSha256.equals(issuer));
        }
    }
    private final DeliveryProtocol.Bootstrap bootstrap;
    private final SSLSocketFactory sockets;
    interface Connections {HttpsURLConnection open(URL url)throws Exception;}
    private final Connections connections;
    public NativeTransport(DeliveryProtocol.Bootstrap b)throws Exception {
        this(b,url->(HttpsURLConnection)url.openConnection(Proxy.NO_PROXY));
    }
    NativeTransport(DeliveryProtocol.Bootstrap b,Connections connections)throws Exception {
        this.connections=connections;
        bootstrap=b;KeyStore ks=KeyStore.getInstance(KeyStore.getDefaultType());ks.load(null);
        var certs=CertificateFactory.getInstance("X.509").generateCertificates(new ByteArrayInputStream(b.ca().getBytes(java.nio.charset.StandardCharsets.US_ASCII)));
        DeliveryProtocol.need(certs.size()==1);ks.setCertificateEntry("bootstrap",certs.iterator().next());
        TrustManagerFactory tm=TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());tm.init(ks);
        SSLContext ssl=SSLContext.getInstance("TLS");ssl.init(null,tm.getTrustManagers(),null);sockets=ssl.getSocketFactory();
    }
    private HttpsURLConnection connection(String path,String secret,byte[] body)throws Exception {
        DeliveryProtocol.need(path.startsWith("/")&&!path.startsWith("//")&&!path.contains("#")&&!path.contains("\\")&&!path.contains("\r")&&!path.contains("\n"));
        HttpsURLConnection c=connections.open(new URL(bootstrap.origin()+path));
        try {
        c.setSSLSocketFactory(sockets);c.setInstanceFollowRedirects(false);c.setConnectTimeout(10000);c.setReadTimeout(10000);c.setUseCaches(false);
        c.setRequestProperty("Accept-Encoding","identity");
        if(secret!=null){DeliveryProtocol.need(secret.matches("[a-f0-9]{64}"));c.setRequestProperty("Authorization","Bearer "+secret);}
        if(body!=null){DeliveryProtocol.need(body.length<=2*1024*1024);c.setRequestMethod("POST");c.setDoOutput(true);c.setRequestProperty("Content-Type","application/json");c.setFixedLengthStreamingMode(body.length);try(OutputStream out=c.getOutputStream()){out.write(body);}}
        return c;
        }catch(Exception failure){c.disconnect();throw failure;}
    }
    private static String[] peers(HttpsURLConnection c)throws Exception{
        java.security.cert.Certificate[] chain=c.getServerCertificates();
        DeliveryProtocol.need(chain!=null&&chain.length>=1&&chain.length<=3);
        // The pinned issuer must be the certificate that actually signed the serving leaf, not just
        // "whatever came second" in the chain.
        String leaf=LocalView.digest(chain[0].getPublicKey().getEncoded()),issuer="";
        for(int i=1;i<chain.length;i++)try{
            chain[0].verify(chain[i].getPublicKey());
            issuer=LocalView.digest(chain[i].getPublicKey().getEncoded());
            break;
        }catch(Exception notTheSigner){}
        return new String[]{leaf,issuer};
    }
    public Response call(String path,String secret,byte[] body,int cap,PeerPin pin)throws Exception {
        HttpsURLConnection c=connection(path,secret,body);
        try {
            int status=c.getResponseCode();DeliveryProtocol.need(status<300||status>=400);String[] peers=peers(c);
            if(pin!=null)pin.require(peers[0],peers[1]);
            InputStream stream=status<400?c.getInputStream():c.getErrorStream();byte[] bytes=stream==null?new byte[0]:LocalView.readBounded(stream,cap);
            return new Response(status,bytes,peers[0],peers[1],c.getHeaderField("Retry-After"));
        }finally{c.disconnect();}
    }
    public InputStream artifact(String path,String secret,long size,PeerPin pin)throws IOException {
        HttpsURLConnection c=null;
        try {
            c=connection(path,secret,null);int status=c.getResponseCode();String[] peers=peers(c);
            DeliveryProtocol.need(status==200&&c.getContentLengthLong()==size);
            if(pin!=null)pin.require(peers[0],peers[1]);
            final HttpsURLConnection retained=c;
            return new FilterInputStream(c.getInputStream()){
                long count;
                private int observed(int n)throws IOException {if(n<0){if(count!=size)throw new IOException("artifact_short");}else {count+=n;if(count>size)throw new IOException("artifact_long");}return n;}
                @Override public int read()throws IOException {int n=in.read();observed(n<0?-1:1);return n;}
                @Override public int read(byte[] b,int off,int len)throws IOException{return observed(in.read(b,off,len));}
                @Override public void close()throws IOException {try{super.close();}finally{retained.disconnect();}}
            };
        }catch(Exception e){if(c!=null)c.disconnect();throw new IOException("artifact_refused");}
    }
    @Override public org.kiosk.harness.binding.ResumableCapture.Reply rangeArtifact(String path,String secret,long size,String sha256,long offset,PeerPin pin)throws Exception {
        DeliveryProtocol.need(offset>=0&&offset<size&&sha256.matches("[a-f0-9]{64}")||offset==0&&size==0&&sha256.matches("[a-f0-9]{64}"));
        HttpsURLConnection c=connection(path,secret,null);
        try {
            if(offset>0){c.setRequestProperty("Range","bytes="+offset+"-");c.setRequestProperty("If-Range","\""+sha256+"\"");}
            int status=c.getResponseCode();String[] peers=peers(c);DeliveryProtocol.need(status<300||status>=400);
            if(pin!=null)pin.require(peers[0],peers[1]);
            if(status==200||status==206)DeliveryProtocol.need("application/octet-stream".equals(c.getContentType())&&"bytes".equals(c.getHeaderField("Accept-Ranges")));
            InputStream raw=status<400?c.getInputStream():c.getErrorStream();final HttpsURLConnection retained=c;
            InputStream body=new FilterInputStream(raw==null?new ByteArrayInputStream(new byte[0]):raw){public void close()throws IOException{try{super.close();}finally{retained.disconnect();}}};
            return new org.kiosk.harness.binding.ResumableCapture.Reply(status,c.getContentLengthLong(),c.getHeaderField("ETag"),c.getHeaderField("Content-Range"),c.getContentEncoding(),c.getHeaderField("Retry-After"),body);
        }catch(Exception failure){c.disconnect();throw failure;}
    }
}
