package org.kiosk.harness.storage;
import org.kiosk.harness.binding.DevelopmentWitness;

/** Explicit trusted native opt-in for experimental playback, NEVER production authorization. */
public final class DevelopmentPlaybackAuthority {
    private DevelopmentPlaybackAuthority(){}
    public static final class Permit {
        public final DevelopmentWitness.Package pkg;
        public final DevelopmentWitness.Renderer renderer;
        public final DevelopmentWitness.Artifact kiosk,tv;
        private Permit(DevelopmentWitness.Package p,DevelopmentWitness.Renderer r,DevelopmentWitness.Artifact k,DevelopmentWitness.Artifact t){pkg=p;renderer=r;kiosk=k;tv=t;}
    }
    /** Native caller accepts all five unresolved admission gates for DEVELOPMENT ONLY. */
    public static Permit authorizeUnverifiedDevelopmentPlayback(DevelopmentWitness.Package p,DevelopmentWitness.Renderer r,
                                                               DevelopmentWitness.Artifact k,DevelopmentWitness.Artifact t){
        if(p==null||r==null||k==null||t==null||!p.canonicalIdentity().matches("[0-9a-f]{64}")
            ||!k.mode().equals("kiosk")||!t.mode().equals("tv")||!k.packageIdentity().equals(p.canonicalIdentity())
            ||!t.packageIdentity().equals(p.canonicalIdentity())||!k.rendererIdentity().equals(r.identity())||!t.rendererIdentity().equals(r.identity()))
            throw new IllegalArgumentException("invalid_development_authority");
        return new Permit(p,r,k,t);
    }
}
