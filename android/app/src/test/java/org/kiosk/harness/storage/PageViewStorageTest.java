package org.kiosk.harness.storage;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.kiosk.harness.core.LocalView;
import static org.junit.Assert.*;

public class PageViewStorageTest {
    private static final String PACKAGE="a".repeat(64),REVISION="b".repeat(64);
    private static final byte[] JS="trusted page renderer".getBytes(StandardCharsets.UTF_8);
    private static final byte[] CSS="trusted page styles".getBytes(StandardCharsets.UTF_8);
    private static final String JS_SHA=LocalView.digest(JS),CSS_SHA=LocalView.digest(CSS);
    private static final class Source implements LocalView.Source {
        private final Map<String,byte[]> files;
        Source(Map<String,byte[]> files){this.files=Map.copyOf(files);}
        public InputStream open(String path)throws IOException{
            byte[] value=files.get(path);if(value==null)throw new IOException("missing");
            return new ByteArrayInputStream(value);
        }
        public Set<String> files(){return files.keySet();}
    }
    private static byte[] descriptor(Map<String,byte[]> files)throws Exception{
        JSONArray rows=new JSONArray();
        for(Map.Entry<String,byte[]> entry:new TreeMap<>(files).entrySet())
            rows.put(new JSONObject().put("path",entry.getKey()).put("size",entry.getValue().length)
                .put("sha256",LocalView.digest(entry.getValue())));
        return new JSONObject().put("schema_version",2).put("kind","pages")
            .put("renderer","pages-v1").put("revision",REVISION).put("package_sha256",PACKAGE)
            .put("mode","tv").put("files",rows).toString().getBytes(StandardCharsets.UTF_8);
    }
    private static Map<String,byte[]> view()throws Exception{
        Map<String,byte[]> files=new TreeMap<>();
        files.put("index.html","<!doctype html><main></main>".getBytes(StandardCharsets.UTF_8));
        files.put("bootstrap.js","bootstrap".getBytes(StandardCharsets.UTF_8));
        files.put("page_display.js",JS);files.put("page_display.css",CSS);
        files.put("static/uploads/card.png","synthetic-image".getBytes(StandardCharsets.UTF_8));
        files.put("view.json",descriptor(files));
        return files;
    }

    @Test public void onlyFixedShippedViewFilesAreAccepted()throws Exception{
        Source source=new Source(view());
        LocalView result=LocalView.verifyPage(source,PACKAGE,"tv",JS_SHA,CSS_SHA);
        assertEquals("tv",result.mode);
        assertEquals(PACKAGE,result.packageIdentity);

        Map<String,byte[]> executable=new TreeMap<>(view());
        executable.put("evil.js","alert(1)".getBytes(StandardCharsets.UTF_8));
        try{LocalView.verifyPage(new Source(executable),PACKAGE,"tv",JS_SHA,CSS_SHA);fail("accepted executable view file");}
        catch(IOException expected){}

        try{LocalView.verifyPage(source,PACKAGE,"tv","9".repeat(64),CSS_SHA);fail("accepted unpinned renderer");}
        catch(IOException expected){}
    }
}
