package org.kiosk.harness.storage;

import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import org.json.JSONObject;

/** Internal closed-fixture metadata, never an Events contract. Canonical bytes required. */
final class StoreMetadata {
    record Pointer(String current,String previous) {
        String encode(){return "{\"schema\":1,\"current\":\""+current+"\",\"previous\":"+(previous==null?"null":"\""+previous+"\"")+"}";}
    }
    static Pointer pointer(Path file) throws Exception {
        String raw=new String(PrivateFiles.metadata(file),StandardCharsets.UTF_8);JSONObject data=new JSONObject(raw);
        String id=data.getString("current");DevelopmentGrant.identity(id);
        String prev=data.isNull("previous")?null:data.getString("previous");if(prev!=null)DevelopmentGrant.identity(prev);
        Pointer value=new Pointer(id,prev);if(!value.encode().equals(raw))throw PrivateFiles.refusal("invalid_pointer");return value;
    }
    static String receipt(String id){
        return receipt(id,"tv");
    }
    static String receipt(String id,String mode){
        var fixture=PublicationFixtures.identity(id);
        PublicationFixtures.mode(mode);
        return "{\"schema\":1,\"id\":\""+id+"\",\"mode\":\""+mode+"\",\"view\":\""+PublicationFixtures.viewFiles(fixture,mode).get("view.json").sha256()+"\",\"renderer\":\""+PublicationFixtures.build(mode)+"\"}";
    }
    static String receipt(Path path) throws Exception {
        return receipt(path,"tv");
    }
    static String receipt(Path path,String mode) throws Exception {
        String raw=new String(PrivateFiles.metadata(path),StandardCharsets.UTF_8);String id=new JSONObject(raw).getString("id");
        if(!receipt(id,mode,path.getParent()).equals(raw))throw PrivateFiles.refusal("invalid_receipt");return id;
    }
    static String receipt(String id,String mode,Path root)throws Exception{
        var admitted=AdmissionRecord.load(root,id);
        if(admitted!=null){
            if(admitted.page!=null){
                String expected=admitted.page.projection().startsWith("tv-")?"tv":"kiosk";
                if(!expected.equals(mode))throw PrivateFiles.refusal("page_release_mode");
                return "{\"schema\":2,\"id\":\""+id+"\",\"mode\":\""+mode+"\",\"view\":\""+admitted.page.viewFiles().get("view.json").sha256()+"\",\"renderer\":\""+admitted.page.renderer()+"\"}";
            }
            var r=admitted.request;var files=mode.equals("tv")?r.tv().files():r.kiosk().files();PublicationFixtures.mode(mode);
            return "{\"schema\":1,\"id\":\""+id+"\",\"mode\":\""+mode+"\",\"view\":\""+files.get("view.json").sha256()+"\",\"renderer\":\""+r.renderer().identity()+"\"}";
        }
        var grant=DevelopmentGrant.load(root,id);if(grant==null)return receipt(id,mode);
        var p=grant.permit;var files=mode.equals("tv")?p.tv.files():p.kiosk.files();PublicationFixtures.mode(mode);
        return "{\"schema\":1,\"id\":\""+id+"\",\"mode\":\""+mode+"\",\"view\":\""+files.get("view.json").sha256()+"\",\"renderer\":\""+p.renderer.identity()+"\"}";
    }
    static String mode(String mode){return "{\"schema\":1,\"mode\":\""+PublicationFixtures.mode(mode)+"\"}";}
    static String mode(Path path) throws Exception {
        String raw=new String(PrivateFiles.metadata(path),StandardCharsets.UTF_8);String mode=new JSONObject(raw).getString("mode");
        if(!mode(mode).equals(raw))throw PrivateFiles.refusal("invalid_mode");return mode;
    }
}
