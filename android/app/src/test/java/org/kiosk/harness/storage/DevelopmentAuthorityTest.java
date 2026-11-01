package org.kiosk.harness.storage;
import org.junit.Test;
import static org.junit.Assert.*;
import java.util.*;
import org.json.JSONObject;
import org.kiosk.harness.binding.DevelopmentWitness;
public class DevelopmentAuthorityTest {
    @Test public void explicitAuthoritySeparatesRawAndCanonicalAndStablePins()throws Exception{
        String id="1".repeat(64),raw="2".repeat(64),build="3".repeat(64);
        var files=Map.of("manifest.json",new DevelopmentWitness.Pin(1,raw));
        var p=new DevelopmentWitness.Package(id,raw,files);var r=new DevelopmentWitness.Renderer(build,raw,raw);
        var a=new DevelopmentGrant(DevelopmentPlaybackAuthority.authorizeUnverifiedDevelopmentPlayback(p,r,new DevelopmentWitness.Artifact("kiosk",id,build,files),new DevelopmentWitness.Artifact("tv",id,build,files)));
        var j=new JSONObject(a.encode());assertEquals(id,j.getString("identity"));assertEquals(raw,j.getString("raw_manifest"));assertEquals(a.fingerprint(),j.getString("witness_fingerprint"));
        assertEquals("native_unverified_development_only",j.getString("authority"));
    }
    @Test public void mismatchedNativeAuthorityRejected(){
        String id="1".repeat(64),h="2".repeat(64);var files=Map.of("manifest.json",new DevelopmentWitness.Pin(1,h));
        try{DevelopmentPlaybackAuthority.authorizeUnverifiedDevelopmentPlayback(new DevelopmentWitness.Package(id,h,files),new DevelopmentWitness.Renderer(h,h,h),new DevelopmentWitness.Artifact("kiosk",h,h,files),new DevelopmentWitness.Artifact("tv",id,h,files));fail();}catch(IllegalArgumentException expected){assertEquals("invalid_development_authority",expected.getMessage());}
    }
}
