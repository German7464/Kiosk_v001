package org.kiosk.harness.delivery;

import java.io.*;
import java.net.*;
import java.security.*;
import java.security.cert.*;
import javax.net.ssl.*;
import org.kiosk.harness.core.LocalView;

/** One bootstrap origin, bootstrap CA only, platform hostname validation, no redirects/cookies. */
public final class NativeTransport implements DeliveryIO.Wire {
    public record Response(int status,byte[] body,String peer){}
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
    private static String peer(HttpsURLConnection c)throws Exception{return LocalView.digest(c.getServerCertificates()[0].getPublicKey().getEncoded());}
    public Response call(String path,String secret,byte[] body,int cap,String pin)throws Exception {
        HttpsURLConnection c=connection(path,secret,body);
        try {
            int status=c.getResponseCode();DeliveryProtocol.need(status<300||status>=400);String peer=peer(c);if(pin!=null)DeliveryProtocol.need(pin.equals(peer));
            InputStream stream=status<400?c.getInputStream():c.getErrorStream();byte[] bytes=stream==null?new byte[0]:LocalView.readBounded(stream,cap);
            return new Response(status,bytes,peer);
        }finally{c.disconnect();}
    }
    public InputStream artifact(String path,String secret,long size,String pin)throws IOException {
        HttpsURLConnection c=null;
        try {
            c=connection(path,secret,null);DeliveryProtocol.need(c.getResponseCode()==200&&pin.equals(peer(c))&&c.getContentLengthLong()==size);
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
    @Override public org.kiosk.harness.binding.ResumableCapture.Reply rangeArtifact(String path,String secret,long size,String sha256,long offset,String pin)throws Exception {
        DeliveryProtocol.need(offset>=0&&offset<size&&sha256.matches("[a-f0-9]{64}")||offset==0&&size==0&&sha256.matches("[a-f0-9]{64}"));
        HttpsURLConnection c=connection(path,secret,null);
        try {
            if(offset>0){c.setRequestProperty("Range","bytes="+offset+"-");c.setRequestProperty("If-Range","\""+sha256+"\"");}
            int status=c.getResponseCode();DeliveryProtocol.need(pin.equals(peer(c))&&(status<300||status>=400));
            if(status==200||status==206)DeliveryProtocol.need("application/octet-stream".equals(c.getContentType())&&"bytes".equals(c.getHeaderField("Accept-Ranges")));
            InputStream raw=status<400?c.getInputStream():c.getErrorStream();final HttpsURLConnection retained=c;
            InputStream body=new FilterInputStream(raw==null?new ByteArrayInputStream(new byte[0]):raw){public void close()throws IOException{try{super.close();}finally{retained.disconnect();}}};
            return new org.kiosk.harness.binding.ResumableCapture.Reply(status,c.getContentLengthLong(),c.getHeaderField("ETag"),c.getHeaderField("Content-Range"),c.getContentEncoding(),c.getHeaderField("Retry-After"),body);
        }catch(Exception failure){c.disconnect();throw failure;}
    }
}
