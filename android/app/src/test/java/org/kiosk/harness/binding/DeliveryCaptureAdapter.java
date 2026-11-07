package org.kiosk.harness.binding;

import java.nio.file.Path;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.storage.PreparedAdmission;

/** Test APK/JVM only: exercises the existing real capture algorithm with bounded transport adapters. */
public final class DeliveryCaptureAdapter {
    public static CapturedCandidate capture(Path owned,PreparedAdmission.Request r,LocalView.Source p,LocalView.Source k,LocalView.Source t)throws Exception {
        return CapturedCandidate.captureAt(owned,p,k,t,r.pkg(),r.renderer(),r.kiosk(),r.tv(),r.storage(),new CapturedCandidate.Cancellation(),new CapturedCandidate.Hooks(){});
    }
}
