package org.kiosk.harness.delivery;

import org.junit.Test;
import static org.junit.Assert.*;
import org.json.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;

public class ContentProgressTest {
    static class Scheduler extends ScheduledThreadPoolExecutor {
        long delay;int queued;
        Scheduler(){super(1);}
        @Override public ScheduledFuture<?> schedule(Runnable r,long d,TimeUnit u){delay=u.toMillis(d);queued++;return new ScheduledFuture<Object>(){
            public long getDelay(TimeUnit unit){return unit.convert(delay,TimeUnit.MILLISECONDS);}public int compareTo(Delayed other){return 0;}
            public boolean cancel(boolean interrupt){return true;}public boolean isCancelled(){return false;}public boolean isDone(){return false;}
            public Object get(){return null;}public Object get(long timeout,TimeUnit unit){return null;}
        };}
    }
    static class Lab implements AutoCloseable {
        long now;int status=200;String retry;Runnable during=()->{};List<JSONObject> sent=new ArrayList<>();Scheduler scheduler=new Scheduler();
        ContentProgress p=new ContentProgress(bytes->{JSONObject b=new JSONObject(new String(bytes,StandardCharsets.UTF_8));sent.add(b);
            during.run();return new NativeTransport.Response(status,new JSONObject().put("version",1).put("sequence",b.getLong("sequence")).put("state","recorded").toString().getBytes(StandardCharsets.UTF_8),"","",retry);},new ContentProgress.Time(){public long elapsed(){return now;}public long wall(){return 0;}},scheduler);
        ContentProgress.Token begin(long first){return p.begin(new ContentProgress.Binding("device-public","group-public",1,"a".repeat(64)),first,first+ContentProgress.RESERVATION-1,1024);}
        void send(){now+=Math.max(5000,scheduler.delay);p.drain();}
        public void close(){p.close();scheduler.shutdownNow();}
    }
    @Test public void publicBytesAndValidation()throws Exception{
        byte[] bytes=getClass().getResourceAsStream("/content-progress-v1.json").readAllBytes();
        assertEquals("b2833097bc60c5722f17350a839e403898a30f21e2e963a4eb910a0b1020a638",org.kiosk.harness.core.LocalView.digest(bytes));
        JSONObject vectors=new JSONObject(new String(bytes,StandardCharsets.UTF_8));
        for(int i=0;i<vectors.getJSONArray("accepts").length();i++)ContentProgress.validate(vectors.getJSONArray("accepts").getJSONObject(i));
        for(int i=0;i<vectors.getJSONArray("rejects").length();i++){JSONObject vector=vectors.getJSONArray("rejects").getJSONObject(i);try{ContentProgress.validate(vector.getJSONObject("body"));fail(vector.getString("name"));}catch(Exception expected){assertEquals(vector.getString("name"),vector.getString("error"),expected.getMessage());}}
        for(int i=0;i<vectors.getJSONArray("ordering").length();i++)ContentProgress.validate(vectors.getJSONArray("ordering").getJSONObject(i).getJSONObject("body"));
    }
    @Test public void newestOnlyOrderingAndStaleCallbacks()throws Exception{try(Lab l=new Lab()){
        var a=l.begin(1);l.p.offer(a,"downloading",512,"none");l.p.offer(a,"waiting",0,"none");l.send();assertEquals(512,l.sent.get(0).getLong("completed_bytes"));
        l.p.offer(a,"downloaded",1024,"none");l.p.offer(a,"verified",1024,"none");l.send();assertEquals("verified",l.sent.get(1).getString("state"));
        var b=l.begin(ContentProgress.RESERVATION+1);l.p.offer(a,"error",0,"connection");l.send();assertEquals(b.attempt(),l.sent.get(2).getLong("attempt"));assertEquals("waiting",l.sent.get(2).getString("state"));
    }}
    @Test public void coalescingIsBounded()throws Exception{try(Lab l=new Lab()){
        var a=l.begin(1);for(int i=0;i<1024;i++)l.p.offer(a,"downloading",i,"none");assertEquals(1,l.scheduler.queued);l.send();assertEquals(1,l.sent.size());assertEquals(1023,l.sent.get(0).getLong("completed_bytes"));
        l.p.offer(a,"downloaded",1024,"none");assertTrue(l.scheduler.delay>=5000);
    }}
    @Test public void retrySameBodyAndRetryAfterAndCeiling()throws Exception{try(Lab l=new Lab()){
        l.status=429;l.retry="3600";l.begin(1);l.send();assertEquals(3600000,l.scheduler.delay);l.send();assertEquals(l.sent.get(0).toString(),l.sent.get(1).toString());
        for(int i=0;i<4;i++)l.send();int count=l.sent.size();l.p.offer(l.begin(ContentProgress.RESERVATION+1),"downloading",1,"none");assertEquals(6,count);
        assertEquals(3600000,ContentProgress.retryMillis("9223372036854775807",0));assertEquals(10000,ContentProgress.retryMillis("Thu, 01 Jan 1970 00:00:10 GMT",0));
    }}
    @Test public void permanentAndLegacyStopTraffic()throws Exception{for(int status:new int[]{400,401,403,404,405,409,413,415})try(Lab l=new Lab()){
        l.status=status;var a=l.begin(1);l.send();l.p.offer(a,"downloading",1,"none");l.send();assertEquals(1,l.sent.size());
        if(status==404||status==405){assertTrue(l.p.unsupported());assertNull(l.begin(ContentProgress.RESERVATION+1));}
    }}
    @Test public void terminalCannotResumeAndRestartSkipsReservation()throws Exception{try(Lab l=new Lab()){
        var a=l.begin(1);l.p.offer(a,"error",0,"integrity");l.p.offer(a,"verified",1024,"none");l.send();assertEquals("error",l.sent.get(0).getString("state"));
        long high=a.limit();try(Lab restarted=new Lab()){restarted.begin(high+1);restarted.send();assertTrue(restarted.sent.get(0).getLong("sequence")>high);}
    }}
    @Test public void delayedOldResponseCannotBackoffOrOverwriteReplacement()throws Exception{try(Lab l=new Lab()){
        var old=l.begin(1);l.status=500;
        l.during=()->{l.p.begin(new ContentProgress.Binding("device-public","group-public",2,"b".repeat(64)),ContentProgress.RESERVATION+1,2*ContentProgress.RESERVATION,1024);l.during=()->{};};
        l.send();assertEquals(5000,l.scheduler.delay);l.p.offer(old,"verified",1024,"none");l.status=200;l.send();
        assertEquals(2,l.sent.get(1).getLong("generation"));assertEquals("b".repeat(64),l.sent.get(1).getString("package_id"));assertEquals("waiting",l.sent.get(1).getString("state"));
    }}
    @Test public void fixedFailureCodesDoNotExposeProviderDetails(){
        assertEquals("storage",DeliveryClient.progressError(new java.nio.file.FileSystemException("private path")));
        assertEquals("integrity",DeliveryClient.progressError(new java.io.IOException("transfer_short")));
        assertEquals("assignment_changed",DeliveryClient.progressError(new org.kiosk.harness.binding.ResumableCapture.TransferFailure("private",409,0)));
        assertEquals("connection",DeliveryClient.progressError(new java.io.IOException("private credential")));
        assertEquals("candidate_refused",DeliveryClient.progressError(new IllegalArgumentException("private detail")));
    }
}
