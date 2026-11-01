package org.kiosk.harness.binding;

import java.util.Map;
import java.util.Set;
import org.json.JSONObject;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.packagecore.EventsPackage;
import static org.kiosk.harness.binding.BindingFailure.Code.*;

/** Observational development binding only. No catalog, display, store or activation dependency. */
public final class PublicationBinding {
    private PublicationBinding() {}
    public enum Proven { PACKAGE_STRUCTURAL_INTEGRITY, OBSERVED_INVENTORIES_SIZES_HASHES,
        PACKAGE_MODE_REVISION_MATCH, INDEPENDENT_CALLER_WITNESS_MATCH, TRUSTED_JS_CSS_MATCH }
    public enum Unproven { CANONICAL_IDENTITY_INDEPENDENTLY_COMPUTED, HTML_DERIVATION_FROM_PACKAGE,
        RENDERER_BUILD_INDEPENDENTLY_COMPUTED, SOURCE_IMMUTABILITY, FUTURE_READS_AND_LIFETIME }
    public record ArtifactIdentity(String mode,String packageIdentity,String rendererWitnessIdentity,
                                   String rawDescriptorSha256,Map<String,DevelopmentWitness.Pin> observedInventory) {
        public ArtifactIdentity { observedInventory=Map.copyOf(observedInventory); }
    }
    public record Report(String callerAttestedCanonicalPackageIdentity,String rawManifestSha256,String revision,
                         Map<String,ArtifactIdentity> artifacts,Set<Proven> proven,
                         Set<EventsPackage.Unchecked> unchecked,Set<Unproven> unproven) {
        public Report { artifacts=Map.copyOf(artifacts);proven=Set.copyOf(proven);
            unchecked=Set.copyOf(unchecked);unproven=Set.copyOf(unproven); }
    }
    public static Report inspect(LocalView.Source packageSource,LocalView.Source kioskSource,LocalView.Source tvSource,
                                 DevelopmentWitness.Package expectedPackage,DevelopmentWitness.Renderer renderer,
                                 DevelopmentWitness.Artifact kiosk,DevelopmentWitness.Artifact tv) throws BindingFailure {
        try {
            if(expectedPackage==null || renderer==null || kiosk==null || tv==null
                || !PinnedSource.hash(expectedPackage.canonicalIdentity()) || !PinnedSource.hash(expectedPackage.rawManifestSha256())
                || !PinnedSource.hash(renderer.identity()) || !PinnedSource.hash(renderer.trustedJsSha256())
                || !PinnedSource.hash(renderer.trustedCssSha256()))throw new BindingFailure(INVALID_WITNESS);
            checkArtifact(kiosk,"kiosk",expectedPackage,renderer);checkArtifact(tv,"tv",expectedPackage,renderer);
            PinnedSource pkg=new PinnedSource(packageSource,expectedPackage.files(),"manifest.json",2L*1024*1024,256L*1024*1024,64L*1024*1024);
            if(!expectedPackage.rawManifestSha256().equals(expectedPackage.files().get("manifest.json").sha256()))
                throw new BindingFailure(WITNESS_MISMATCH);
            // No canonical JSON approximation. Canonical identity is attested separately by caller.
            pkg.inventory();pkg.verifyFile("manifest.json");
            EventsPackage.StructuralIntegrityReport structure;
            try { structure=EventsPackage.inspect(pkg); }
            catch(Exception e){throw new BindingFailure(PACKAGE_STRUCTURE);}
            pkg.verifyAll();
            ArtifactIdentity k=artifact(kioskSource,kiosk,renderer,structure.revision);
            ArtifactIdentity t=artifact(tvSource,tv,renderer,structure.revision);
            pkg.inventory();
            return new Report(expectedPackage.canonicalIdentity(),expectedPackage.rawManifestSha256(),structure.revision,
                Map.of("kiosk",k,"tv",t),Set.of(Proven.values()),structure.unchecked,Set.of(Unproven.values()));
        }catch(BindingFailure e){throw new BindingFailure(e.code);}
        catch(Exception e){throw new BindingFailure(INVALID_WITNESS);}
    }
    private static void checkArtifact(DevelopmentWitness.Artifact artifact,String mode,DevelopmentWitness.Package pkg,
                                      DevelopmentWitness.Renderer renderer) throws BindingFailure {
        if(!mode.equals(artifact.mode()) || !pkg.canonicalIdentity().equals(artifact.packageIdentity())
            || !renderer.identity().equals(artifact.rendererIdentity()))throw new BindingFailure(WITNESS_MISMATCH);
    }
    private static ArtifactIdentity artifact(LocalView.Source source,DevelopmentWitness.Artifact expected,
                                             DevelopmentWitness.Renderer renderer,String revision) throws Exception {
        PinnedSource pinned=new PinnedSource(source,expected.files(),"view.json",LocalView.DESCRIPTOR_LIMIT,LocalView.FILE_LIMIT,LocalView.TOTAL_LIMIT);
        pinned.verifyAll();
        try { LocalView.verify(pinned,expected.packageIdentity(),expected.mode(),renderer.trustedJsSha256(),renderer.trustedCssSha256()); }
        catch(Exception e){throw new BindingFailure(ARTIFACT_STRUCTURE);}
        byte[] descriptor=LocalView.readBounded(pinned.open("view.json"),LocalView.DESCRIPTOR_LIMIT);
        if(!revision.equals(new JSONObject(new String(descriptor,java.nio.charset.StandardCharsets.UTF_8)).getString("revision")))
            throw new BindingFailure(REVISION_MISMATCH);
        pinned.inventory();
        return new ArtifactIdentity(expected.mode(),expected.packageIdentity(),renderer.identity(),LocalView.digest(descriptor),expected.files());
    }
}
