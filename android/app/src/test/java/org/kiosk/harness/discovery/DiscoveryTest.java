package org.kiosk.harness.discovery;

import org.junit.Test;
import static org.junit.Assert.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import org.kiosk.harness.delivery.DeliveryJson;

public class DiscoveryTest {
    private final String nonce="0123456789abcdef0123456789abcdef";
    private byte[] reply(String origin,String label){return DeliveryJson.encode(Map.of("protocol","kiosk-discovery-v1","type","reply","nonce",nonce,"origin",origin,"label",label)).getBytes(StandardCharsets.UTF_8);}
    private byte[] valid(){return reply("https://192.168.1.165:9443","PC1");}
    private void rejects(byte[] b){try{DiscoveryProtocol.reply(b,nonce);fail("must refuse");}catch(Exception expected){}}
    @Test public void exactQueryPaddingAndRandomNonce()throws Exception{
        Set<String> seen=new HashSet<>();for(int i=0;i<32;i++){String n=DiscoveryProtocol.nonce();assertTrue(n.matches("[a-f0-9]{32}"));assertTrue(seen.add(n));byte[] q=DiscoveryProtocol.query(n);assertEquals(512,q.length);int end=new String(q,StandardCharsets.UTF_8).indexOf('}')+1;for(int at=end;at<q.length;at++)assertEquals(32,q[at]);var m=DeliveryJson.object(DeliveryJson.parse(q,512));assertEquals(Set.of("protocol","type","nonce"),m.keySet());assertEquals(n,m.get("nonce"));}
        try{DiscoveryProtocol.query("BAD");fail();}catch(Exception expected){}
    }
    @Test public void strictSchemaUtf8NonceSizeAndTruncation()throws Exception{
        assertEquals("PC1",DiscoveryProtocol.reply(valid(),nonce).label());String s=new String(valid(),StandardCharsets.UTF_8);
        for(String bad:List.of(s.replace("{","{\"type\":\"reply\","),s.replace("\"reply\"","true"),s.replace("\"PC1\"","1"),s.replace("kiosk-discovery-v1","future"),s.replace(nonce,"ffffffffffffffffffffffffffffffff"),s.replace("{","{\"extra\":0,")))rejects(bad.getBytes(StandardCharsets.UTF_8));
        rejects(new byte[]{(byte)0xc3,0x28});rejects(new byte[513]);rejects(new byte[0]);for(int i=0;i<valid().length;i++)rejects(Arrays.copyOf(valid(),i));
        byte[] padded=Arrays.copyOf(valid(),512);Arrays.fill(padded,valid().length,512,(byte)' ');assertEquals("PC1",DiscoveryProtocol.reply(padded,nonce).label());
    }
    @Test public void exactHttpsOriginAndPlainLabel()throws Exception{
        for(String origin:List.of("http://x:443","https://x","https://x:443/","https://x:443?q=x","https://x:443#x","https://u@x:443","https://x:0","https://x:65536","https://x:0443","https://x:443\\evil"))rejects(reply(origin,"PC1"));
        for(String label:List.of("x\ny","x\u0000y","x\u007fy","x\u202ey","x\u2028y","x".repeat(65)))rejects(reply("https://x:443",label));
        assertEquals("<b>&PC1",DiscoveryProtocol.reply(reply("https://x:443","<b>&PC1"),nonce).label());assertNotNull(DiscoveryProtocol.reply(reply("https://x:443","😀".repeat(64)),nonce));
    }
    @Test public void dedupResultAndInputCaps(){
        var r=new DiscoveryProtocol.Results();for(int i=0;i<100;i++)r.accept(reply("https://host"+i+":443","label"),nonce);assertEquals(32,r.hints().size());
        assertNull(r.accept(valid(),nonce));while(!r.full())r.accept(new byte[513],nonce);assertEquals(256,r.inputs());assertNull(r.accept(valid(),nonce));assertEquals(256,r.inputs());
        var stale=new DiscoveryProtocol.Results();assertNull(stale.accept(valid(),"ffffffffffffffffffffffffffffffff"));assertTrue(stale.hints().isEmpty());
        var dup=new DiscoveryProtocol.Results();assertNotNull(dup.accept(valid(),nonce));assertNull(dup.accept(valid(),nonce));assertEquals(1,dup.hints().size());
    }
    static class FakeSocket extends DatagramSocket {
        int sends,receives,timeout;boolean released,flood;String nonce;byte[] lastQuery;
        FakeSocket(boolean flood)throws Exception{super((SocketAddress)null);this.flood=flood;}
        @Override public void setBroadcast(boolean b){}
        @Override public void setSoTimeout(int n){timeout=n;}
        @Override public void send(DatagramPacket p){assertEquals(47751,p.getPort());assertEquals("255.255.255.255",p.getAddress().getHostAddress());assertEquals(512,p.getLength());if(lastQuery!=null)assertArrayEquals(lastQuery,p.getData());lastQuery=p.getData().clone();sends++;}
        @Override public synchronized void receive(DatagramPacket p)throws java.io.IOException {
            if(released)throw new SocketException("closed");receives++;
            if(flood){p.setLength(513);return;}
            try{wait(Math.max(1,timeout));}catch(InterruptedException e){Thread.currentThread().interrupt();}
            if(released)throw new SocketException("closed");throw new SocketTimeoutException();
        }
        @Override public synchronized void close(){released=true;super.close();notifyAll();}
    }
    @Test public void finiteDeadlineThreeBroadcastsAndSocketRelease()throws Exception{
        FakeSocket socket=new FakeSocket(false);var result=new DiscoverySearch().run(()->socket);assertEquals(3,result.sent());assertTrue(result.millis()>=2800&&result.millis()<3100);assertTrue(socket.released);assertTrue(result.hints().isEmpty());
    }
    @Test public void floodStopsAt256AndReleases()throws Exception{
        FakeSocket socket=new FakeSocket(true);var result=new DiscoverySearch().run(()->socket);assertEquals(256,result.inputs());assertEquals(256,socket.receives);assertEquals(1,result.sent());assertTrue(result.millis()<3000);assertTrue(socket.released);assertTrue(result.hints().isEmpty());
    }
    @Test public void cancellationClosesBlockedSocketAndNoRestart()throws Exception{
        DiscoverySearch search=new DiscoverySearch();FakeSocket socket=new FakeSocket(false);ExecutorService worker=Executors.newSingleThreadExecutor();CountDownLatch opened=new CountDownLatch(1);
        try{var f=worker.submit(()->search.run(()->{opened.countDown();return socket;}));assertTrue(opened.await(1,TimeUnit.SECONDS));search.close();var result=f.get(1,TimeUnit.SECONDS);assertTrue(result.cancelled());assertTrue(socket.released);try{search.run(()->socket);fail();}catch(IllegalStateException expected){}}
        finally{search.close();worker.shutdownNow();}
        DiscoverySearch before=new DiscoverySearch();before.close();assertTrue(before.run(()->{throw new AssertionError("cancelled search must not open socket");}).cancelled());
    }
}
