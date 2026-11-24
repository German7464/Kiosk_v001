package org.kiosk.harness.storage;

import java.nio.file.*;
import java.util.*;
import org.json.JSONObject;
import org.kiosk.harness.binding.*;
import org.kiosk.harness.core.LocalView;

/** Internal store metadata only. Loading it NEVER verifies source authority. */
final class AdmissionRecord {
    final PreparedAdmission.Request request;final String issuer;
    AdmissionRecord(PreparedAdmission.Request request,String issuer){this.request=request;this.issuer=issuer;}
    static boolean present(Path root,String id){Path r=root.resolve("revisions").resolve(id);return Files.exists(r.resolve("admission-required"),LinkOption.NOFOLLOW_LINKS)||Files.exists(r.resolve("admission.json"),LinkOption.NOFOLLOW_LINKS);}
    static AdmissionRecord load(Path root,String id)throws Exception {
        DevelopmentGrant.identity(id);Path revision=root.resolve("revisions").resolve(id);
        if(!present(root,id))return null;
        String marker=new String(PrivateFiles.metadata(revision.resolve("admission-required")),java.nio.charset.StandardCharsets.UTF_8);
        if(!marker.equals("native-local-admission-v1"))throw new java.io.IOException("admission_record_refused");
        var record=decode(new String(LocalView.readBounded(PrivateFiles.open(revision.resolve("admission.json")),DevelopmentGrant.LIMIT),java.nio.charset.StandardCharsets.UTF_8));
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
    private static long number(JSONObject j,String k)throws Exception {Object n=j.get(k);if(!(n instanceof Integer||n instanceof Long)||((Number)n).longValue()<0)throw new java.io.IOException("admission_record_type");return ((Number)n).longValue();}
    private static void keys(JSONObject j,String... names)throws Exception {Set<String> found=new HashSet<>();j.keys().forEachRemaining(found::add);if(!found.equals(Set.of(names)))throw new java.io.IOException("admission_record_fields");}
}
