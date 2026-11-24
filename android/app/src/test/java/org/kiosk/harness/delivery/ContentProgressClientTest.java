package org.kiosk.harness.delivery;

import org.junit.Test;
import static org.junit.Assert.*;
import org.kiosk.harness.binding.DeliveryCaptureAdapter;

/** Synthetic native-client fixtures: exercises actual persisted state and capture, no phone/server claim. */
public class ContentProgressClientTest {
    @Test public void incompatibleLegacyHintIsProbedOnlyOnce()throws Exception{
        try(var lab=new DeliveryClientRecoveryTest().new Lab()){
            int[] hints={0};
            DeliveryClient c=new DeliveryClient(null,lab.store,b->new DeliveryIO.Wire(){
                public NativeTransport.Response call(String path,String secret,byte[] body,int cap,NativeTransport.PeerPin pin)throws Exception{
                    if(path.startsWith("/api/v2/client/assignment?"))return new NativeTransport.Response(409,"{\"version\":1,\"error\":\"requires_update\"}".getBytes(java.nio.charset.StandardCharsets.UTF_8),lab.peer,lab.issuer);
                    if(path.equals("/api/v2/client/progress")){hints[0]++;return new NativeTransport.Response(404,new byte[0],lab.peer,lab.issuer);}
                    return lab.call(path,secret,body,cap,pin);
                }
                public java.io.InputStream artifact(String path,String secret,long size,NativeTransport.PeerPin pin)throws java.io.IOException{throw new java.io.IOException("must_not_transfer");}
            },lab.clock,(r,p,k,t)->{throw new AssertionError("must_not_capture");});
            try{c.confirm(lab.bootstrap);c.authorize();c.poll();for(int i=0;i<2;i++){try{c.download();fail();}catch(java.io.IOException expected){}}
                assertEquals(1,hints[0]);assertFalse(lab.store.saved.has("progress_high_water"));assertTrue(lab.receipts.isEmpty());
            }finally{c.closeProgress();}
        }
    }
    @Test public void persistedReservationRestartAndReadyIndependence()throws Exception{
        try(var lab=new DeliveryClientRecoveryTest().new Lab()){
            DeliveryClient first=lab.enrolled();
            try{
                try(var capture=first.download().capture()){}
                long high=lab.store.saved.getLong("progress_high_water");assertEquals(ContentProgress.RESERVATION,high);
                assertFalse(lab.store.saved.has("outbox"));assertFalse(lab.store.saved.has("accepted"));assertTrue(lab.receipts.isEmpty());
                String identity=lab.store.saved.getString("device"),secret=lab.store.saved.getString("secret");first.closeProgress();
                DeliveryClient restarted=lab.client();
                try{try(var capture=restarted.download().capture()){}
                    assertEquals(high+ContentProgress.RESERVATION,lab.store.saved.getLong("progress_high_water"));
                    assertEquals(identity,lab.store.saved.getString("device"));assertEquals(secret,lab.store.saved.getString("secret"));
                    assertFalse(lab.store.saved.has("outbox"));assertTrue(lab.receipts.isEmpty());
                }finally{restarted.closeProgress();}
            }finally{first.closeProgress();}
        }
    }
    @Test public void reportingFailureDoesNotFailCapture()throws Exception{
        try(var lab=new DeliveryClientRecoveryTest().new Lab()){
            DeliveryClient c=new DeliveryClient(null,lab.store,b->new DeliveryIO.Wire(){
                public NativeTransport.Response call(String path,String secret,byte[] body,int cap,NativeTransport.PeerPin pin)throws Exception{
                    if(path.equals("/api/v2/client/progress"))throw new java.io.IOException("offline");return lab.call(path,secret,body,cap,pin);
                }
                public java.io.InputStream artifact(String path,String secret,long size,NativeTransport.PeerPin pin)throws java.io.IOException{return lab.artifact(path,secret,size,pin);}
            },lab.clock,(r,p,k,t)->DeliveryCaptureAdapter.capture(lab.owned,r,p,k,t));
            try{c.confirm(lab.bootstrap);c.authorize();c.poll();try(var capture=c.download().capture()){assertNotNull(capture);}
                assertEquals(ContentProgress.RESERVATION,lab.store.saved.getLong("progress_high_water"));assertTrue(lab.receipts.isEmpty());
            }finally{c.closeProgress();}
        }
    }
}
