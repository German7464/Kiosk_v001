package org.kiosk.harness.delivery;

import org.junit.Test;
import static org.junit.Assert.*;
import java.net.URL;
import java.util.*;
import org.kiosk.harness.binding.*;
import org.kiosk.harness.core.LocalView;

public class ResumeTransportTest {
    @Test public void diagnosticsNeverLeakProviderMessagesAndHandleMissingMessage(){
        assertEquals("interrupted_or_invalid",DeliveryClient.transferFailureReason(new java.io.IOException()));
        assertEquals("interrupted_or_invalid",DeliveryClient.transferFailureReason(new java.io.IOException("untrusted provider path or credential")));
        assertEquals("transfer_range",DeliveryClient.transferFailureReason(new java.io.IOException("transfer_range")));
    }
    @Test public void transferSummaryFitsExistingDisplayRecordBudget()throws Exception{
        var input=new org.json.JSONObject().put("candidate","a".repeat(64)).put("reused_bytes",1000).put("requests",new org.json.JSONArray().put("x".repeat(12000))).put("restart_reason","transfer_range").put("unexpected","y".repeat(2000));
        var compact=DeliveryClient.summarizeTransfer(input.toString());assertFalse(compact.has("requests"));assertFalse(compact.has("unexpected"));assertEquals(1000,compact.getLong("reused_bytes"));assertTrue(compact.toString().length()<1024);
        assertEquals("invalid_diagnostic",DeliveryClient.summarizeTransfer(new org.json.JSONObject().put("restart_reason","x".repeat(5000)).toString()).getString("restart_reason"));
    }
    static class RangeConnection extends NativeTransportTest.Connection {
        Map<String,String> headers=new HashMap<>();
        RangeConnection(URL u,java.security.PublicKey key){super(u,key);headers.put("Accept-Ranges","bytes");}
        public String getContentType(){return "application/octet-stream";}public String getHeaderField(String name){return headers.get(name);}public String getContentEncoding(){return headers.get("Content-Encoding");}
    }
    @Test public void actualRangeRequestHeadersAndResponseValidation()throws Exception{
        var b=new NativeTransportTest().anchor();var c=new RangeConnection(new URL(b.origin()),b.key());String peer=LocalView.digest(b.key().getEncoded()),sha="a".repeat(64);
        c.code=206;c.length=3;c.headers.put("ETag","\""+sha+"\"");c.headers.put("Content-Range","bytes 2-4/5");
        var wire=new NativeTransport(b,u->c);try(var reply=wire.rangeArtifact("/file","b".repeat(64),5,sha,2,peer)){
            assertEquals("bytes=2-",c.getRequestProperty("Range"));assertEquals("\""+sha+"\"",c.getRequestProperty("If-Range"));assertEquals("identity",c.getRequestProperty("Accept-Encoding"));
            assertEquals(2,ResumableCapture.validate(reply,new DevelopmentWitness.Pin(5,sha),2));assertEquals(3,reply.body().readAllBytes().length);
        }assertTrue(c.disconnected);assertFalse(c.getInstanceFollowRedirects());
    }
    @Test public void fullFallbackAndRetryStatusDoNotInventPartialBytes()throws Exception{
        var b=new NativeTransportTest().anchor();var c=new RangeConnection(new URL(b.origin()),b.key());String peer=LocalView.digest(b.key().getEncoded()),sha="a".repeat(64);
        c.length=3;c.headers.put("ETag","\""+sha+"\"");var wire=new NativeTransport(b,u->c);
        try(var reply=wire.rangeArtifact("/file","b".repeat(64),3,sha,1,peer)){assertEquals(0,ResumableCapture.validate(reply,new DevelopmentWitness.Pin(3,sha),1));}
        c.code=429;c.length=0;c.headers.put("Retry-After","5");try(var reply=wire.rangeArtifact("/file","b".repeat(64),3,sha,1,peer)){
            try{ResumableCapture.validate(reply,new DevelopmentWitness.Pin(3,sha),1);fail();}catch(ResumableCapture.TransferFailure failure){assertEquals(429,failure.status);assertEquals(5000,failure.retryMillis);}
        }
    }
    @Test public void retryAfterPersistsAcrossFreshClientAndPreventsRequests()throws Exception{
        var owner=new DeliveryClientRecoveryTest();try(var lab=owner.new Lab()){
            lab.enrolled();var client=new DeliveryClient(null,lab.store,b->lab,lab.clock,(r,p,k,t)->{throw new ResumableCapture.TransferFailure("busy",429,5000);});
            try{client.download();fail();}catch(ResumableCapture.TransferFailure busy){assertEquals(429,busy.status);}
            var fresh=lab.client();assertEquals(5000,fresh.transferRetryMillis());try{fresh.download();fail();}catch(ResumableCapture.TransferFailure busy){assertEquals("transfer_retry_pending",busy.getMessage());}
            lab.clock.elapsed+=5001;try(var capture=lab.client().download().capture()){assertNotNull(capture);}
        }
    }
    @Test public void assignment409And416RefetchOnlyOnce()throws Exception{
        for(int status:List.of(409,416)){
            var owner=new DeliveryClientRecoveryTest();try(var lab=owner.new Lab()){
                lab.enrolled();int[] calls={0};var client=new DeliveryClient(null,lab.store,b->lab,lab.clock,(r,p,k,t)->{
                    if(calls[0]++==0){if(status==409)lab.generation++;throw new ResumableCapture.TransferFailure("refetch",status,0);}
                    return org.kiosk.harness.binding.DeliveryCaptureAdapter.capture(lab.owned,r,p,k,t);
                });
                try(var captured=client.download().capture()){assertEquals(2,calls[0]);assertNotNull(captured);}assertEquals(lab.generation,lab.store.saved.getLong("assignment_generation"));
                calls[0]=0;var persistent=new DeliveryClient(null,lab.store,b->lab,lab.clock,(r,p,k,t)->{calls[0]++;throw new ResumableCapture.TransferFailure("refetch",status,0);});
                try{persistent.download();fail();}catch(ResumableCapture.TransferFailure bounded){assertEquals(status,bounded.status);assertEquals(2,calls[0]);}
            }
        }
    }
    @Test public void fullResyncFlagDoesNotSkipCurrentAndKeepsRegistration()throws Exception{
        var owner=new DeliveryClientRecoveryTest();try(var lab=owner.new Lab()){
            var c=lab.enrolled();lab.accept(c);String credential=lab.store.saved.getString("credential"),accepted=lab.store.saved.getJSONObject("accepted").toString();
            assertNull(lab.client().download(lab.pid));int before=lab.captures;
            lab.store.saved.put("full_transfer_token","explicit-owner-request");try(var capture=lab.client().download(lab.pid).capture()){assertNotNull(capture);}
            assertTrue(lab.captures>before);assertEquals(credential,lab.store.saved.getString("credential"));assertEquals(accepted,lab.store.saved.getJSONObject("accepted").toString());
        }
    }
}
