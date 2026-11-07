package org.kiosk.harness.storage;

import java.io.*;
import java.util.*;
import org.json.JSONObject;
import org.kiosk.harness.binding.*;
import org.kiosk.harness.core.LocalView;

/** Native typed input only. Neither these facts nor a persisted record establish source authority. */
public final class PreparedAdmission {
    private PreparedAdmission(){}
    public enum WindowsResult { VERIFIED, REJECTED }
    public enum Phase { NEW_ACTIVATION, PRIVATE_REOPEN }
    public record WindowsImage(String sha256,WindowsResult result){}
    public record ImageBudget(long maxPixels,long maxLiveBytes,long perImageMillis,long totalMillis){
        public void check()throws IOException {if(maxPixels<=0||maxLiveBytes<=0||perImageMillis<=0||totalMillis<=0||perImageMillis>totalMillis)throw new IOException("image_budget_required");}
        public long estimatedLive(int width,int height,long encoded)throws IOException {
            check();try{long pixels=Math.multiplyExact((long)width,height);long live=Math.addExact(encoded,Math.multiplyExact(pixels,8));
                if(width<=0||height<=0||pixels>maxPixels||encoded<0||live>maxLiveBytes)throw new IOException("image_budget_exceeded");return live;
            }catch(ArithmeticException e){throw new IOException("image_budget_exceeded");}
        }
    }
    public record Request(DevelopmentWitness.Package pkg,DevelopmentWitness.Renderer renderer,
                          DevelopmentWitness.Artifact kiosk,DevelopmentWitness.Artifact tv,
                          String preparationReference,Map<String,WindowsImage> windowsImages,
                          ImageBudget images,CapturedCandidate.Budget storage){
        public Request {windowsImages=windowsImages==null?Map.of():Map.copyOf(windowsImages);}
        /** Internal binding for independent native verifiers; it is not a signature or bootstrap. */
        public String factsFingerprint(){
            StringBuilder b=new StringBuilder("prepared-local-facts-v1\n").append(pkg.canonicalIdentity()).append('\n').append(pkg.rawManifestSha256()).append('\n')
                .append(renderer.identity()).append('\n').append(renderer.trustedJsSha256()).append('\n').append(renderer.trustedCssSha256()).append('\n');
            for(var group:List.of(pkg.files(),kiosk.files(),tv.files())){b.append("group\n");for(var e:new TreeMap<>(group).entrySet())b.append(e.getKey()).append('\n').append(e.getValue().size()).append('\n').append(e.getValue().sha256()).append('\n');}
            b.append(preparationReference).append('\n');for(var e:new TreeMap<>(windowsImages).entrySet())b.append(e.getKey()).append('\n').append(e.getValue().sha256()).append('\n').append(e.getValue().result()).append('\n');
            return LocalView.digest(b.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
        }
        public void checkBudgets()throws IOException {
            if(images==null||storage==null||storage.maxBytes()<=0||storage.maxFiles()<=0||storage.minFreeBytes()<0)throw new IOException("explicit_budgets_required");images.check();
        }
    }
    public interface SourceVerifier {
        String issuerId();
        /** Must independently validate exact facts/permission for this phase; never trust self assertions. */
        void verify(Request request,Phase phase)throws IOException;
    }
    public interface VerifierProvider {SourceVerifier current();}
    public static final VerifierProvider UNAVAILABLE=()->null;
    public static SourceVerifier require(VerifierProvider provider)throws IOException {
        SourceVerifier v=provider==null?null:provider.current();if(v==null||v.issuerId()==null||v.issuerId().isEmpty()||v.issuerId().length()>128)throw new IOException("source_verifier_unavailable");return v;
    }
    static Set<String> referenced(LocalView.Source pkg)throws Exception {
        JSONObject data=new JSONObject(new String(LocalView.readBounded(pkg.open("data/events.json"),2L*1024*1024),java.nio.charset.StandardCharsets.UTF_8));
        Set<String> names=new TreeSet<>();names.add("resources/static/img/site_icon.png");
        var events=data.getJSONArray("events");for(int i=0;i<events.length();i++)for(String field:List.of("image_kiosk","image_tv","image_thumb")){
            Object v=events.getJSONObject(i).opt(field);if(v instanceof String&&!((String)v).isEmpty())names.add(mediaPath((String)v));
        }
        Object icon=data.getJSONObject("settings").opt("site_icon");if(icon instanceof String&&!((String)icon).isEmpty())names.add(mediaPath((String)icon));return names;
    }
    private static String mediaPath(String value)throws IOException {if(!value.startsWith("/static/uploads/"))throw new IOException("image_reference");return value.substring(1);}
    static String validate(LocalView.Source pkg,LocalView.Source kiosk,LocalView.Source tv,Request r,SourceVerifier issuer,Phase phase,FixturePublicationStore.Checkpoint cancel)throws Exception {
        if(issuer==null)throw new IOException("source_verifier_unavailable");r.checkBudgets();cancel.hit("admission.validation");
        PublicationBinding.inspect(pkg,kiosk,tv,r.pkg(),r.renderer(),r.kiosk(),r.tv());
        Set<String> names=referenced(pkg);if(!r.windowsImages().keySet().equals(names))throw new IOException("windows_evidence_missing");
        for(String name:names){var evidence=r.windowsImages().get(name);var pin=r.pkg().files().get(name);
            if(evidence==null||evidence.result()!=WindowsResult.VERIFIED)throw new IOException("windows_image_rejected");
            if(pin==null||!pin.sha256().equals(evidence.sha256()))throw new IOException("windows_bytes_mismatch");
        }
        issuer.verify(r,phase);cancel.hit("admission.issuer_verified");
        AndroidImageValidation.verify(pkg,r,names,cancel);cancel.hit("admission.images_verified");return issuer.issuerId();
    }
}
