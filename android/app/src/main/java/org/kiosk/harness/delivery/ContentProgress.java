package org.kiosk.harness.delivery;

import java.nio.charset.StandardCharsets;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.concurrent.*;
import org.json.JSONObject;

/** Advisory, memory-only newest item. Never owns admission, display or ready receipts. */
final class ContentProgress implements AutoCloseable {
    static final long MAX_BYTES=201326592, RESERVATION=1048576;
    record Binding(String device,String group,long generation,String pkg){}
    record Token(Binding binding,long attempt,long limit){}
    interface Sender {NativeTransport.Response send(byte[] body)throws Exception;}
    interface Time {long elapsed();long wall();}
    private final Sender sender;private final Time time;
    private final ScheduledExecutorService worker;
    private ScheduledFuture<?> wake;
    private Token active;private JSONObject pending;private long sequence,notBefore,lastSend=-5000;
    private int failures;private boolean stopped,unsupported,running,halted;
    private String lastState="waiting";private long completed,total;
    ContentProgress(Sender sender,Time time){this(sender,time,Executors.newSingleThreadScheduledExecutor(r->{Thread t=new Thread(r,"content-progress");t.setDaemon(true);return t;}));}
    ContentProgress(Sender sender,Time time,ScheduledExecutorService worker){this.sender=sender;this.time=time;this.worker=worker;}
    synchronized Token begin(Binding b,long first,long limit,long bytes){
        if(stopped||unsupported)return null;
        active=new Token(b,first,limit);sequence=first-1;failures=0;halted=false;completed=0;total=bytes;lastState="waiting";pending=null;
        offer(active,"waiting",0,"none");return active;
    }
    synchronized void offer(Token token,String state,long bytes,String error){
        if(token==null||token!=active||stopped||unsupported||halted||sequence>=token.limit())return;
        boolean terminal=Set.of("error","incompatible").contains(state);
        if(Set.of("error","incompatible").contains(lastState))return;
        if(!terminal&&(rank(state)<rank(lastState)||bytes<completed))return;
        if(state.equals(lastState)&&bytes==completed&&pending!=null)return;
        try{
            JSONObject body=new JSONObject().put("version",1).put("device_id",token.binding.device()).put("group_id",token.binding.group())
                .put("generation",token.binding.generation()).put("package_id",token.binding.pkg()).put("attempt",token.attempt())
                .put("sequence",++sequence).put("state",state).put("completed_bytes",bytes).put("total_bytes",total).put("error",error);
            validate(body);pending=body;lastState=state;completed=bytes;schedule();
        }catch(Exception invalid){/* Invalid advisory facts must not escape into the content path. */}
    }
    static int rank(String s){return List.of("waiting","downloading","downloaded","verified").indexOf(s);}
    private void schedule(){
        if(stopped||unsupported||running||pending==null||wake!=null)return;
        long delay=Math.max(0,Math.max(notBefore,lastSend+5000)-time.elapsed());
        wake=worker.schedule(this::drain,delay,TimeUnit.MILLISECONDS);
    }
    void drain(){
        JSONObject item;Token token;
        synchronized(this){wake=null;if(stopped||unsupported||pending==null)return;running=true;item=pending;token=active;lastSend=time.elapsed();}
        int status=0;String retry=null;
        try{var reply=sender.send(item.toString().getBytes(StandardCharsets.UTF_8));status=reply.status();retry=reply.retryAfter();
            if(status==200){var ack=new JSONObject(new String(reply.body(),StandardCharsets.UTF_8));
                if(ack.length()!=3||!(ack.get("version") instanceof Integer)||ack.getInt("version")!=1||ack.getLong("sequence")!=item.getLong("sequence")||!Set.of("recorded","duplicate","superseded").contains(ack.getString("state")))status=400;
            }
        }catch(Exception unavailable){status=0;}
        synchronized(this){running=false;
            if(status==404||status==405){unsupported=true;pending=null;}
            else if(token==active){
                if(status==0||status==429||status>=500){
                    if(++failures>=6){pending=null;halted=true;}
                    else notBefore=time.elapsed()+Math.max(Math.min(300000,10000L<<(failures-1)),retryMillis(retry,time.wall()));
                }else{failures=0;notBefore=0;if(status>=400){pending=null;halted=true;}else if(pending==item)pending=null;}
            }
            schedule();
        }
    }
    static long retryMillis(String value,long wall){
        if(value==null)return 0;
        try{return Math.min(3600,Math.max(0,Long.parseLong(value)))*1000L;}catch(Exception ignored){}
        try{return Math.min(3600000,Math.max(0,ZonedDateTime.parse(value,DateTimeFormatter.RFC_1123_DATE_TIME).toInstant().toEpochMilli()-wall));}catch(Exception ignored){return 0;}
    }
    static void validate(JSONObject b)throws Exception{
        Set<String> keys=new HashSet<>();for(Iterator<String> it=b.keys();it.hasNext();)keys.add(it.next());
        if(!keys.equals(Set.of("version","device_id","group_id","generation","package_id","attempt","sequence","state","completed_bytes","total_bytes","error")))throw new Exception("invalid_fields");
        if(integer(b,"version",1,1)!=1)throw new Exception("unsupported_version");
        if(!(b.get("device_id") instanceof String)||b.getString("device_id").isEmpty()||!(b.get("group_id") instanceof String)||b.getString("group_id").isEmpty())throw new Exception("invalid_progress");
        if(!(b.get("package_id") instanceof String)||!b.getString("package_id").matches("[a-f0-9]{64}"))throw new Exception("invalid_digest");
        integer(b,"generation",1,Long.MAX_VALUE);long attempt=integer(b,"attempt",1,Long.MAX_VALUE);integer(b,"sequence",attempt,Long.MAX_VALUE);
        long total=integer(b,"total_bytes",0,MAX_BYTES),done=integer(b,"completed_bytes",0,total);
        String s=b.getString("state"),e=b.getString("error");boolean terminal=Set.of("error","incompatible").contains(s);
        if(rank(s)<0&&!terminal||!Set.of("none","connection","storage","integrity","requires_update","assignment_changed","candidate_refused").contains(e)||terminal==e.equals("none")||s.equals("incompatible")&&!e.equals("requires_update")||Set.of("downloaded","verified").contains(s)&&done!=total)throw new Exception("invalid_progress");
        if(b.toString().getBytes(StandardCharsets.UTF_8).length>2048)throw new Exception("progress_limit");
    }
    private static long integer(JSONObject b,String name,long min,long max)throws Exception{
        Object v=b.get(name);if(!(v instanceof Integer||v instanceof Long))throw new Exception(name.equals("version")?"unsupported_version":"invalid_progress");
        long n=((Number)v).longValue();if(n<min||n>max)throw new Exception(name.equals("version")?"unsupported_version":"invalid_progress");return n;
    }
    synchronized boolean unsupported(){return unsupported;}
    synchronized void abandon(){active=null;pending=null;}
    @Override public synchronized void close(){stopped=true;pending=null;active=null;if(wake!=null)wake.cancel(false);worker.shutdownNow();}
}
