package org.kiosk.harness.binding;
import java.nio.file.*;
import java.util.*;
import java.io.*;
import org.junit.Test;
import static org.junit.Assert.*;
public class TvPaginationInputsTest {
    private Map<String,byte[]> load(String name)throws Exception{Path r=Path.of(System.getProperty("tvPaginationRoot"),name);Map<String,byte[]> out=new HashMap<>();try(var paths=Files.walk(r)){for(Path p:paths.filter(Files::isRegularFile).toList())out.put(r.relativize(p).toString().replace('\\','/'),Files.readAllBytes(p));}return out;}
    @Test public void sixExactPreparationsAndBothArtifacts()throws Exception{for(String name:PaginationInputs.NAMES){var all=load(name);var e=PaginationInputs.evidence(all,name);assertEquals(5,LocalPreparation.inspect(all,e).unchecked().size());assertEquals("839bb0c182822f7530e0d9c403b3ebddcfff214f871fb52c45d68a6dc68e6238",e.renderer().trustedJsSha256());}}
    @Test public void exactPinsDoNotAuthorizeChangedOrOldArtifacts()throws Exception{for(String name:PaginationInputs.NAMES){var all=load(name);var e=PaginationInputs.evidence(all,name);all.get(e.tvRoot()+"/events.js")[0]^=1;try{LocalPreparation.inspect(all,e);fail();}catch(IOException expected){}}var all=load("control");try{LocalPreparation.confirm(new ByteArrayInputStream(all.get("preparation.json")),LocalPreparation.Confirmation.CONTROL,LocalPreparation.Confirmation.CONTROL.sha256);fail();}catch(IOException expected){}}
}
