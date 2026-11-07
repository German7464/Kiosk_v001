package org.kiosk.harness.storage;
import org.kiosk.harness.binding.CapturedCandidate;
/** Test APK only: demonstrates why decoder acceptance must not override negative Windows evidence. */
public final class LocalImageProbe {
    public static void decodeCaptured(CapturedCandidate capture,PreparedAdmission.Request r)throws Exception {
        decodeCaptured(capture,r,FixturePublicationStore.NONE);
    }
    public static void decodeCaptured(CapturedCandidate capture,PreparedAdmission.Request r,FixturePublicationStore.Checkpoint cancel)throws Exception {AndroidImageValidation.verify(capture.source(CapturedCandidate.Part.PACKAGE),r,r.windowsImages().keySet(),cancel);}
}
