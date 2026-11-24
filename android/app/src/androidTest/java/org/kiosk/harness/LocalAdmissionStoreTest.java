package org.kiosk.harness;
import java.io.*;
import org.kiosk.harness.binding.*;
public class LocalAdmissionStoreTest extends GenericStoreTest {
    @Override protected PlaybackInputs.Owned input(String name)throws Exception{
        var all=LocalAdmissionInputs.load(getInstrumentation().getContext(),name);var c=LocalPreparation.Confirmation.valueOf(name);
        var e=LocalPreparation.confirm(new ByteArrayInputStream(all.get("preparation.json")),c,c.sha256);
        return LocalPreparation.capture(getInstrumentation().getTargetContext(),all,e);
    }
}
