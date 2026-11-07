package org.kiosk.harness.delivery;

import java.io.InputStream;
import org.json.JSONObject;
import org.kiosk.harness.binding.CapturedCandidate;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.storage.PreparedAdmission;

/** Package-private constructor seams; ordinary startup always supplies platform implementations. */
final class DeliveryIO {
    interface Store {JSONObject read()throws Exception;void write(JSONObject value)throws Exception;}
    interface Wire {
        NativeTransport.Response call(String path,String secret,byte[] body,int cap,String pin)throws Exception;
        InputStream artifact(String path,String secret,long size,String pin)throws java.io.IOException;
        default org.kiosk.harness.binding.ResumableCapture.Reply rangeArtifact(String path,String secret,long size,String sha256,long offset,String pin)throws Exception{throw new java.io.IOException("range_transport_required");}
    }
    interface Wires {Wire create(DeliveryProtocol.Bootstrap b)throws Exception;}
    interface Clock {long now();long elapsed();int boot();boolean automatic();}
    interface Capture {CapturedCandidate create(PreparedAdmission.Request r,LocalView.Source pkg,LocalView.Source kiosk,LocalView.Source tv)throws Exception;}
}
