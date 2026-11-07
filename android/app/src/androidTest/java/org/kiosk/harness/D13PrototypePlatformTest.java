package org.kiosk.harness;
import android.os.Bundle;
import android.test.InstrumentationTestCase;
import java.io.*;
import org.kiosk.harness.d13.*;
/** No Activity/provider/store/network access; reads test-APK assets and emits results over instrumentation. */
@SuppressWarnings("deprecation")
public class D13PrototypePlatformTest extends InstrumentationTestCase {
    private byte[] asset(String name)throws Exception {
        try(InputStream in=getInstrumentation().getContext().getAssets().open("d13-prototype/"+name);ByteArrayOutputStream out=new ByteArrayOutputStream()){
            byte[] block=new byte[4096];int n;while((n=in.read(block))!=-1){if(out.size()+n>65536)throw new IOException("fixture_bound");out.write(block,0,n);}return out.toByteArray();
        }
    }
    public void testSyntheticInteropAndEnrollmentModel()throws Exception {
        String report=StrictPrototypeJson.encode(D13Checks.run(asset("vectors.json"),asset("windows-signature-results.json")));
        Bundle results=new Bundle();results.putString("d13_report",report);getInstrumentation().sendStatus(0,results);
    }
}
