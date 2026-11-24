package org.kiosk.harness.binding;
import java.nio.file.*;
import java.util.*;
import org.junit.Test;
public class PublicationBindingTest {
    private Map<String,byte[]> load()throws Exception{
        Path root=Path.of(System.getProperty("bindingFixtureRoot"));Map<String,byte[]> all=new HashMap<>();
        try(var walk=Files.walk(root)){for(Path p:walk.filter(Files::isRegularFile).toList())all.put(root.relativize(p).toString().replace('\\','/'),Files.readAllBytes(p));}return all;
    }
    @Test public void canonicalCOutsideCatalog()throws Exception{BindingVectors.valid(this::load);}
    @Test public void independentWitnessMismatches()throws Exception{BindingVectors.witnesses(this::load);}
    @Test public void inventoryDescriptorAndPayloadTampering()throws Exception{BindingVectors.inventoryAndTampering(this::load);}
    @Test public void boundedStreamsAndClosure()throws Exception{BindingVectors.streams(this::load);}
    @Test public void changedRereads()throws Exception{BindingVectors.changedReread(this::load);}
    @Test public void lifetimeAndNoWrites()throws Exception{BindingVectors.lifetimeAndNoWrites(this::load);}
}
