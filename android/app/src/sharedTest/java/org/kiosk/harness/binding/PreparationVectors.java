package org.kiosk.harness.binding;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import org.kiosk.harness.core.LocalView;
public final class PreparationVectors {
    public interface Loader {Map<String,byte[]> load(String name)throws Exception;}
    private interface Work{void run()throws Exception;}
    private static void check(boolean b){if(!b)throw new AssertionError("preparation vector");}
    private static void refuses(Work w)throws Exception{try{w.run();throw new AssertionError("unconfirmed success");}catch(IOException expected){}}
    static LocalPreparation.Evidence evidence(Map<String,byte[]> all,String name)throws Exception{var c=LocalPreparation.Confirmation.valueOf(name);return LocalPreparation.confirm(new ByteArrayInputStream(all.get("preparation.json")),c,c.sha256);}
    public static void valid(Loader loader)throws Exception{
        for(String name:List.of("C","B")){var all=loader.load(name);var e=evidence(all,name);var r=LocalPreparation.inspect(all,e);check(r.unchecked().size()==5);check(r.callerAttestedCanonicalPackageIdentity().equals(e.pkg().canonicalIdentity()));check(e.windowsEnvironment().contains("13.0.0"));}
    }
    public static void confirmations(Loader loader)throws Exception{
        byte[] original=loader.load("C").get("preparation.json");var c=LocalPreparation.Confirmation.C;
        for(String digest:Arrays.asList(null,"","0".repeat(64),LocalPreparation.Confirmation.B.sha256))refuses(()->LocalPreparation.confirm(new ByteArrayInputStream(original),c,digest));
        refuses(()->LocalPreparation.confirm(new ByteArrayInputStream(original),null,c.sha256));
        for(String field:List.of("package_identity","renderer_identity","path","sha256","size","scope")){
            String raw=new String(original,java.nio.charset.StandardCharsets.UTF_8);byte[] changed=raw.replaceFirst("\""+field+"\"","\"changed_"+field+"\"").getBytes(java.nio.charset.StandardCharsets.UTF_8);
            refuses(()->LocalPreparation.confirm(new ByteArrayInputStream(changed),c,LocalView.digest(changed)));
            refuses(()->LocalPreparation.confirm(new ByteArrayInputStream(changed),c,c.sha256));
        }
        refuses(()->LocalPreparation.confirm(new ByteArrayInputStream(new byte[256*1024+1]),c,c.sha256));
        final boolean[] closed={false};refuses(()->LocalPreparation.confirm(new ByteArrayInputStream(original){public void close(){closed[0]=true;}},c,"bad"));check(closed[0]);
    }
    public static void contentTampering(Loader loader)throws Exception{
        for(String target:List.of("package","html","inventory","descriptor","renderer")){
            var all=loader.load("C");var e=evidence(all,"C");String key=switch(target){case "package"->e.packageRoot()+"/data/events.json";case "html"->e.kioskRoot()+"/index.html";case "descriptor"->e.tvRoot()+"/view.json";case "renderer"->e.tvRoot()+"/events.js";default->e.packageRoot()+"/extra";};
            if(target.equals("inventory"))all.put(key,new byte[0]);else all.get(key)[0]^=1;
            refuses(()->LocalPreparation.inspect(all,e));
        }
    }
    public static void captureFailures(Path root,Loader loader)throws Exception{
        for(String fault:List.of("mutate","cancel","space")){
            var all=loader.load("C");var e=evidence(all,"C");var p=LocalPreparation.source(all,e.packageRoot(),e.pkg().files());var k=LocalPreparation.source(all,e.kioskRoot(),e.kiosk().files());var t=LocalPreparation.source(all,e.tvRoot(),e.tv().files());
            var cancel=new CapturedCandidate.Cancellation();boolean[] injected={false};
            CapturedCandidate.Hooks hooks=new CapturedCandidate.Hooks(){
                public long usable(Path path){return fault.equals("space")?0:Long.MAX_VALUE;}
                public void at(String phase,Path path){if(!injected[0]&&phase.equals("before_file")){injected[0]=true;if(fault.equals("cancel"))cancel.cancel();if(fault.equals("mutate"))for(byte[] bytes:p.files.values())bytes[0]^=1;}}
            };
            refuses(()->{try(var capture=CapturedCandidate.captureAt(root,p,k,t,e.pkg(),e.renderer(),e.kiosk(),e.tv(),new CapturedCandidate.Budget(8L*1024*1024,100,1024),cancel,hooks)){throw new AssertionError("fault admitted");}});
            check(p.opened==p.closed&&k.opened==k.closed&&t.opened==t.closed);
            if(Files.exists(root))try(var paths=Files.list(root)){check(paths.count()==0);}
        }
    }
}
