package org.kiosk.harness.binding;
import java.io.IOException;
public final class CaptureFailure extends IOException {
    public enum Code { INVALID_BUDGET, BUDGET_EXCEEDED, INSUFFICIENT_SPACE, CANCELLED, CAPTURE_FAILED,
        BINDING_FAILED, CLOSED, CORRUPT_CAPTURE, CLEANUP_FAILED }
    public final Code code;
    CaptureFailure(Code code){super(code.name());this.code=code;}
}
