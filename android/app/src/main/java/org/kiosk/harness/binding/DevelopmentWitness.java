package org.kiosk.harness.binding;

import java.util.Map;

/** Independent native-caller expectations, not a serialized protocol or source authentication. */
public final class DevelopmentWitness {
    private DevelopmentWitness() {}
    public record Pin(long size, String sha256) {}
    public record Package(String canonicalIdentity, String rawManifestSha256, Map<String,Pin> files) {
        public Package { files=Map.copyOf(files); }
    }
    public record Renderer(String identity, String trustedJsSha256, String trustedCssSha256) {}
    public record Artifact(String mode, String packageIdentity, String rendererIdentity, Map<String,Pin> files) {
        public Artifact { files=Map.copyOf(files); }
    }
}
