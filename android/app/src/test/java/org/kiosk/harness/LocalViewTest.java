package org.kiosk.harness;

import org.junit.Test;
import org.json.JSONObject;
import org.json.JSONArray;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.core.OriginPolicy;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;
import static org.junit.Assert.*;

public class LocalViewTest {
    static final class MemorySource implements LocalView.Source {
        final Map<String, byte[]> data = new HashMap<>();
        MemorySource(String name) throws Exception {
            Path root = Path.of(System.getProperty("fixtureRoot"), name);
            try (var paths = Files.walk(root)) {
                for (Path p : paths.filter(Files::isRegularFile).toList())
                    data.put(root.relativize(p).toString().replace('\\', '/'), Files.readAllBytes(p));
            }
        }
        public InputStream open(String name) throws IOException {
            if (!data.containsKey(name)) throw new IOException("missing");
            return new ByteArrayInputStream(data.get(name));
        }
        public Set<String> files() { return data.keySet(); }
        JSONObject descriptor() throws Exception { return new JSONObject(new String(data.get("view.json"), StandardCharsets.UTF_8)); }
        void descriptor(JSONObject value) { data.put("view.json", value.toString().getBytes(StandardCharsets.UTF_8)); }
    }
    private MemorySource source() throws Exception { return new MemorySource("valid-kiosk"); }
    private LocalView verify(MemorySource s) throws Exception {
        return LocalView.verify(s, FixtureCatalog.identity("valid-kiosk"), "kiosk", FixtureCatalog.JS, FixtureCatalog.CSS);
    }
    private void refused(MemorySource s) throws Exception {
        IOException e = assertThrows(IOException.class, () -> verify(s));
        assertEquals("invalid_local_view", e.getMessage());
    }
    @Test public void allFourViewsAndEmptyState() throws Exception {
        for (String name : FixtureCatalog.NAMES) {
            LocalView v = LocalView.verify(new MemorySource(name), FixtureCatalog.identity(name), FixtureCatalog.mode(name), FixtureCatalog.JS, FixtureCatalog.CSS);
            assertTrue(v.read("index.html").length > 0);
            assertEquals(FixtureCatalog.JS, LocalView.digest(v.read("events.js")));
        }
    }
    @Test public void damagedDescriptor() throws Exception { MemorySource s=source();s.data.put("view.json",new byte[]{'{'});refused(s); }
    @Test public void descriptorByteLimit() throws Exception { MemorySource s=source();s.data.put("view.json",new byte[LocalView.DESCRIPTOR_LIMIT+1]);refused(s); }
    @Test public void malformedUtf8() throws Exception { MemorySource s=source();s.data.put("view.json",new byte[]{(byte)0xff});refused(s); }
    @Test public void rejectLenientAndroidJsonForms() throws Exception {
        for (String text : new String[]{"{} trailing", "{/*comment*/}", "{'a':1}", "{\"a\":1,}", "{\"a\":01}", "{\"a\":1.}", "{\"a\":NaN}"}) {
            MemorySource s=source();s.data.put("view.json",text.getBytes(StandardCharsets.UTF_8));refused(s);
        }
    }
    @Test public void depthLimit() throws Exception {
        MemorySource s=source(); JSONObject d=s.descriptor();d.put("unknown",new JSONArray("[".repeat(33)+"0"+"]".repeat(33)));s.descriptor(d);refused(s);
    }
    @Test public void expectedIdentityAndMode() throws Exception {
        MemorySource s=source();JSONObject d=s.descriptor();d.put("package_sha256","0".repeat(64));s.descriptor(d);refused(s);
        s=source();d=s.descriptor();d.put("mode","tv");s.descriptor(d);refused(s);
    }
    @Test public void schemaRendererRevision() throws Exception {
        for (Object schema : new Object[]{true,1.5,2,"1"}) { MemorySource s=source();JSONObject d=s.descriptor();d.put("schema_version",schema);s.descriptor(d);refused(s); }
        MemorySource s=source();JSONObject d=s.descriptor();d.put("renderer","events-v2");s.descriptor(d);refused(s);
        s=source();d=s.descriptor();d.put("revision","");s.descriptor(d);refused(s);
    }
    @Test public void preserveUnknownDescriptorProperties() throws Exception {
        MemorySource s=source();JSONObject d=s.descriptor();d.put("future",true);s.descriptor(d);verify(s);
    }
    @Test public void exactEntryKeys() throws Exception { MemorySource s=source();JSONObject d=s.descriptor();d.getJSONArray("files").getJSONObject(0).put("extra",1);s.descriptor(d);refused(s); }
    @Test public void missingFile() throws Exception { MemorySource s=source();s.data.remove("events.css");refused(s); }
    @Test public void extraFile() throws Exception { MemorySource s=source();s.data.put("extra.png",new byte[0]);refused(s); }
    @Test public void byteTamperAndSize() throws Exception {
        MemorySource s=source();s.data.get("events.js")[0]^=1;refused(s);
        s=source();s.data.put("events.css",new byte[0]);refused(s);
    }
    @Test public void rehashedUntrustedAssets() throws Exception {
        for (String name : new String[]{"events.js","events.css"}) {
            MemorySource s=source();s.data.get(name)[0]^=1;JSONObject d=s.descriptor();JSONArray f=d.getJSONArray("files");
            for(int i=0;i<f.length();i++) if(f.getJSONObject(i).getString("path").equals(name)) f.getJSONObject(i).put("sha256",LocalView.digest(s.data.get(name)));
            s.descriptor(d);refused(s);
        }
    }
    @Test public void unsafePathVectors() throws Exception {
        for(String path:new String[]{"/a.png","../a.png","a//b.png","a/./b.png","a\\b.png","a:b.png","a./b.png","a /b.png",""}) {
            assertFalse(path,LocalView.safePath(path));
            MemorySource s=source();JSONObject d=s.descriptor();d.getJSONArray("files").getJSONObject(0).put("path",path);s.descriptor(d);refused(s);
        }
    }
    @Test public void disallowedMimeAndCaseCollision() throws Exception {
        MemorySource s=source();JSONObject d=s.descriptor();JSONArray f=d.getJSONArray("files");f.put(new JSONObject().put("path","static/uploads/file.js").put("size",0).put("sha256","0".repeat(64)));s.descriptor(d);refused(s);
        s=source();d=s.descriptor();f=d.getJSONArray("files");f.put(new JSONObject(f.getJSONObject(3).toString()).put("path","static/uploads/CARD.PNG"));s.descriptor(d);refused(s);
    }
    @Test public void countLimits() throws Exception {
        MemorySource s=source();JSONObject d=s.descriptor();JSONArray f=d.getJSONArray("files");f.remove(0);f.remove(0);s.descriptor(d);refused(s);
        s=source();d=s.descriptor();f=d.getJSONArray("files");while(f.length()<=10000)f.put(new JSONObject());s.descriptor(d);refused(s);
    }
    @Test public void sizeAndHashSyntax() throws Exception {
        for(Object size:new Object[]{-1,LocalView.FILE_LIMIT+1,true,"1",1.5}) {
            MemorySource s=source();JSONObject d=s.descriptor();d.getJSONArray("files").getJSONObject(0).put("size",size);s.descriptor(d);refused(s);
        }
        MemorySource s=source();JSONObject d=s.descriptor();d.getJSONArray("files").getJSONObject(0).put("sha256",FixtureCatalog.CSS.toUpperCase());s.descriptor(d);refused(s);
    }
    @Test public void totalLimitBeforeReads() throws Exception {
        MemorySource s=source();JSONObject d=s.descriptor();JSONArray f=d.getJSONArray("files");for(int i=0;i<3;i++)f.getJSONObject(i).put("size",LocalView.FILE_LIMIT);s.descriptor(d);refused(s);
    }
    @Test public void mutationAfterVerification() throws Exception {
        MemorySource s=source();LocalView v=verify(s);s.data.get("events.js")[0]^=1;assertThrows(IOException.class,()->v.read("events.js"));
    }
    @Test public void originAndMethodPolicy() throws Exception {
        OriginPolicy p=new OriginPolicy(verify(source()));
        assertEquals("index.html",p.resource(OriginPolicy.INDEX,"GET"));
        assertEquals("events.js",p.resource(OriginPolicy.ORIGIN+"/events.js","GET"));
        for(String url:new String[]{"https://example.com/index.html","http://kiosk.invalid/index.html","file:///index.html","content://local/index.html","intent://local",OriginPolicy.ORIGIN+"/view.json",OriginPolicy.INDEX+"?x=1",OriginPolicy.INDEX+"#x",OriginPolicy.ORIGIN+":444/index.html","https://u@kiosk.invalid/index.html",OriginPolicy.ORIGIN+"/%2e%2e/index.html",OriginPolicy.ORIGIN+"/static%2fuploads/card.png",OriginPolicy.ORIGIN+"//index.html"}) assertNull(url,p.resource(url,"GET"));
        assertNull(p.resource(OriginPolicy.INDEX,"POST"));
        assertFalse(p.navigate(OriginPolicy.INDEX,"GET",false));
        assertFalse(p.navigate(OriginPolicy.ORIGIN+"/events.js","GET",true));
    }
}
