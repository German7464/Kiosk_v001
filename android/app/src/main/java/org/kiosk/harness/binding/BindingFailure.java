package org.kiosk.harness.binding;

import java.io.IOException;

/** Stable codes only: no payload, source exception or private path escapes this boundary. */
public final class BindingFailure extends IOException {
    public enum Code { INVALID_WITNESS, WITNESS_MISMATCH, INVENTORY_MISMATCH, STREAM_INTEGRITY,
        SOURCE_IO, PACKAGE_STRUCTURE, ARTIFACT_STRUCTURE, REVISION_MISMATCH }
    public final Code code;
    BindingFailure(Code code) { super(code.name()); this.code=code; }
}
