package org.kiosk.harness.binding;

import android.content.Context;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.packagecore.EventsPackage;
import static org.kiosk.harness.binding.CaptureFailure.Code.*;

/** Disposable verified captured bytes, never a publication or activation candidate admission. */
public final class CapturedCandidate implements AutoCloseable {
    public enum Part { PACKAGE, KIOSK, TV }
    public enum ScopedGuarantee { PROVIDER_INDEPENDENT_CAPTURE, VERIFIED_BEFORE_OPEN, REVOKED_ON_CLOSE, EXCLUSIVE_APP_OWNED_MODEL_ONLY }
    public record Budget(long maxBytes,int maxFiles,long minFreeBytes){}
    public static final class Cancellation {
        private final AtomicBoolean cancelled=new AtomicBoolean();
        public void cancel(){cancelled.set(true);}
        void check(){if(cancelled.get())throw new java.util.concurrent.CancellationException();}
    }
    // Native tests only, no Intent/page/reflection controller. Default path never exposes the directory.
    interface Hooks {
        default void at(String phase,Path owned)throws IOException{}
        default long usable(Path root){return root.toFile().getUsableSpace();}
    }
    private static final Hooks PLATFORM=new Hooks(){};
    private final Path owned;
    private final Map<Part,Map<String,DevelopmentWitness.Pin>> pins;
    private final Set<InputStream> opened=new HashSet<>();
    private final PublicationBinding.Report report;
    private boolean closed;
    private AutoCloseable ownership;
    private CapturedCandidate(Path owned,Map<Part,Map<String,DevelopmentWitness.Pin>> pins,PublicationBinding.Report report){
        this.owned=owned;this.pins=Map.copyOf(pins);this.report=report;
    }
    static CapturedCandidate adopt(Path owned,Map<Part,Map<String,DevelopmentWitness.Pin>> pins,PreparedFacts facts,AutoCloseable ownership)throws Exception {
        var p=CaptureFiles.source(owned.resolve("PACKAGE"),pins.get(Part.PACKAGE),()->{});
        var k=CaptureFiles.source(owned.resolve("KIOSK"),pins.get(Part.KIOSK),()->{});
        var t=CaptureFiles.source(owned.resolve("TV"),pins.get(Part.TV),()->{});
        var report=PublicationBinding.inspect(p,k,t,facts.pkg,facts.renderer,facts.kiosk,facts.tv);
        CapturedCandidate c=new CapturedCandidate(owned,pins,report);c.ownership=ownership;return c;
    }
    record PreparedFacts(DevelopmentWitness.Package pkg,DevelopmentWitness.Renderer renderer,DevelopmentWitness.Artifact kiosk,DevelopmentWitness.Artifact tv){}
    public static CapturedCandidate capture(Context context,LocalView.Source pkg,LocalView.Source kiosk,LocalView.Source tv,
            DevelopmentWitness.Package expected,DevelopmentWitness.Renderer renderer,DevelopmentWitness.Artifact kw,
            DevelopmentWitness.Artifact tw,Budget budget,Cancellation cancel)throws CaptureFailure{
        try{return captureAt(context.getNoBackupFilesDir().toPath().resolve("captured-candidates"),pkg,kiosk,tv,expected,renderer,kw,tw,budget,cancel,PLATFORM);}
        catch(CaptureFailure e){throw e;}
        catch(Exception e){throw new CaptureFailure(CAPTURE_FAILED);}
    }
    static CapturedCandidate captureAt(Path root,LocalView.Source pkg,LocalView.Source kiosk,LocalView.Source tv,
            DevelopmentWitness.Package expected,DevelopmentWitness.Renderer renderer,DevelopmentWitness.Artifact kw,
            DevelopmentWitness.Artifact tw,Budget budget,Cancellation cancel,Hooks hooks)throws CaptureFailure{
        Path owned=null;
        try{
            if(budget==null||cancel==null||budget.maxBytes()<0||budget.maxFiles()<0||budget.minFreeBytes()<0)throw new CaptureFailure(INVALID_BUDGET);
            cancel.check();
            Map<Part,Map<String,DevelopmentWitness.Pin>> pins=Map.of(Part.PACKAGE,expected.files(),Part.KIOSK,kw.files(),Part.TV,tw.files());
            Map<Part,LocalView.Source> sources=Map.of(Part.PACKAGE,pkg,Part.KIOSK,kiosk,Part.TV,tv);
            Map<Part,PinnedSource> checked=new EnumMap<>(Part.class);
            long bytes=0;int files=0;
            for(Part part:Part.values()){
                checked.put(part,pinned(sources.get(part),pins.get(part),part));
                for(var pin:pins.get(part).values()){
                    if(files==budget.maxFiles()||pin.size()>budget.maxBytes()-bytes)throw new CaptureFailure(BUDGET_EXCEEDED);
                    files++;bytes+=pin.size();
                }
                checked.get(part).inventory();
            }
            Files.createDirectories(root);if(Files.isSymbolicLink(root))throw new CaptureFailure(CAPTURE_FAILED);
            space(root,bytes,budget,hooks);owned=Files.createTempDirectory(root,"session-");hooks.at("created",owned);cancel.check();
            for(Part p:Part.values())Files.createDirectory(owned.resolve(p.name()));
            copy(checked.get(Part.PACKAGE),owned.resolve("PACKAGE"),"manifest.json",pins.get(Part.PACKAGE).get("manifest.json"),budget,cancel,hooks,owned);
            LocalView.Source capturedPackage=CaptureFiles.source(owned.resolve("PACKAGE"),pins.get(Part.PACKAGE),cancel::check);
            EventsPackage.inspectManifestCompatibility(capturedPackage);hooks.at("manifest",owned);cancel.check();
            for(Part part:Part.values()){
                for(var entry:new TreeMap<>(pins.get(part)).entrySet()){
                    if(part==Part.PACKAGE&&entry.getKey().equals("manifest.json"))continue;
                    copy(checked.get(part),owned.resolve(part.name()),entry.getKey(),entry.getValue(),budget,cancel,hooks,owned);
                }
                checked.get(part).inventory();
            }
            cancel.check();hooks.at("before_binding",owned);
            final Path capturedRoot=owned;
            Runnable bindingCheck=()->{
                cancel.check();
                try{hooks.at("binding_read",capturedRoot);}catch(IOException e){throw new UncheckedIOException(e);}
            };
            PublicationBinding.Report bound;
            try{bound=PublicationBinding.inspect(CaptureFiles.source(owned.resolve("PACKAGE"),pins.get(Part.PACKAGE),bindingCheck),
                CaptureFiles.source(owned.resolve("KIOSK"),pins.get(Part.KIOSK),bindingCheck),
                CaptureFiles.source(owned.resolve("TV"),pins.get(Part.TV),bindingCheck),expected,renderer,kw,tw);}
            catch(Exception e){throw new CaptureFailure(BINDING_FAILED);}
            hooks.at("bound",owned);cancel.check();
            return new CapturedCandidate(owned,pins,bound);
        }catch(Exception e){
            CaptureFailure.Code code=cancel!=null&&cancel.cancelled.get()?CANCELLED:e instanceof CaptureFailure?((CaptureFailure)e).code:CAPTURE_FAILED;
            if(owned!=null)try{CaptureFiles.deleteOwned(owned);}catch(Exception cleanup){code=CLEANUP_FAILED;}
            throw new CaptureFailure(code);
        }
    }
    private static PinnedSource pinned(LocalView.Source source,Map<String,DevelopmentWitness.Pin> pins,Part part)throws BindingFailure{
        return part==Part.PACKAGE?new PinnedSource(source,pins,"manifest.json",2L*1024*1024,256L*1024*1024,64L*1024*1024):
            new PinnedSource(source,pins,"view.json",LocalView.DESCRIPTOR_LIMIT,LocalView.FILE_LIMIT,LocalView.TOTAL_LIMIT);
    }
    private static void space(Path root,long bytes,Budget budget,Hooks hooks)throws CaptureFailure{
        long available=hooks.usable(root);
        if(available<budget.minFreeBytes()||bytes>available-budget.minFreeBytes())throw new CaptureFailure(INSUFFICIENT_SPACE);
    }
    private static void copy(PinnedSource source,Path root,String path,DevelopmentWitness.Pin pin,Budget budget,
                             Cancellation cancel,Hooks hooks,Path owned)throws Exception{
        cancel.check();hooks.at("before_file",owned);space(owned,pin.size(),budget,hooks);
        Path dest=CaptureFiles.resolve(root,path);Files.createDirectories(dest.getParent());
        try(InputStream in=source.open(path);OutputStream out=Files.newOutputStream(dest,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE)){
            byte[] block=new byte[16384];int n;
            while((n=in.read(block))!=-1){cancel.check();hooks.at("chunk",owned);out.write(block,0,n);}
        }
        hooks.at("file",owned);cancel.check();
    }
    private void alive()throws CaptureFailure{if(closed)throw new CaptureFailure(CLOSED);}
    public synchronized PublicationBinding.Report report()throws CaptureFailure{alive();return report;}
    public synchronized Set<ScopedGuarantee> scopedGuarantees()throws CaptureFailure{alive();return Set.of(ScopedGuarantee.values());}
    public synchronized LocalView.Source source(Part part)throws CaptureFailure{
        alive();if(part==null)throw new CaptureFailure(CAPTURE_FAILED);
        return new LocalView.Source(){
            @Override public Set<String> files()throws IOException{synchronized(CapturedCandidate.this){alive();return pins.get(part).keySet();}}
            @Override public InputStream open(String path)throws IOException{return openVerified(part,path);}
        };
    }
    private synchronized InputStream openVerified(Part part,String path)throws IOException{
        alive();FileInputStream raw=null;
        try{
            if(part==null||!pins.get(part).containsKey(path))throw new IOException();
            Path file=CaptureFiles.resolve(owned.resolve(part.name()),path);
            if(!Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS))throw new IOException();
            raw=new FileInputStream(file.toFile());final FileInputStream retained=raw;
            // Verify the full file BEFORE exposing bytes; retain/rewind the same read-only descriptor.
            LocalView.Source one=new LocalView.Source(){
                public Set<String> files(){return pins.get(part).keySet();}
                public InputStream open(String name){return new FilterInputStream(retained){@Override public void close(){}};}
            };
            pinned(one,pins.get(part),part).verifyFile(path);raw.getChannel().position(0);
            InputStream handle=new InputStream(){boolean done;
                @Override public int read()throws IOException{synchronized(CapturedCandidate.this){alive();if(done)throw new CaptureFailure(CLOSED);return retained.read();}}
                @Override public int read(byte[] b,int off,int len)throws IOException{synchronized(CapturedCandidate.this){alive();if(done)throw new CaptureFailure(CLOSED);return retained.read(b,off,len);}}
                @Override public void close()throws IOException{synchronized(CapturedCandidate.this){if(!done){done=true;opened.remove(this);retained.close();}}}
            };
            opened.add(handle);return handle;
        }catch(Exception e){if(raw!=null)try{raw.close();}catch(Exception ignored){}throw new CaptureFailure(CORRUPT_CAPTURE);}
    }
    @Override public synchronized void close()throws CaptureFailure{
        if(closed)return;
        closed=true;boolean failed=false;
        for(InputStream stream:List.copyOf(opened))try{stream.close();}catch(Exception e){failed=true;}
        try{CaptureFiles.deleteOwned(owned);}catch(Exception e){failed=true;}
        if(ownership!=null)try{ownership.close();}catch(Exception e){failed=true;}finally{ownership=null;}
        if(failed)throw new CaptureFailure(CLEANUP_FAILED);
    }
}
