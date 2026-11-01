package org.kiosk.harness.storage;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.JSONObject;
import org.kiosk.harness.binding.DevelopmentWitness;
import org.kiosk.harness.core.LocalView;

/** Native-owned persisted authority, never accepted from package sources; internal experimental metadata. */
final class DevelopmentGrant {
    static final int LIMIT=8*1024*1024;
    final DevelopmentPlaybackAuthority.Permit permit;
    DevelopmentGrant(DevelopmentPlaybackAuthority.Permit permit){this.permit=permit;}
    static Path path(Path root,String id){identity(id);return root.resolve("development-authority").resolve(id+".json");}
    static void identity(String id){if(id==null||!id.matches("[0-9a-f]{64}"))throw new IllegalArgumentException("invalid_identity");}
    static DevelopmentGrant load(Path root,String id)throws Exception{
        Path path=path(root,id);if(!Files.exists(path,LinkOption.NOFOLLOW_LINKS))return null;
        var j=new JSONObject(new String(LocalView.readBounded(PrivateFiles.open(path),LIMIT),StandardCharsets.UTF_8));
        if(j.getInt("schema")!=1||!j.getString("authority").equals("native_unverified_development_only")||!j.getString("identity").equals(id))throw PrivateFiles.refusal("invalid_development_authority");
        var p=new DevelopmentWitness.Package(id,j.getString("raw_manifest"),readPins(j.getJSONObject("package")));
        var r=new DevelopmentWitness.Renderer(j.getString("renderer"),j.getString("js"),j.getString("css"));
        var grant=new DevelopmentGrant(DevelopmentPlaybackAuthority.authorizeUnverifiedDevelopmentPlayback(p,r,
            new DevelopmentWitness.Artifact("kiosk",id,r.identity(),readPins(j.getJSONObject("kiosk"))),
            new DevelopmentWitness.Artifact("tv",id,r.identity(),readPins(j.getJSONObject("tv")))));
        if(!grant.fingerprint().equals(j.getString("witness_fingerprint"))||!p.rawManifestSha256().equals(p.files().get("manifest.json").sha256()))throw PrivateFiles.refusal("invalid_development_authority");return grant;
    }
    String encode()throws Exception{
        return new JSONObject().put("schema",1).put("authority","native_unverified_development_only").put("witness_fingerprint",fingerprint())
            .put("identity",permit.pkg.canonicalIdentity()).put("raw_manifest",permit.pkg.rawManifestSha256())
            .put("renderer",permit.renderer.identity()).put("js",permit.renderer.trustedJsSha256()).put("css",permit.renderer.trustedCssSha256())
            .put("package",pins(permit.pkg.files())).put("kiosk",pins(permit.kiosk.files())).put("tv",pins(permit.tv.files())).toString();
    }
    String fingerprint(){
        var p=permit;StringBuilder text=new StringBuilder("development-only\n").append(p.pkg.canonicalIdentity()).append('\n').append(p.pkg.rawManifestSha256()).append('\n')
            .append(p.renderer.identity()).append('\n').append(p.renderer.trustedJsSha256()).append('\n').append(p.renderer.trustedCssSha256()).append('\n');
        for(var group:List.of(p.pkg.files(),p.kiosk.files(),p.tv.files())){text.append("group\n");for(var e:new TreeMap<>(group).entrySet())text.append(e.getKey()).append('\n').append(e.getValue().size()).append('\n').append(e.getValue().sha256()).append('\n');}
        return LocalView.digest(text.toString().getBytes(StandardCharsets.UTF_8));
    }
    private static JSONObject pins(Map<String,DevelopmentWitness.Pin> pins)throws Exception{
        var json=new JSONObject();for(var e:new TreeMap<>(pins).entrySet())json.put(e.getKey(),new JSONObject().put("size",e.getValue().size()).put("sha256",e.getValue().sha256()));return json;
    }
    private static Map<String,DevelopmentWitness.Pin> readPins(JSONObject json)throws Exception{
        if(json.length()>10001)throw PrivateFiles.refusal("authority_limit");Map<String,DevelopmentWitness.Pin> pins=new HashMap<>();
        for(var i=json.keys();i.hasNext();){String name=i.next();var p=json.getJSONObject(name);pins.put(name,new DevelopmentWitness.Pin(p.getLong("size"),p.getString("sha256")));}return pins;
    }
    // Compatibility with existing streamed copy/private-file primitives; no identity lookup here.
    static Map<String,PublicationFixtures.Pin> copyPins(Map<String,DevelopmentWitness.Pin> pins){
        Map<String,PublicationFixtures.Pin> out=new HashMap<>();pins.forEach((n,p)->out.put(n,new PublicationFixtures.Pin(p.size(),p.sha256())));return Map.copyOf(out);
    }
}
