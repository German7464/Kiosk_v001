package org.kiosk.harness.packagecore;

import org.junit.Test;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;

public class EventsPackageTest {
    private Map<String,byte[]> load(String name) throws Exception {
        Path root=Path.of(System.getProperty("packageFixtureRoot"),name);Map<String,byte[]> bytes=new LinkedHashMap<>();
        try(var paths=Files.walk(root)){
            for(Path p:paths.filter(Files::isRegularFile).sorted().toList())bytes.put(root.relativize(p).toString().replace('\\','/'),Files.readAllBytes(p));
        }
        return bytes;
    }
    @Test public void ninePc1CasesStructuralIntegrityOnly() throws Exception {PackageCoreVectors.oracle(this::load,System.out::println);}
    @Test public void manifestTypesAndEarlyUnsupportedRefusal() throws Exception {PackageCoreVectors.types(this::load,System.out::println);}
    @Test public void portableInventoryAndBounds() throws Exception {PackageCoreVectors.pathsAndLimits(this::load,System.out::println);}
    @Test public void publicSchemaAndResourceClosure() throws Exception {PackageCoreVectors.publicAndResources(this::load,System.out::println);}
    @Test public void jsonUnicodeAndUnknownTolerance() throws Exception {PackageCoreVectors.jsonAndUnicode(this::load,System.out::println);}
    @Test public void boundedStreamsMutationAndSafeErrors() throws Exception {PackageCoreVectors.streams(this::load,System.out::println);}
}
