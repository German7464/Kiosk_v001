package org.kiosk.harness.delivery;

import android.content.Context;
import android.os.SystemClock;
import android.provider.Settings;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.*;
import org.kiosk.harness.binding.CapturedCandidate;
import org.kiosk.harness.core.LocalView;

/** Test APK only. Real platform trust/secret/state; bounded corruption of a selected response. */
public final class PhoneDeliveryAdapters {
    public String fault="";
    public final Map<String,Integer> statuses=new TreeMap<>();
    public final List<String> receiptHashes=new ArrayList<>();
    private final Context context;
    public PhoneDeliveryAdapters(Context context){this.context=context;}
    private DeliveryIO.Clock clock(){return new DeliveryIO.Clock(){
        public long now(){return System.currentTimeMillis()/1000;}public long elapsed(){return SystemClock.elapsedRealtime();}
        public int boot(){return Settings.Global.getInt(context.getContentResolver(),Settings.Global.BOOT_COUNT,-1);}
        public boolean automatic(){return Settings.Global.getInt(context.getContentResolver(),Settings.Global.AUTO_TIME,0)==1;}
    };}
    public DeliveryClient client()throws Exception{return client(new PrivateDeliveryState(context));}
    public DeliveryClient expiredCredentialClient()throws Exception{
        JSONObject expired=new PrivateDeliveryState(context).read();if(!expired.has("credential"))throw new IOException("enrollment_not_ready");
        expired.put("credential_expires",System.currentTimeMillis()/1000-1);
        return client(new DeliveryIO.Store(){public JSONObject read()throws Exception{return new JSONObject(expired.toString());}
            public void write(JSONObject ignored)throws Exception{throw new IOException("expired_test_state_must_not_persist");}});
    }
    private DeliveryClient client(DeliveryIO.Store state)throws Exception{
        return new DeliveryClient(context,state,b->{NativeTransport real=new NativeTransport(b);return new DeliveryIO.Wire(){
            public NativeTransport.Response call(String path,String secret,byte[] body,int cap,NativeTransport.PeerPin pin)throws Exception{
                var r=real.call(path,secret,body,cap,pin);String endpoint=path.contains("?")?path.substring(0,path.indexOf('?')):path;
                statuses.merge(endpoint+":"+r.status(),1,Integer::sum);
                if(path.equals("/api/v2/client/receipts")){
                    receiptHashes.add(LocalView.digest(body));if(fault.equals("lost-receipt")){fault="";throw new IOException("test_lost_reply_after_real_accept");}
                }
                if((path.equals("/api/v2/device/token")||path.equals("/api/v2/client/status"))&&r.status()==200&&fault.equals("lost-token")){fault="";throw new IOException("test_lost_token_reply");}
                if(path.startsWith("/api/v2/client/assignment?")){
                    if(fault.equals("unauthorized"))return new NativeTransport.Response(401,new byte[0],r.leafSha256(),r.issuerSha256());
                    if(fault.equals("malformed"))return new NativeTransport.Response(200,"{\"version\":1,\"version\":1}".getBytes(StandardCharsets.UTF_8),r.leafSha256(),r.issuerSha256());
                    if(fault.equals("stale")||fault.equals("unsupported")){
                        JSONObject m=new JSONObject(new String(r.body(),StandardCharsets.UTF_8));
                        if(fault.equals("stale"))m.put("generation",Math.max(0,m.getLong("generation")-1));
                        else {m.put("generation",m.getLong("generation")+1);JSONObject p=m.getJSONObject("publication");p.put("resource_profile","unsupported");
                            m.put("metadata_sha256",LocalView.digest(DeliveryProtocol.canonical(DeliveryJson.parse(p.toString().getBytes(StandardCharsets.UTF_8),2*1024*1024)).getBytes(StandardCharsets.UTF_8)));}
                        return new NativeTransport.Response(200,m.toString().getBytes(StandardCharsets.UTF_8),r.leafSha256(),r.issuerSha256());
                    }
                }
                return r;
            }
            public InputStream artifact(String path,String secret,long size,NativeTransport.PeerPin pin)throws IOException{
                InputStream in=real.artifact(path,secret,size,pin);
                if(fault.equals("partial"))return new FilterInputStream(in){long left=Math.max(0,size-1);public int read()throws IOException{if(left==0)return -1;int n=in.read();if(n>=0)left--;return n;}public int read(byte[] b,int o,int n)throws IOException{if(left==0)return -1;int r=in.read(b,o,(int)Math.min(n,left));if(r>0)left-=r;return r;}};
                if(fault.equals("tampered"))return new FilterInputStream(in){boolean first=true;public int read()throws IOException{int n=in.read();if(n>=0&&first){first=false;return n^1;}return n;}public int read(byte[] b,int o,int n)throws IOException{int r=in.read(b,o,n);if(r>0&&first){first=false;b[o]^=1;}return r;}};
                return in;
            }
        };},clock(),(r,p,k,t)->CapturedCandidate.capture(context,p,k,t,r.pkg(),r.renderer(),r.kiosk(),r.tv(),r.storage(),new CapturedCandidate.Cancellation()));
    }
    public String associationDigest()throws Exception{return LocalView.digest(new PrivateDeliveryState(context).read().getJSONObject("accepted").toString().getBytes(StandardCharsets.UTF_8));}
    public int queued()throws Exception{JSONArray a=new PrivateDeliveryState(context).read().optJSONArray("outbox");return a==null?0:a.length();}
    public void enrollmentLostReplyRecovery()throws Exception{
        // A volatile checkpoint models a crash before persisting an already approved token response.
        // The real secret/request/code were durably generated by ordinary native enrollment earlier.
        JSONObject original=new PrivateDeliveryState(context).read();String expected=original.getString("credential");
        original.remove("credential");original.remove("credential_expires");
        DeliveryIO.Store checkpoint=new DeliveryIO.Store(){JSONObject copy=original;
            public JSONObject read()throws Exception{return new JSONObject(copy.toString());}
            public void write(JSONObject value)throws Exception{copy=new JSONObject(value.toString());}
        };
        fault="lost-token";try{client(checkpoint).poll();throw new AssertionError("lost reply accepted");}catch(IOException expectedLoss){}
        if(!"approved".equals(client(checkpoint).poll())||!expected.equals(checkpoint.read().getString("credential")))throw new AssertionError("same credential not recovered");
        fault="";
    }
}
