package org.kiosk.harness.binding;

import java.io.*;
import java.nio.file.*;
import java.util.*;
import org.json.JSONObject;
import org.kiosk.harness.core.LocalView;
import static org.kiosk.harness.binding.CapturedCandidate.*;

public final class CaptureVectors {
    private static final Budget BUDGET=new Budget(8L*1024*1024,100,1024);
    private static final Hooks HOOKS=new Hooks(){};
    private static void check(boolean b){if(!b)throw new AssertionError("capture vector");}
    private static CapturedCandidate capture(Path root,BindingVectors.Data d,Budget budget,Cancellation cancel,Hooks hooks)throws Exception{
        return CapturedCandidate.captureAt(root,d.p,d.k,d.t,d.pkg,d.renderer,d.kiosk,d.tv,budget,cancel,hooks);
    }
    private static void empty(Path root)throws Exception{if(Files.exists(root))try(var walk=Files.list(root)){check(walk.count()==0);}}
    private static void refuse(Path root,BindingVectors.Data d,Budget b,Cancellation c,Hooks h,CaptureFailure.Code code)throws Exception{
        try{capture(root,d,b,c,h);throw new AssertionError("unexpected captured success");}
        catch(CaptureFailure e){if(code!=null)check(e.code==code);check(e.getMessage().equals(e.code.name())&&e.getCause()==null&&e.getSuppressed().length==0);}
        d.closed();empty(root);
    }
    public static void independent(Path root,BindingVectors.Loader loader)throws Exception{
        BindingVectors.Data d=new BindingVectors.Data(loader);
        try(var s=capture(root,d,BUDGET,new Cancellation(),HOOKS)){
            d.closed();int reads=d.p.opened+d.k.opened+d.t.opened;
            d.p.files.clear();d.k.files.clear();d.t.files.clear();
            for(Part part:Part.values()){
                var all=loader.load();String prefix=part==Part.PACKAGE?"package":part==Part.KIOSK?"view-kiosk":"view-tv";
                for(String path:s.source(part).files())try(InputStream in=s.source(part).open(path)){
                    check(Arrays.equals(LocalView.readBounded(in,2L*1024*1024),all.get(prefix+"/"+path)));
                }
            }
            check(reads==d.p.opened+d.k.opened+d.t.opened);
            check(s.report().unchecked().size()==5&&s.scopedGuarantees().size()==4);
        }
        empty(root);
    }
    public static void corruptCaptured(Path root,BindingVectors.Loader loader)throws Exception{
        BindingVectors.Data d=new BindingVectors.Data(loader);final Path[] owned={null};
        try(var s=capture(root,d,BUDGET,new Cancellation(),new Hooks(){public void at(String phase,Path path){owned[0]=path;}})){
            Path p=owned[0].resolve("KIOSK/index.html");byte[] bytes=Files.readAllBytes(p);bytes[bytes.length-1]^=1;Files.write(p,bytes);
            try{s.source(Part.KIOSK).open("index.html");throw new AssertionError("unverified handle exposed");}
            catch(CaptureFailure e){check(e.code==CaptureFailure.Code.CORRUPT_CAPTURE);}
        }
        empty(root);
    }
    public static void mutations(Path root,BindingVectors.Loader loader)throws Exception{
        BindingVectors.Data d=new BindingVectors.Data(loader);BindingVectors.Data chosen=d;boolean[] changed={false};
        refuse(root,d,BUDGET,new Cancellation(),new Hooks(){public void at(String phase,Path path){
            if(phase.equals("chunk")&&!changed[0]&&chosen.p.reads.containsKey("resources/static/img/site_icon.png")){
                byte[] b=chosen.p.files.get("resources/static/img/site_icon.png");b[b.length-1]^=1;changed[0]=true;
            }
        }},CaptureFailure.Code.CAPTURE_FAILED);check(changed[0]);
        d=new BindingVectors.Data(loader);boolean[] during={false};
        refuse(root,d,BUDGET,new Cancellation(),new Hooks(){public void at(String phase,Path path)throws IOException{
            if(phase.equals("binding_read")&&!during[0]){during[0]=true;Path p=path.resolve("TV/index.html");byte[] b=Files.readAllBytes(p);b[0]^=1;Files.write(p,b);}
        }},CaptureFailure.Code.BINDING_FAILED);check(during[0]);
    }
    public static void faultyStreams(Path root,BindingVectors.Loader loader)throws Exception{
        for(String fault:List.of("short","overlong","zero","error","close")){
            BindingVectors.Data d=new BindingVectors.Data(loader);d.p.fault=fault;
            refuse(root,d,BUDGET,new Cancellation(),HOOKS,CaptureFailure.Code.CAPTURE_FAILED);
            d=new BindingVectors.Data(loader);d.t.target="index.html";d.t.fault=fault;
            refuse(root,d,BUDGET,new Cancellation(),HOOKS,CaptureFailure.Code.CAPTURE_FAILED);
        }
        BindingVectors.Data d=new BindingVectors.Data(loader);d.t.files.put("extra",new byte[0]);refuse(root,d,BUDGET,new Cancellation(),HOOKS,CaptureFailure.Code.CAPTURE_FAILED);
        d=new BindingVectors.Data(loader);d.k.files.remove("view.json");refuse(root,d,BUDGET,new Cancellation(),HOOKS,CaptureFailure.Code.CAPTURE_FAILED);
        d=new BindingVectors.Data(loader);d.pkg=new DevelopmentWitness.Package("0".repeat(64),d.pkg.rawManifestSha256(),d.pkg.files());refuse(root,d,BUDGET,new Cancellation(),HOOKS,CaptureFailure.Code.BINDING_FAILED);
    }
    public static void cancellation(Path root,BindingVectors.Loader loader)throws Exception{
        for(String boundary:List.of("prior","created","manifest","before_file","chunk","file","before_binding","binding_read","bound")){
            Cancellation cancel=new Cancellation();if(boundary.equals("prior"))cancel.cancel();
            refuse(root,new BindingVectors.Data(loader),BUDGET,cancel,new Hooks(){public void at(String phase,Path path){if(phase.equals(boundary))cancel.cancel();}},CaptureFailure.Code.CANCELLED);
        }
        refuse(root,new BindingVectors.Data(loader),BUDGET,new Cancellation(),new Hooks(){public void at(String phase,Path path)throws IOException{if(phase.equals("file"))throw new IOException("private/path");}},CaptureFailure.Code.CAPTURE_FAILED);
    }
    public static void budgets(Path root,BindingVectors.Loader loader)throws Exception{
        refuse(root,new BindingVectors.Data(loader),new Budget(1,100,0),new Cancellation(),HOOKS,CaptureFailure.Code.BUDGET_EXCEEDED);
        refuse(root,new BindingVectors.Data(loader),new Budget(Long.MAX_VALUE,1,0),new Cancellation(),HOOKS,CaptureFailure.Code.BUDGET_EXCEEDED);
        refuse(root,new BindingVectors.Data(loader),new Budget(-1,100,0),new Cancellation(),HOOKS,CaptureFailure.Code.INVALID_BUDGET);
        refuse(root,new BindingVectors.Data(loader),BUDGET,new Cancellation(),new Hooks(){public long usable(Path p){return 0;}},CaptureFailure.Code.INSUFFICIENT_SPACE);
        final int[] n={0};refuse(root,new BindingVectors.Data(loader),BUDGET,new Cancellation(),new Hooks(){public long usable(Path p){return ++n[0]>2?0:Long.MAX_VALUE;}},CaptureFailure.Code.INSUFFICIENT_SPACE);
    }
    public static void lifecycle(Path root,BindingVectors.Loader loader)throws Exception{
        CapturedCandidate a=capture(root,new BindingVectors.Data(loader),BUDGET,new Cancellation(),HOOKS);
        try(var b=capture(root,new BindingVectors.Data(loader),BUDGET,new Cancellation(),HOOKS)){
            var source=a.source(Part.KIOSK);InputStream open=source.open("index.html");check(open.read()>=0);
            a.close();a.close();
            try{open.read();throw new AssertionError();}catch(CaptureFailure e){check(e.code==CaptureFailure.Code.CLOSED);}
            open.close();
            try{source.files();throw new AssertionError();}catch(CaptureFailure e){check(e.code==CaptureFailure.Code.CLOSED);}
            try{source.open("index.html");throw new AssertionError();}catch(CaptureFailure e){check(e.code==CaptureFailure.Code.CLOSED);}
            try{a.report();throw new AssertionError();}catch(CaptureFailure e){check(e.code==CaptureFailure.Code.CLOSED);}
            try(InputStream in=b.source(Part.TV).open("index.html")){check(in.read()>=0);}
        }finally{a.close();}
        empty(root);
    }
    public static void earlyCompatibility(Path root,BindingVectors.Loader loader)throws Exception{
        var d=new BindingVectors.Data(loader);JSONObject m=new JSONObject(new String(d.p.files.get("manifest.json"),java.nio.charset.StandardCharsets.UTF_8));m.put("resource_contract",2);
        byte[] raw=m.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);d.p.files.put("manifest.json",raw);
        var pins=new HashMap<>(d.pkg.files());pins.put("manifest.json",new DevelopmentWitness.Pin(raw.length,LocalView.digest(raw)));
        d.pkg=new DevelopmentWitness.Package(d.pkg.canonicalIdentity(),LocalView.digest(raw),pins);
        refuse(root,d,BUDGET,new Cancellation(),HOOKS,CaptureFailure.Code.CAPTURE_FAILED);
        check(d.p.reads.keySet().equals(Set.of("manifest.json"))&&d.k.opened==0&&d.t.opened==0);
    }
}
