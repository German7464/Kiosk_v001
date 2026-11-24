package org.kiosk.harness;

import java.io.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.*;
import org.kiosk.harness.binding.*;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.storage.PreparedAdmission;

/** Independently pinned Windows fixtures; no DevelopmentPlaybackAuthority call in this provisioning. */
final class PreparedTestInputs {
    static final PreparedAdmission.ImageBudget IMAGES=new PreparedAdmission.ImageBudget(2_000_000,32L*1024*1024,5000,15000);
    static final CapturedCandidate.Budget STORAGE=new CapturedCandidate.Budget(8L*1024*1024,100,1024);
    record Input(CapturedCandidate capture,PreparedAdmission.Request request,AtomicInteger providerReads){}
    static final PreparedAdmission.SourceVerifier TEST_ONLY_ISSUER=new PreparedAdmission.SourceVerifier(){
        public String issuerId(){return "TEST_ONLY_ISSUER";}
        public void verify(PreparedAdmission.Request request,PreparedAdmission.Phase phase)throws IOException {
            // Computed independently from PC1 preparation inventories, never from the candidate under test.
            if(!Set.of("321e6acbb061b7bcfd7d3f99ef8585d6e0060dee61d8780ae4d0c035ad99a42b",
                "ebf13bff9935f30874a9605b284c4110472cd8fc6631564df40df168af2b1d3a").contains(request.factsFingerprint()))throw new IOException("test_issuer_not_confirmed");
        }
    };
    static Input capture(android.content.Context target,android.content.Context tests,String name,byte[] negativeMedia)throws Exception {
        Map<String,byte[]> all=PaginationAssets.load(tests,name);var e=PaginationInputs.evidence(all,name);
        Map<String,byte[]> pkg=part(all,e.packageRoot()),k=part(all,e.kioskRoot()),t=part(all,e.tvRoot());
        String id=e.pkg().canonicalIdentity();
        if(negativeMedia!=null){
            // Transient NEGATIVE fixture only: not claimed to be a Windows-prepared/authorized publication.
            String media="static/uploads/card.jpg";pkg.put(media,negativeMedia.clone());k.put(media,negativeMedia.clone());t.put(media,negativeMedia.clone());
            JSONObject manifest=new JSONObject(new String(pkg.get("manifest.json"),java.nio.charset.StandardCharsets.UTF_8));update(manifest.getJSONArray("files"),media,negativeMedia);
            pkg.put("manifest.json",manifest.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));id=LocalView.digest(pkg.get("manifest.json"));
            for(Map<String,byte[]> view:List.of(k,t)){JSONObject descriptor=new JSONObject(new String(view.get("view.json"),java.nio.charset.StandardCharsets.UTF_8));descriptor.put("package_sha256",id);update(descriptor.getJSONArray("files"),media,negativeMedia);view.put("view.json",descriptor.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));}
        }
        var p=new DevelopmentWitness.Package(id,LocalView.digest(pkg.get("manifest.json")),pins(pkg));
        var kw=new DevelopmentWitness.Artifact("kiosk",id,e.renderer().identity(),pins(k));var tw=new DevelopmentWitness.Artifact("tv",id,e.renderer().identity(),pins(t));
        Set<String> media=new TreeSet<>();media.add("resources/static/img/site_icon.png");JSONObject data=new JSONObject(new String(pkg.get("data/events.json"),java.nio.charset.StandardCharsets.UTF_8));
        for(int i=0;i<data.getJSONArray("events").length();i++)for(String field:List.of("image_kiosk","image_tv","image_thumb")){Object v=data.getJSONArray("events").getJSONObject(i).opt(field);if(v instanceof String&&!((String)v).isEmpty())media.add(((String)v).substring(1));}
        Object icon=data.getJSONObject("settings").opt("site_icon");if(icon instanceof String&&!((String)icon).isEmpty())media.add(((String)icon).substring(1));
        Map<String,PreparedAdmission.WindowsImage> windows=new HashMap<>();for(String n:media)windows.put(n,new PreparedAdmission.WindowsImage(p.files().get(n).sha256(),negativeMedia!=null&&n.equals("static/uploads/card.jpg")?PreparedAdmission.WindowsResult.REJECTED:PreparedAdmission.WindowsResult.VERIFIED));
        var request=new PreparedAdmission.Request(p,e.renderer(),kw,tw,e.preparationSha256(),windows,IMAGES,STORAGE);AtomicInteger reads=new AtomicInteger();
        var captured=CapturedCandidate.capture(target,source(pkg,reads),source(k,reads),source(t,reads),p,e.renderer(),kw,tw,STORAGE,new CapturedCandidate.Cancellation());
        pkg.clear();k.clear();t.clear();all.clear();return new Input(captured,request,reads);
    }
    static Input capture(android.content.Context target,android.content.Context tests,String name)throws Exception{return capture(target,tests,name,null);}
    static PreparedAdmission.Request replace(PreparedAdmission.Request r,Map<String,PreparedAdmission.WindowsImage> images,PreparedAdmission.ImageBudget budget,DevelopmentWitness.Renderer renderer){return new PreparedAdmission.Request(r.pkg(),renderer,r.kiosk(),r.tv(),r.preparationReference(),images,budget,r.storage());}
    static byte[] asset(android.content.Context tests,String name)throws Exception {return LocalView.readBounded(tests.getAssets().open(name),2L*1024*1024);}
    private static Map<String,byte[]> part(Map<String,byte[]> all,String root){Map<String,byte[]> out=new HashMap<>();all.forEach((n,b)->{if(n.startsWith(root+"/"))out.put(n.substring(root.length()+1),b.clone());});return out;}
    private static Map<String,DevelopmentWitness.Pin> pins(Map<String,byte[]> files){Map<String,DevelopmentWitness.Pin> pins=new HashMap<>();files.forEach((n,b)->pins.put(n,new DevelopmentWitness.Pin(b.length,LocalView.digest(b))));return pins;}
    private static LocalView.Source source(Map<String,byte[]> files,AtomicInteger reads){return new LocalView.Source(){public Set<String> files(){reads.incrementAndGet();return Set.copyOf(files.keySet());}public InputStream open(String n)throws IOException{reads.incrementAndGet();if(!files.containsKey(n))throw new IOException("missing");return new ByteArrayInputStream(files.get(n));}};}
    private static void update(JSONArray files,String name,byte[] bytes)throws Exception {for(int i=0;i<files.length();i++)if(files.getJSONObject(i).getString("path").equals(name)){files.getJSONObject(i).put("size",bytes.length).put("sha256",LocalView.digest(bytes));return;}throw new IOException("missing fixture media");}
}
