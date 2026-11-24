package org.kiosk.harness.binding;
import android.content.Context;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.kiosk.harness.storage.DevelopmentPlaybackAuthority;

/** Test native caller only; never a main APK importer or identity registry. */
public final class PlaybackInputs {
    public record Owned(CapturedCandidate capture,DevelopmentPlaybackAuthority.Permit permit,String identity,AtomicInteger providerReads){}
    public static Owned capture(Context context,BindingVectors.Loader loader)throws Exception{
        BindingVectors.Data d=new BindingVectors.Data(loader);AtomicInteger reads=new AtomicInteger();
        var permit=DevelopmentPlaybackAuthority.authorizeUnverifiedDevelopmentPlayback(d.pkg,d.renderer,d.kiosk,d.tv);
        var p=count(d.p,reads);var k=count(d.k,reads);var t=count(d.t,reads);
        var captured=CapturedCandidate.capture(context,p,k,t,d.pkg,d.renderer,d.kiosk,d.tv,new CapturedCandidate.Budget(8L*1024*1024,100,1024),new CapturedCandidate.Cancellation());
        d.closed();d.p.files.clear();d.k.files.clear();d.t.files.clear();
        return new Owned(captured,permit,d.pkg.canonicalIdentity(),reads);
    }
    private static org.kiosk.harness.core.LocalView.Source count(org.kiosk.harness.core.LocalView.Source source,AtomicInteger reads){return new org.kiosk.harness.core.LocalView.Source(){
        public java.io.InputStream open(String name)throws java.io.IOException{reads.incrementAndGet();return source.open(name);}
        public Set<String> files()throws java.io.IOException{reads.incrementAndGet();return source.files();}
    };}
}
