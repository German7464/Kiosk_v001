package org.kiosk.harness.binding;
import android.content.Context;
import java.io.*;
import java.nio.file.*;
import java.util.*;
public final class FitnessInputs {
    public static final List<String> NAMES=List.of("empty","control","long-text-tags","image-shapes");
    public static LocalPreparation.Confirmation confirmation(String name){if(!NAMES.contains(name))throw new IllegalArgumentException();return LocalPreparation.Confirmation.valueOf(name.toUpperCase(java.util.Locale.ROOT).replace('-','_'));}
    public static LocalPreparation.Evidence evidence(Map<String,byte[]> all,String name)throws Exception{var c=confirmation(name);return LocalPreparation.confirm(new ByteArrayInputStream(all.get("preparation.json")),c,c.sha256);}
    public static PlaybackInputs.Owned capture(Context context,Map<String,byte[]> all,String name)throws Exception{return LocalPreparation.capture(context,all,evidence(all,name));}
    public static void cancelledCapture(Path root,Map<String,byte[]> all,String name)throws Exception{
        var e=evidence(all,name);var p=LocalPreparation.source(all,e.packageRoot(),e.pkg().files());var k=LocalPreparation.source(all,e.kioskRoot(),e.kiosk().files());var t=LocalPreparation.source(all,e.tvRoot(),e.tv().files());var cancel=new CapturedCandidate.Cancellation();
        try(var unexpected=CapturedCandidate.captureAt(root,p,k,t,e.pkg(),e.renderer(),e.kiosk(),e.tv(),new CapturedCandidate.Budget(8L*1024*1024,100,1024),cancel,new CapturedCandidate.Hooks(){public void at(String phase,Path path){if(phase.equals("chunk"))cancel.cancel();}})){throw new AssertionError("cancelled candidate accepted");}
        catch(CaptureFailure failure){if(failure.code!=CaptureFailure.Code.CANCELLED)throw failure;}
        if(p.opened!=p.closed||k.opened!=k.closed||t.opened!=t.closed)throw new AssertionError("unclosed provider");
        try(var files=Files.list(root)){if(files.count()!=0)throw new AssertionError("capture residue");}
    }
}
