package org.kiosk.harness.packagecore;

import java.math.BigInteger;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import org.kiosk.harness.core.LocalView;
import static org.kiosk.harness.packagecore.PackageFailure.Code.*;
import static org.kiosk.harness.packagecore.PackageJson.*;

/** Non-activating structural/integrity inspection of logical streams, never package admission. */
public final class EventsPackage {
    private EventsPackage() {}
    public enum Unchecked { IMAGE_VALIDATION, ANDROID_DECODER_PARITY, FILESYSTEM_SAFETY, SOURCE_TRUST, ACTIVATION_READINESS }
    public static final class StructuralIntegrityReport {
        public final String revision;
        public final int fileCount;
        public final Set<Unchecked> unchecked=Set.of(Unchecked.values());
        private StructuralIntegrityReport(String revision,int fileCount){this.revision=revision;this.fileCount=fileCount;}
    }
    public static StructuralIntegrityReport inspect(LocalView.Source source) throws PackageFailure {
        try {
            Manifest parsed=manifest(source);
            Map<String,Object> manifest=parsed.data();
            Map<String,PackageInventory.Entry> inventory=parsed.inventory();
            PackageInventory.treeAndTotal(source,inventory);
            Map<String,byte[]> payloads=new LinkedHashMap<>();
            for(var entry:inventory.entrySet()){
                PackageInventory.payload(source,entry.getKey(),entry.getValue(),false,false);
                if(entry.getKey().equals("data/events.json")||entry.getKey().startsWith("resources/"))
                    payloads.put(entry.getKey(),PackageInventory.payload(source,entry.getKey(),entry.getValue(),true,true));
            }
            Map<String,Object> data=object(PackageJson.parse(payloads.get("data/events.json")),invalid_public_data);
            if(!PackageSchema.data(data).toString().equals(manifest.get("revision")))throw PackageFailure.fail(revision_mismatch);
            PackageResources.closure(inventory.keySet(),PackageResources.references(data));
            PackageResources.check(payloads);
            return new StructuralIntegrityReport((String)manifest.get("revision"),inventory.size());
        } catch(PackageFailure e){throw PackageFailure.fail(e.code);}
        catch(Exception e){throw PackageFailure.fail(invalid_package);}
    }
    /** Manifest-only early compatibility gate; not payload inspection or admission. */
    public static void inspectManifestCompatibility(LocalView.Source source) throws PackageFailure {
        try {
            manifest(source);
        }catch(PackageFailure e){throw PackageFailure.fail(e.code);}
        catch(Exception e){throw PackageFailure.fail(invalid_package);}
    }
    private record Manifest(Map<String,Object> data,Map<String,PackageInventory.Entry> inventory){}
    private static Manifest manifest(LocalView.Source source)throws Exception{
        Map<String,Object> manifest=object(PackageJson.parse(PackageInventory.manifest(source)),invalid_package);
        PackageSchema.manifest(manifest);
        Map<String,PackageInventory.Entry> inventory=PackageInventory.parse(manifest.get("files"));
        if(!"events".equals(manifest.get("kind"))||!BigInteger.ONE.equals(manifest.get("resource_contract")))
            throw PackageFailure.fail(unsupported_client_contract);
        if(!java.util.List.of("data/events.json").equals(manifest.get("entrypoints")))throw PackageFailure.fail(unsupported_package_contract);
        return new Manifest(manifest,inventory);
    }
}
