package org.kiosk.harness.binding;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.JSONObject;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.storage.DevelopmentPlaybackAuthority;
import android.content.Context;

/** PC1 evidence adapter ONLY in test source sets. Never a production protocol/admission API. */
public final class LocalPreparation {
    public enum Confirmation {
        C("5fc915b121f36120e787412c0c28bbefd585b80efcc1c5865083f136593302b3"),
        B("91f5f9674617d88dc0b32201f5ac70b9b4fc72f1da681cc172019bb6b1d42493");
        public final String sha256;
        Confirmation(String sha256){this.sha256=sha256;}
    }
    public static final class Evidence {
        private final DevelopmentWitness.Package pkg; private final DevelopmentWitness.Renderer renderer;
        private final DevelopmentWitness.Artifact kiosk,tv; private final String packageRoot,kioskRoot,tvRoot,preparationSha256,windowsEnvironment;
        private Evidence(DevelopmentWitness.Package pkg,DevelopmentWitness.Renderer renderer,DevelopmentWitness.Artifact kiosk,DevelopmentWitness.Artifact tv,String packageRoot,String kioskRoot,String tvRoot,String preparationSha256,String windowsEnvironment){
            this.pkg=pkg;this.renderer=renderer;this.kiosk=kiosk;this.tv=tv;this.packageRoot=packageRoot;this.kioskRoot=kioskRoot;this.tvRoot=tvRoot;this.preparationSha256=preparationSha256;this.windowsEnvironment=windowsEnvironment;
        }
        public DevelopmentWitness.Package pkg(){return pkg;} public DevelopmentWitness.Renderer renderer(){return renderer;}
        public DevelopmentWitness.Artifact kiosk(){return kiosk;} public DevelopmentWitness.Artifact tv(){return tv;}
        public String packageRoot(){return packageRoot;} public String kioskRoot(){return kioskRoot;} public String tvRoot(){return tvRoot;}
        public String preparationSha256(){return preparationSha256;} public String windowsEnvironment(){return windowsEnvironment;}
    }
    private static Set<String> keys(JSONObject j){Set<String> out=new HashSet<>();j.keys().forEachRemaining(out::add);return out;}
    private static IOException refused(){return new IOException("TEST_PREPARATION_REFUSED");}
    private static String hash(JSONObject j,String key)throws Exception{
        Object v=j.get(key);if(!(v instanceof String s)||!s.matches("[0-9a-f]{64}"))throw refused();return s;
    }
    private static void path(String s)throws Exception{
        if(s.length()>240||!s.matches("[A-Za-z0-9_./-]+"))throw refused();
        for(String c:s.split("/",-1))if(c.isEmpty()||c.equals(".")||c.equals(".."))throw refused();
    }
    private static Map<String,DevelopmentWitness.Pin> pins(JSONObject j)throws Exception{
        if(j.length()==0||j.length()>10000)throw refused();Map<String,DevelopmentWitness.Pin> out=new HashMap<>();
        for(Iterator<String> it=j.keys();it.hasNext();){String name=it.next();path(name);JSONObject pin=j.getJSONObject(name);
            Object n=pin.get("size");if(!(n instanceof Integer||n instanceof Long)||((Number)n).longValue()<0||((Number)n).longValue()>256L*1024*1024)throw refused();
            if(!keys(pin).equals(Set.of("size","sha256")))throw refused();out.put(name,new DevelopmentWitness.Pin(((Number)n).longValue(),hash(pin,"sha256")));
        }return Map.copyOf(out);
    }
    /** Reads at most 256KiB, closes input, pins and parses the SAME byte array. No self-digest authority. */
    public static Evidence confirm(InputStream input,Confirmation authority,String independentlySuppliedDigest)throws Exception{
        byte[] bytes=LocalView.readBounded(input,256*1024);
        if(authority==null||!authority.sha256.equals(independentlySuppliedDigest)||!authority.sha256.equals(LocalView.digest(bytes)))throw refused();
        JSONObject j=new JSONObject(new String(bytes,StandardCharsets.UTF_8));
        if(!keys(j).equals(Set.of("environment","limitations","package","package_identity","preparer_sources","raw_manifest_sha256","renderer_identity","scope","views")))throw refused();
        if(!j.getString("scope").equals("local_test_preparation_only_not_authorization"))throw refused();
        j.getJSONObject("environment").getString("pillow");j.getJSONObject("environment").getString("python");j.getJSONArray("limitations");
        hash(j.getJSONObject("preparer_sources"),"exporter");hash(j.getJSONObject("preparer_sources"),"test_preparer");
        String id=hash(j,"package_identity"),raw=hash(j,"raw_manifest_sha256"),rendererId=hash(j,"renderer_identity");
        JSONObject pkg=j.getJSONObject("package"),views=j.getJSONObject("views"),k=views.getJSONObject("kiosk"),t=views.getJSONObject("tv");
        if(!keys(views).equals(Set.of("kiosk","tv")))throw refused();
        String pr=pkg.getString("path"),kr=k.getString("path"),tr=t.getString("path");
        if(!pr.equals("store/revisions/"+id)||!kr.matches("cache/[0-9a-f]{64}")||!tr.matches("cache/[0-9a-f]{64}")||kr.equals(tr))throw refused();
        var pp=pins(pkg.getJSONObject("files"));var kp=pins(k.getJSONObject("files"));var tp=pins(t.getJSONObject("files"));
        if(!pp.containsKey("manifest.json")||!pp.get("manifest.json").sha256().equals(raw))throw refused();
        for(String f:List.of("view.json","index.html","events.js","events.css"))if(!kp.containsKey(f)||!tp.containsKey(f))throw refused();
        if(!kp.get("events.js").equals(tp.get("events.js"))||!kp.get("events.css").equals(tp.get("events.css")))throw refused();
        return new Evidence(new DevelopmentWitness.Package(id,raw,pp),new DevelopmentWitness.Renderer(rendererId,kp.get("events.js").sha256(),kp.get("events.css").sha256()),
            new DevelopmentWitness.Artifact("kiosk",id,rendererId,kp),new DevelopmentWitness.Artifact("tv",id,rendererId,tp),pr,kr,tr,authority.sha256,j.getJSONObject("environment").toString());
    }
    static BindingVectors.Memory source(Map<String,byte[]> all,String root,Map<String,DevelopmentWitness.Pin> inventory)throws Exception{
        Map<String,byte[]> found=new HashMap<>();for(var e:all.entrySet())if(e.getKey().startsWith(root+"/"))found.put(e.getKey().substring(root.length()+1),e.getValue().clone());
        if(!found.keySet().equals(inventory.keySet()))throw refused();return new BindingVectors.Memory(found);
    }
    public static PublicationBinding.Report inspect(Map<String,byte[]> all,Evidence e)throws Exception{
        var p=source(all,e.packageRoot,e.pkg.files());var k=source(all,e.kioskRoot,e.kiosk.files());var t=source(all,e.tvRoot,e.tv.files());
        try{return PublicationBinding.inspect(p,k,t,e.pkg,e.renderer,e.kiosk,e.tv);}finally{if(p.opened!=p.closed||k.opened!=k.closed||t.opened!=t.closed)throw new AssertionError("stream ownership");}
    }
    public static PlaybackInputs.Owned capture(Context target,Map<String,byte[]> all,Evidence e)throws Exception{
        var p=source(all,e.packageRoot,e.pkg.files());var k=source(all,e.kioskRoot,e.kiosk.files());var t=source(all,e.tvRoot,e.tv.files());AtomicInteger reads=new AtomicInteger();
        var permit=DevelopmentPlaybackAuthority.authorizeUnverifiedDevelopmentPlayback(e.pkg,e.renderer,e.kiosk,e.tv);
        CapturedCandidate candidate=CapturedCandidate.capture(target,count(p,reads),count(k,reads),count(t,reads),e.pkg,e.renderer,e.kiosk,e.tv,new CapturedCandidate.Budget(8L*1024*1024,100,1024),new CapturedCandidate.Cancellation());
        if(p.opened!=p.closed||k.opened!=k.closed||t.opened!=t.closed){candidate.close();throw new AssertionError("stream ownership");}
        p.files.clear();k.files.clear();t.files.clear();all.clear(); // Providers now cannot supply any bytes.
        return new PlaybackInputs.Owned(candidate,permit,e.pkg.canonicalIdentity(),reads);
    }
    private static LocalView.Source count(LocalView.Source s,AtomicInteger calls){return new LocalView.Source(){
        public Set<String> files()throws IOException{calls.incrementAndGet();return s.files();}
        public InputStream open(String name)throws IOException{calls.incrementAndGet();return s.open(name);}
    };}
}
