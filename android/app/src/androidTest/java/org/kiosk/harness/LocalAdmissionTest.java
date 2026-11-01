package org.kiosk.harness;
import java.util.*;
import java.io.*;
import org.kiosk.harness.binding.*;
/** Inherits actual kiosk/TV/replacement/render failure/late callback scenarios using pinned PC1 preparations. */
public class LocalAdmissionTest extends GenericPlaybackTest {
    @Override PlaybackInputs.Owned inputs(String name)throws Exception{
        Map<String,byte[]> all=LocalAdmissionInputs.load(getInstrumentation().getContext(),name);
        var confirmation=LocalPreparation.Confirmation.valueOf(name);
        var e=LocalPreparation.confirm(new ByteArrayInputStream(all.get("preparation.json")),confirmation,confirmation.sha256);
        return LocalPreparation.capture(getInstrumentation().getTargetContext(),all,e);
    }
}
