package org.kiosk.harness.binding;

import java.io.*;
import java.util.*;
import org.json.JSONObject;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.packagecore.EventsPackage;

/** Test adapter only: PC1 JSON is not parsed by the main API or fetched from its sources. */
public final class BindingVectors {
    public interface Loader { Map<String,byte[]> load() throws Exception; }
    private static final String C="b14a125bde2dafbccb1c304f0ac0ae22428e2caef7c79e02ffebebccf215e731";
    private static void check(boolean value){if(!value)throw new AssertionError("binding vector");}
    private static Map<String,DevelopmentWitness.Pin> pins(JSONObject json) throws Exception {
        Map<String,DevelopmentWitness.Pin> result=new HashMap<>();
        for(Iterator<String> keys=json.keys();keys.hasNext();){String key=keys.next();JSONObject p=json.getJSONObject(key);result.put(key,new DevelopmentWitness.Pin(p.getLong("size"),p.getString("sha256")));}
        return result;
    }
    private static Map<String,byte[]> subtree(Map<String,byte[]> all,String root) {
        Map<String,byte[]> result=new HashMap<>();all.forEach((p,b)->{if(p.startsWith(root+"/"))result.put(p.substring(root.length()+1),b.clone());});return result;
    }
    static class Memory implements LocalView.Source {
        final Map<String,byte[]> files; final Map<String,Integer> reads=new HashMap<>();
        int opened,closed; String fault="",target="manifest.json";
        Memory(Map<String,byte[]> files){this.files=files;}
        @Override public Set<String> files(){return Set.copyOf(files.keySet());}
        @Override public InputStream open(String path) throws IOException {
            byte[] data=files.get(path);if(data==null)throw new IOException("private/path/content");
            int n=reads.merge(path,1,Integer::sum);
            if(path.equals(target)){
                if(fault.equals("short"))data=Arrays.copyOf(data,data.length-1);
                if(fault.equals("overlong"))data=Arrays.copyOf(data,data.length+1);
                if(fault.equals("reread")&&n>1){data=data.clone();data[0]^=1;}
            }
            ByteArrayInputStream raw=new ByteArrayInputStream(data);opened++;
            return new InputStream(){boolean done;
                @Override public int read() throws IOException{byte[] b=new byte[1];int n=read(b,0,1);return n<0?-1:b[0]&255;}
                @Override public int read(byte[] b,int off,int len)throws IOException{
                    if(path.equals(target)&&fault.equals("zero"))return 0;
                    if(path.equals(target)&&fault.equals("error"))throw new IOException("private/path/content");
                    return raw.read(b,off,len);
                }
                @Override public void close()throws IOException{if(!done){done=true;closed++;raw.close();if(path.equals(target)&&fault.equals("close"))throw new IOException("private/path/content");}}
            };
        }
    }
    static class Data {
        final Memory p,k,t;
        DevelopmentWitness.Package pkg; DevelopmentWitness.Renderer renderer;
        DevelopmentWitness.Artifact kiosk,tv;
        Data(Loader loader)throws Exception{
            var all=loader.load();JSONObject w=new JSONObject(new String(all.get("pc1-witness.json"),java.nio.charset.StandardCharsets.UTF_8));
            p=new Memory(subtree(all,"package"));k=new Memory(subtree(all,"view-kiosk"));t=new Memory(subtree(all,"view-tv"));
            pkg=new DevelopmentWitness.Package(w.getString("package_identity"),w.getString("raw_manifest_sha256"),pins(w.getJSONObject("package_files")));
            var views=w.getJSONObject("views");var kfiles=pins(views.getJSONObject("kiosk").getJSONObject("files"));var tfiles=pins(views.getJSONObject("tv").getJSONObject("files"));
            renderer=new DevelopmentWitness.Renderer(w.getString("renderer_identity"),kfiles.get("events.js").sha256(),kfiles.get("events.css").sha256());
            kiosk=new DevelopmentWitness.Artifact("kiosk",pkg.canonicalIdentity(),renderer.identity(),kfiles);
            tv=new DevelopmentWitness.Artifact("tv",pkg.canonicalIdentity(),renderer.identity(),tfiles);
        }
        PublicationBinding.Report inspect()throws Exception{return PublicationBinding.inspect(p,k,t,pkg,renderer,kiosk,tv);}
        void closed(){check(p.opened==p.closed&&k.opened==k.closed&&t.opened==t.closed);}
    }
    private static void refuse(Data d,BindingFailure.Code code)throws Exception{
        try{d.inspect();throw new AssertionError("unexpected binding success");}
        catch(BindingFailure e){if(code!=null)check(e.code==code);check(e.getMessage().equals(e.code.name())&&e.getCause()==null&&e.getSuppressed().length==0);}
        d.closed();
    }
    public static void valid(Loader load)throws Exception{
        Data d=new Data(load);var r=d.inspect();d.closed();
        check(r.callerAttestedCanonicalPackageIdentity().equals(C));check(r.artifacts().keySet().equals(Set.of("kiosk","tv")));
        check(r.unchecked().equals(Set.of(EventsPackage.Unchecked.values()))&&r.unproven().equals(Set.of(PublicationBinding.Unproven.values())));
        check(r.rawManifestSha256().equals(LocalView.digest(d.p.files.get("manifest.json"))));
        check(r.artifacts().get("kiosk").rawDescriptorSha256().equals(LocalView.digest(d.k.files.get("view.json"))));
        try{r.artifacts().clear();throw new AssertionError();}catch(UnsupportedOperationException expected){}
    }
    public static void witnesses(Loader load)throws Exception{
        Data d=new Data(load);d.kiosk=new DevelopmentWitness.Artifact("tv",C,d.renderer.identity(),d.kiosk.files());refuse(d,BindingFailure.Code.WITNESS_MISMATCH);
        d=new Data(load);d.tv=new DevelopmentWitness.Artifact("tv","0".repeat(64),d.renderer.identity(),d.tv.files());refuse(d,BindingFailure.Code.WITNESS_MISMATCH);
        d=new Data(load);d.renderer=new DevelopmentWitness.Renderer("0".repeat(64),d.renderer.trustedJsSha256(),d.renderer.trustedCssSha256());refuse(d,BindingFailure.Code.WITNESS_MISMATCH);
        d=new Data(load);d.renderer=new DevelopmentWitness.Renderer(d.renderer.identity(),"0".repeat(64),d.renderer.trustedCssSha256());refuse(d,BindingFailure.Code.ARTIFACT_STRUCTURE);
        d=new Data(load);d.renderer=new DevelopmentWitness.Renderer(d.renderer.identity(),d.renderer.trustedJsSha256(),"0".repeat(64));refuse(d,BindingFailure.Code.ARTIFACT_STRUCTURE);
        d=new Data(load);d.pkg=new DevelopmentWitness.Package(C,"0".repeat(64),d.pkg.files());refuse(d,BindingFailure.Code.WITNESS_MISMATCH);
        // Unsupported tuple is refused before opening any package data/media.
        d=new Data(load);JSONObject manifest=new JSONObject(new String(d.p.files.get("manifest.json"),java.nio.charset.StandardCharsets.UTF_8));
        manifest.put("schema_version",2);byte[] raw=manifest.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);
        d.p.files.put("manifest.json",raw);var nativePins=new HashMap<>(d.pkg.files());
        nativePins.put("manifest.json",new DevelopmentWitness.Pin(raw.length,LocalView.digest(raw)));
        d.pkg=new DevelopmentWitness.Package(C,LocalView.digest(raw),nativePins);
        refuse(d,BindingFailure.Code.PACKAGE_STRUCTURE);check(d.p.reads.keySet().equals(Set.of("manifest.json")));
    }
    public static void inventoryAndTampering(Loader load)throws Exception{
        Data d=new Data(load);d.p.files.remove("data/events.json");refuse(d,BindingFailure.Code.INVENTORY_MISMATCH);
        d=new Data(load);d.k.files.put("extra.png",new byte[0]);refuse(d,BindingFailure.Code.INVENTORY_MISMATCH);
        d=new Data(load);d.t.files.get("index.html")[0]^=1;refuse(d,BindingFailure.Code.STREAM_INTEGRITY);
        // Attacker rewrites content AND its own descriptor digest, retaining an independent caller witness.
        d=new Data(load);byte[] changed=d.k.files.get("index.html");changed[0]^=1;
        String descriptor=new String(d.k.files.get("view.json"),java.nio.charset.StandardCharsets.UTF_8);
        descriptor=descriptor.replace(d.kiosk.files().get("index.html").sha256(),LocalView.digest(changed));
        d.k.files.put("view.json",descriptor.getBytes(java.nio.charset.StandardCharsets.UTF_8));refuse(d,BindingFailure.Code.STREAM_INTEGRITY);
        d=new Data(load);var map=new HashMap<>(d.pkg.files());map.put("../escape",new DevelopmentWitness.Pin(0,"0".repeat(64)));d.pkg=new DevelopmentWitness.Package(C,d.pkg.rawManifestSha256(),map);refuse(d,BindingFailure.Code.INVALID_WITNESS);
        d=new Data(load);map=new HashMap<>(d.pkg.files());map.put("data/events.json",new DevelopmentWitness.Pin(Long.MAX_VALUE,"0".repeat(64)));d.pkg=new DevelopmentWitness.Package(C,d.pkg.rawManifestSha256(),map);refuse(d,BindingFailure.Code.INVALID_WITNESS);check(d.p.opened==0);
        d=new Data(load);map=new HashMap<>(d.pkg.files());map.put("data/events.json",new DevelopmentWitness.Pin(64L*1024*1024+1,"0".repeat(64)));d.pkg=new DevelopmentWitness.Package(C,d.pkg.rawManifestSha256(),map);refuse(d,BindingFailure.Code.INVALID_WITNESS);check(d.p.opened==0);
        // Matching native descriptor pin does not waive LocalView mode/identity/revision checks.
        for(String field:List.of("mode","package_sha256","revision")){
            d=new Data(load);JSONObject j=new JSONObject(new String(d.k.files.get("view.json"),java.nio.charset.StandardCharsets.UTF_8));
            j.put(field,field.equals("mode")?"tv":field.equals("revision")?"999":"0".repeat(64));
            byte[] b=j.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);d.k.files.put("view.json",b);
            var pins=new HashMap<>(d.kiosk.files());pins.put("view.json",new DevelopmentWitness.Pin(b.length,LocalView.digest(b)));
            d.kiosk=new DevelopmentWitness.Artifact("kiosk",C,d.renderer.identity(),pins);
            refuse(d,field.equals("revision")?BindingFailure.Code.REVISION_MISMATCH:BindingFailure.Code.ARTIFACT_STRUCTURE);
        }
    }
    public static void streams(Loader load)throws Exception{
        for(String fault:List.of("short","overlong","zero","error","close")){
            Data d=new Data(load);d.p.fault=fault;refuse(d,fault.equals("error")||fault.equals("close")?BindingFailure.Code.SOURCE_IO:BindingFailure.Code.STREAM_INTEGRITY);
            d=new Data(load);d.t.target="index.html";d.t.fault=fault;refuse(d,fault.equals("error")||fault.equals("close")?BindingFailure.Code.SOURCE_IO:BindingFailure.Code.STREAM_INTEGRITY);
        }
    }
    public static void changedReread(Loader load)throws Exception{
        Data d=new Data(load);d.p.target="data/events.json";d.p.fault="reread";refuse(d,BindingFailure.Code.PACKAGE_STRUCTURE);
        d=new Data(load);d.k.target="index.html";d.k.fault="reread";refuse(d,BindingFailure.Code.ARTIFACT_STRUCTURE);
    }
    public static void lifetimeAndNoWrites(Loader load)throws Exception{
        Data d=new Data(load);Map<String,String> before=new HashMap<>();d.p.files.forEach((p,b)->before.put(p,LocalView.digest(b)));
        var r=d.inspect();d.closed();d.p.files.forEach((p,b)->check(before.get(p).equals(LocalView.digest(b))));
        // A report is not a retained verified source or future-read capability.
        d.k.files.get("index.html")[0]^=1;
        check(r.unproven().contains(PublicationBinding.Unproven.SOURCE_IMMUTABILITY));
        check(r.unproven().contains(PublicationBinding.Unproven.FUTURE_READS_AND_LIFETIME));
        refuse(d,BindingFailure.Code.STREAM_INTEGRITY);
    }
}
