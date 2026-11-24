package org.kiosk.harness.binding;
import org.junit.Test;
import java.nio.file.*;
import java.util.*;
import java.io.*;
import static org.junit.Assert.*;
public class ContentFitnessInputsTest {
    private Map<String,byte[]> load(String name)throws Exception{Path root=Path.of(System.getProperty("contentFitnessRoot"),name);Map<String,byte[]> out=new HashMap<>();try(var files=Files.walk(root)){for(Path p:files.filter(Files::isRegularFile).toList())out.put(root.relativize(p).toString().replace('\\','/'),Files.readAllBytes(p));}return out;}
    @Test public void allFourIndependentPreparationsBind()throws Exception{for(String name:FitnessInputs.NAMES){var all=load(name);var e=FitnessInputs.evidence(all,name);assertEquals(5,LocalPreparation.inspect(all,e).unchecked().size());}}
    @Test public void changedCandidateAndCancellationRefuse()throws Exception{for(String name:FitnessInputs.NAMES){var all=load(name);var e=FitnessInputs.evidence(all,name);all.get(e.kioskRoot()+"/index.html")[0]^=1;try{LocalPreparation.inspect(all,e);fail();}catch(IOException expected){}Path root=Files.createTempDirectory("fitness-cancel-");try{FitnessInputs.cancelledCapture(root,load(name),name);}finally{Files.delete(root);}}}
}
