package org.kiosk.harness.delivery;

import android.content.Context;
import android.os.SystemClock;
import android.provider.Settings;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.*;
import org.kiosk.harness.binding.*;
import org.kiosk.harness.core.LocalView;

/** Test APK only, real TLS/authority/state; cancels one owned response after a measured prefix. */
public final class ResumePhoneDriver {
    private final Context context;public boolean cancel,interrupted;public long deliveredPrefix,interruptionMillis;public final Map<String,Integer> statuses=new TreeMap<>();
    public ResumePhoneDriver(Context context){this.context=context;}
    public DeliveryClient client()throws Exception {
        return new DeliveryClient(context,new PrivateDeliveryState(context),b->{NativeTransport real=new NativeTransport(b);return new DeliveryIO.Wire(){
            public NativeTransport.Response call(String path,String secret,byte[] body,int cap,NativeTransport.PeerPin pin)throws Exception{var r=real.call(path,secret,body,cap,pin);statuses.merge(path.split("\\?")[0]+":"+r.status(),1,Integer::sum);return r;}
            public InputStream artifact(String path,String secret,long size,NativeTransport.PeerPin pin)throws IOException{return real.artifact(path,secret,size,pin);}
            public ResumableCapture.Reply rangeArtifact(String path,String secret,long size,String sha,long offset,NativeTransport.PeerPin pin)throws Exception{
                long started=SystemClock.elapsedRealtime();var r=real.rangeArtifact(path,secret,size,sha,offset,pin);statuses.merge("artifact:"+r.status(),1,Integer::sum);
                if(cancel&&!interrupted&&offset==0&&size>400000&&path.contains("/static/uploads/")){
                    InputStream limited=new FilterInputStream(r.body()){
                        long left=262144;
                        public int read(byte[] b,int o,int n)throws IOException {if(left==0){interrupted=true;interruptionMillis=SystemClock.elapsedRealtime()-started;throw new IOException("controlled_owned_request_cancel");}int v=in.read(b,o,(int)Math.min(n,left));if(v>0){left-=v;deliveredPrefix+=v;}return v;}
                        public int read()throws IOException {if(left==0){interrupted=true;interruptionMillis=SystemClock.elapsedRealtime()-started;throw new IOException("controlled_owned_request_cancel");}int v=in.read();if(v>=0){left--;deliveredPrefix++;}return v;}
                    };
                    return new ResumableCapture.Reply(r.status(),r.length(),r.etag(),r.range(),r.encoding(),r.retryAfter(),limited);
                }return r;
            }
        };},new DeliveryIO.Clock(){public long now(){return System.currentTimeMillis()/1000;}public long elapsed(){return SystemClock.elapsedRealtime();}public int boot(){return Settings.Global.getInt(context.getContentResolver(),Settings.Global.BOOT_COUNT,-1);}public boolean automatic(){return Settings.Global.getInt(context.getContentResolver(),Settings.Global.AUTO_TIME,0)==1;}},
        (r,p,k,t)->{throw new IOException("ordinary_resumable_capture_required");});
    }
    public JSONObject continuity()throws Exception{JSONObject s=new PrivateDeliveryState(context).read();JSONObject result=new JSONObject();for(String k:List.of("device","credential","secret","request"))result.put(k+"_hash",LocalView.digest(s.getString(k).getBytes(StandardCharsets.UTF_8)));return result;}
    public int queued()throws Exception{JSONArray a=new PrivateDeliveryState(context).read().optJSONArray("outbox");return a==null?0:a.length();}
}
