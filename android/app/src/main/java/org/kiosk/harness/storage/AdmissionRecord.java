package org.kiosk.harness.storage;

import java.nio.file.*;
import java.util.*;
import org.json.JSONObject;
import org.kiosk.harness.binding.*;
import org.kiosk.harness.core.LocalView;

/** Internal store metadata only. Loading it NEVER verifies source authority. */
final class AdmissionRecord {
    static final String LEGACY_MARKER="native-local-admission-v1",PAGE_MARKER="native-page-release-v2";
    record Page(String issuer,String packageId,String revision,String rawManifest,String renderer,String js,String css,
                String destination,String projection,String contentSha256,String metadataSha256,String plan,String target,String preparation,
                Map<String,DevelopmentWitness.Pin> packageFiles,Map<String,DevelopmentWitness.Pin> viewFiles,
                long maxBytes,int maxFiles,long minFreeBytes){}
    final PreparedAdmission.Request request;final Page page;final String issuer;
    AdmissionRecord(PreparedAdmission.Request request,String issuer){this.request=request;this.page=null;this.issuer=issuer;}
    AdmissionRecord(Page page,String issuer){this.request=null;this.page=page;this.issuer=issuer;}
    static boolean present(Path root,String id){Path r=root.resolve("revisions").resolve(id);return Files.exists(r.resolve("admission-required"),LinkOption.NOFOLLOW_LINKS)||Files.exists(r.resolve("admission.json"),LinkOption.NOFOLLOW_LINKS);}
    static AdmissionRecord load(Path root,String id)throws Exception {
        DevelopmentGrant.identity(id);Path revision=root.resolve("revisions").resolve(id);
        if(!present(root,id))return null;
        String marker=new String(PrivateFiles.metadata(revision.resolve("admission-required")),java.nio.charset.StandardCharsets.UTF_8);
        if(!marker.equals(LEGACY_MARKER)&&!marker.equals(PAGE_MARKER))throw new java.io.IOException("admission_record_refused");
        String raw=new String(LocalView.readBounded(PrivateFiles.open(revision.resolve("admission.json")),DevelopmentGrant.LIMIT),java.nio.charset.StandardCharsets.UTF_8);
        if(marker.equals(PAGE_MARKER)){
            AdmissionRecord record=decodePage(raw);
            if(!record.page.packageId().equals(id))throw new java.io.IOException("admission_record_refused");return record;
        }
        var record=decode(raw);
        if(!record.request.pkg().canonicalIdentity().equals(id))throw new java.io.IOException("admission_record_refused");return record;
    }
    static JSONObject pins(Map<String,DevelopmentWitness.Pin> pins)throws Exception {JSONObject j=new JSONObject();for(var e:new TreeMap<>(pins).entrySet())j.put(e.getKey(),new JSONObject().put("size",e.getValue().size()).put("sha256",e.getValue().sha256()));return j;}
    static Map<String,DevelopmentWitness.Pin> pins(JSONObject j)throws Exception {if(j.length()>10001)throw new java.io.IOException("admission_record_bound");Map<String,DevelopmentWitness.Pin> out=new HashMap<>();for(var it=j.keys();it.hasNext();){String n=it.next();var p=j.getJSONObject(n);keys(p,"size","sha256");out.put(n,new DevelopmentWitness.Pin(number(p,"size"),p.getString("sha256")));}return out;}
    String encode()throws Exception {
        var r=request;var image=new JSONObject();for(var e:new TreeMap<>(r.windowsImages()).entrySet())image.put(e.getKey(),new JSONObject().put("sha256",e.getValue().sha256()).put("result",e.getValue().result().name()));
        return new JSONObject().put("schema",1).put("issuer",issuer).put("identity",r.pkg().canonicalIdentity()).put("raw_manifest",r.pkg().rawManifestSha256())
            .put("renderer",r.renderer().identity()).put("js",r.renderer().trustedJsSha256()).put("css",r.renderer().trustedCssSha256())
            .put("package",pins(r.pkg().files())).put("kiosk",pins(r.kiosk().files())).put("tv",pins(r.tv().files()))
            .put("preparation",r.preparationReference()).put("windows_images",image)
            .put("pixels",r.images().maxPixels()).put("live_bytes",r.images().maxLiveBytes()).put("image_ms",r.images().perImageMillis()).put("total_ms",r.images().totalMillis())
            .put("store_bytes",r.storage().maxBytes()).put("store_files",r.storage().maxFiles()).put("free_bytes",r.storage().minFreeBytes()).toString();
    }
    static AdmissionRecord decode(String text)throws Exception {
        var j=new JSONObject(text);keys(j,"schema","issuer","identity","raw_manifest","renderer","js","css","package","kiosk","tv","preparation","windows_images","pixels","live_bytes","image_ms","total_ms","store_bytes","store_files","free_bytes");
        if(number(j,"schema")!=1)throw new java.io.IOException("admission_record_version");String id=j.getString("identity"),renderer=j.getString("renderer");
        Map<String,PreparedAdmission.WindowsImage> images=new HashMap<>();var im=j.getJSONObject("windows_images");if(im.length()>10001)throw new java.io.IOException("admission_record_bound");
        for(var it=im.keys();it.hasNext();){String n=it.next();var v=im.getJSONObject(n);keys(v,"sha256","result");images.put(n,new PreparedAdmission.WindowsImage(v.getString("sha256"),PreparedAdmission.WindowsResult.valueOf(v.getString("result"))));}
        long count=number(j,"store_files");if(count>Integer.MAX_VALUE)throw new java.io.IOException("admission_record_bound");
        var r=new PreparedAdmission.Request(new DevelopmentWitness.Package(id,j.getString("raw_manifest"),pins(j.getJSONObject("package"))),new DevelopmentWitness.Renderer(renderer,j.getString("js"),j.getString("css")),
            new DevelopmentWitness.Artifact("kiosk",id,renderer,pins(j.getJSONObject("kiosk"))),new DevelopmentWitness.Artifact("tv",id,renderer,pins(j.getJSONObject("tv"))),j.getString("preparation"),images,
            new PreparedAdmission.ImageBudget(number(j,"pixels"),number(j,"live_bytes"),number(j,"image_ms"),number(j,"total_ms")),new CapturedCandidate.Budget(number(j,"store_bytes"),(int)count,number(j,"free_bytes")));
        r.checkBudgets();return new AdmissionRecord(r,j.getString("issuer"));
    }
    static String encodePage(Page page)throws Exception {
        return new JSONObject().put("schema",2).put("kind","pages").put("issuer",page.issuer())
            .put("identity",page.packageId()).put("revision",page.revision()).put("raw_manifest",page.rawManifest())
            .put("renderer",page.renderer()).put("js",page.js()).put("css",page.css())
            .put("destination",page.destination()).put("projection",page.projection())
            .put("content_sha256",page.contentSha256()).put("metadata_sha256",page.metadataSha256())
            .put("plan",page.plan()).put("target",page.target())
            .put("preparation",page.preparation()).put("package",pins(page.packageFiles())).put("view",pins(page.viewFiles()))
            .put("store_bytes",page.maxBytes()).put("store_files",page.maxFiles()).put("free_bytes",page.minFreeBytes()).toString();
    }
    static AdmissionRecord decodePage(String text)throws Exception {
        var j=new JSONObject(text);
        keys(j,"schema","kind","issuer","identity","revision","raw_manifest","renderer","js","css","destination",
            "projection","content_sha256","metadata_sha256","plan","target","preparation","package","view","store_bytes","store_files","free_bytes");
        if(number(j,"schema")!=2||!"pages".equals(j.getString("kind")))throw new java.io.IOException("admission_record_version");
        for(String name:List.of("identity","revision","raw_manifest","renderer","js","css","content_sha256","metadata_sha256"))
            if(!j.getString(name).matches("[a-f0-9]{64}"))throw new java.io.IOException("admission_record_type");
        String plan=j.getString("plan"),target=j.getString("target");
        if(plan.isEmpty()||target.isEmpty()||plan.length()>org.kiosk.harness.delivery.PageReleaseProtocol.MAX_DOCUMENT
            ||target.length()>org.kiosk.harness.delivery.PageReleaseProtocol.MAX_DOCUMENT)
            throw new java.io.IOException("admission_record_bound");
        String destination=j.getString("destination"),projection=j.getString("projection");
        if(!org.kiosk.harness.delivery.PageReleaseProtocol.DESTINATIONS.contains(destination)
            ||!org.kiosk.harness.delivery.PageReleaseProtocol.PROJECTIONS.contains(projection))
            throw new java.io.IOException("admission_record_type");
        long count=number(j,"store_files");if(count>Integer.MAX_VALUE)throw new java.io.IOException("admission_record_bound");
        var page=new Page(j.getString("issuer"),j.getString("identity"),j.getString("revision"),j.getString("raw_manifest"),
            j.getString("renderer"),j.getString("js"),j.getString("css"),destination,projection,j.getString("content_sha256"),
            j.getString("metadata_sha256"),plan,target,j.getString("preparation"),pins(j.getJSONObject("package")),pins(j.getJSONObject("view")),
            number(j,"store_bytes"),(int)count,number(j,"free_bytes"));
        return new AdmissionRecord(page,j.getString("issuer"));
    }
    private static long number(JSONObject j,String k)throws Exception {Object n=j.get(k);if(!(n instanceof Integer||n instanceof Long)||((Number)n).longValue()<0)throw new java.io.IOException("admission_record_type");return ((Number)n).longValue();}
    private static void keys(JSONObject j,String... names)throws Exception {Set<String> found=new HashSet<>();j.keys().forEachRemaining(found::add);if(!found.equals(Set.of(names)))throw new java.io.IOException("admission_record_fields");}
}
