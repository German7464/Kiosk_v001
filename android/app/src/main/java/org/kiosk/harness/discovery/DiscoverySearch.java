package org.kiosk.harness.discovery;

import java.net.*;
import java.util.*;

/** One worker-owned socket, monotonic deadline, finite input and output budgets. */
public final class DiscoverySearch implements AutoCloseable {
    public interface SocketFactory { DatagramSocket open()throws Exception; }
    public record Received(String source,int port,String base64) {}
    public record Result(List<DiscoveryProtocol.Hint> hints,int sent,int inputs,long millis,boolean cancelled,String queryBase64,List<Received> received) {}
    private volatile boolean cancelled;
    private DatagramSocket socket;
    private boolean started;
    public synchronized void close(){cancelled=true;if(socket!=null)socket.close();}
    private synchronized void own(DatagramSocket s)throws Exception{if(cancelled){s.close();throw new SocketException("cancelled");}socket=s;}
    public Result run(SocketFactory factory)throws Exception {
        synchronized(this){if(started)throw new IllegalStateException("search_already_started");started=true;}
        // Leave 100ms of the contract's 3s budget for socket close/UI scheduling on real devices.
        long start=System.nanoTime(),end=start+2_900_000_000L;int sent=0;var results=new DiscoveryProtocol.Results();String nonce=DiscoveryProtocol.nonce();byte[] query=DiscoveryProtocol.query(nonce);
        List<Received> received=new ArrayList<>();String encoded=Base64.getEncoder().encodeToString(query);
        if(cancelled)return new Result(List.of(),0,0,0,true,encoded,List.of());
        try(DatagramSocket s=factory.open()){
            own(s);s.setBroadcast(true);byte[] buffer=new byte[DiscoveryProtocol.SIZE+1];
            while(!cancelled&&!results.full()){
                long now=System.nanoTime();if(now>=end)break;
                if(sent<3&&now>=start+sent*1_000_000_000L){s.send(new DatagramPacket(query,query.length,InetAddress.getByName("255.255.255.255"),DiscoveryProtocol.PORT));sent++;}
                long next=sent<3?Math.min(end,start+sent*1_000_000_000L):end;
                s.setSoTimeout((int)Math.max(1,Math.min(100,(next-System.nanoTime())/1_000_000L)));
                DatagramPacket p=new DatagramPacket(buffer,buffer.length);
                try{s.receive(p);if(cancelled||System.nanoTime()>=end)break;byte[] bytes=Arrays.copyOfRange(p.getData(),p.getOffset(),p.getOffset()+p.getLength());
                    if(results.accept(bytes,nonce)!=null)received.add(new Received(p.getAddress().getHostAddress(),p.getPort(),Base64.getEncoder().encodeToString(bytes)));
                }catch(SocketTimeoutException timeout){}
            }
        }catch(SocketException closed){if(!cancelled)throw closed;}
        finally{synchronized(this){socket=null;}}
        return new Result(results.hints(),sent,results.inputs(),(System.nanoTime()-start)/1_000_000L,cancelled,encoded,List.copyOf(received));
    }
}
