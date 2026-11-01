package org.kiosk.harness.packagecore;

import java.io.IOException;

/** Stable diagnostics; no source content, path or original exception is exposed. */
public final class PackageFailure extends IOException {
    public enum Code {
        invalid_package, unsupported_client_contract, unsupported_package_contract,
        manifest_too_large, package_too_large, integrity_failure, inventory_mismatch,
        source_changed, invalid_public_data, revision_mismatch, unsafe_path,
        unsupported_media_reference, reference_closure_failure, invalid_translation_resource,
        unsupported_css_dependency, unsupported_script_dependency,
        missing_display_template, missing_display_resource
    }
    public final Code code;
    PackageFailure(Code code) { super(code.name()); this.code = code; }
    static PackageFailure fail(Code code) { return new PackageFailure(code); }
}
