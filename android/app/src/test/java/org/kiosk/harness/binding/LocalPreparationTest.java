package org.kiosk.harness.binding;
import org.junit.Test;
import java.nio.file.*;
import java.util.*;
public class LocalPreparationTest {
    private Map<String,byte[]> load(String name)throws Exception{Path root=Path.of(System.getProperty("preparationFixtureRoot"),name);Map<String,byte[]> all=new HashMap<>();try(var paths=Files.walk(root)){for(Path p:paths.filter(Files::isRegularFile).toList())all.put(root.relativize(p).toString().replace('\\','/'),Files.readAllBytes(p));}return all;}
    @Test public void valid()throws Exception{PreparationVectors.valid(this::load);}
    @Test public void confirmations()throws Exception{PreparationVectors.confirmations(this::load);}
    @Test public void tampering()throws Exception{PreparationVectors.contentTampering(this::load);}
    @Test public void captureFailures()throws Exception{Path root=Files.createTempDirectory("preparation-capture-");try{PreparationVectors.captureFailures(root,this::load);}finally{Files.delete(root);}}
}
