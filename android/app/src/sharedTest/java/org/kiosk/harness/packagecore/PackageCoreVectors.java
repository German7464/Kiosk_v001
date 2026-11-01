package org.kiosk.harness.packagecore;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.io.IOException;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Consumer;
import org.json.JSONObject;
import org.kiosk.harness.core.LocalView;

/** Same vectors on JVM and Android. No image admission claim, no UI/activation imports. */
public final class PackageCoreVectors {
    public interface Loader { Map<String,byte[]> load(String name) throws Exception; }
    public static final class Memory implements LocalView.Source {
        final Map<String,byte[]> bytes;
        final List<String> opened=new ArrayList<>();
        Memory(Map<String,byte[]> bytes){this.bytes=new LinkedHashMap<>(bytes);}
        public InputStream open(String path) throws IOException {
            opened.add(path);byte[] data=bytes.get(path);if(data==null)throw new IOException("PRIVATE_PATH_SECRET");return new ByteArrayInputStream(data);
        }
        public Set<String> files(){return bytes.keySet();}
    }
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static String inspect(Memory source) throws Exception {
        try {
            var result=EventsPackage.inspect(source);
            check(result.unchecked.size()==5,"not full admission");
            return "structural_integrity_ok";
        }catch(PackageFailure error){check(error.getCause()==null&&error.getSuppressed().length==0,"safe cause");check(error.getMessage().equals(error.code.name()),"safe code");return error.getMessage();}
    }
    public static void oracle(Loader loader,Consumer<String> log) throws Exception {
        Map<String,String> expected=Map.of("valid","ok","empty","ok","bad-public-data","invalid_public_data",
            "extra-file","inventory_mismatch","missing-resource","reference_closure_failure","revision-mismatch","revision_mismatch",
            "tampered","integrity_failure","unsafe-path","invalid_package","unsupported-contract","unsupported_client_contract");
        for(var row:expected.entrySet()){
            String actual=inspect(new Memory(loader.load(row.getKey())));
            check(actual.equals(row.getValue().equals("ok")?"structural_integrity_ok":row.getValue()),row.getKey()+":"+actual);
            log.accept("case="+row.getKey()+" pc1_oracle="+row.getValue()+" android_structural_integrity="+actual+" image_conformance=unchecked");
        }
    }
    private static Memory valid(Loader loader) throws Exception{return new Memory(loader.load("valid"));}
    private static String text(byte[] bytes){return new String(bytes,StandardCharsets.UTF_8);}
    private static void manifest(Memory source,String json){source.bytes.put("manifest.json",json.getBytes(StandardCharsets.UTF_8));}
    private static String manifest(Memory source){return text(source.bytes.get("manifest.json"));}
    private static void content(Memory source,String path,String value) throws Exception {
        byte[] bytes=value.getBytes(StandardCharsets.UTF_8);source.bytes.put(path,bytes);
        JSONObject manifest=new JSONObject(manifest(source));var rows=manifest.getJSONArray("files");
        for(int i=0;i<rows.length();i++)if(rows.getJSONObject(i).getString("path").equals(path))
            rows.getJSONObject(i).put("size",bytes.length).put("sha256",LocalView.digest(bytes));
        manifest(source,manifest.toString());
    }
    public static void types(Loader loader,Consumer<String> log) throws Exception {
        for(String field:List.of("schema_version","resource_contract"))for(String token:List.of("true","1.0","1e0","null","\"1\"","2")){
            Memory source=valid(loader);manifest(source,manifest(source).replace("\""+field+"\":1","\""+field+"\":"+token));
            String expected=field.equals("schema_version")?"invalid_package":"unsupported_client_contract";
            check(inspect(source).equals(expected),field+token);
            check(source.opened.equals(List.of("manifest.json")),"reject before data/media");
        }
        for(String revision:List.of("", "x".repeat(129))){Memory s=valid(loader);var m=new JSONObject(manifest(s));m.put("revision",revision);manifest(s,m.toString());check(inspect(s).equals("invalid_package"),"revision");}
        Memory s=valid(loader);var m=new JSONObject(manifest(s));m.put("entrypoints",List.of("data/other.json"));manifest(s,m.toString());check(inspect(s).equals("unsupported_package_contract"),"entrypoints");check(s.opened.size()==1,"early entrypoints");
        s=valid(loader);m=new JSONObject(manifest(s));m.put("kind","other");manifest(s,m.toString());check(inspect(s).equals("unsupported_client_contract"),"kind");
        s=valid(loader);m=new JSONObject(manifest(s));m.put("renderer","unknown");manifest(s,m.toString());check(inspect(s).equals("invalid_package"),"renderer Python manifest gate");
        log.accept("types/tuple/revision/entrypoints PASS");
    }
    public static void pathsAndLimits(Loader loader,Consumer<String> log) throws Exception {
        check(PackageInventory.safe("x".repeat(240))&&!PackageInventory.safe("x".repeat(241)),"path length boundary");
        check(PackageInventory.safe("😀".repeat(240))&&!PackageInventory.safe("😀".repeat(241)),"Python codepoint length");
        for(String path:List.of("/absolute","a//b","../x","a/./b","a\\b","a:b","a%2fb","a#b","a?b","a*b","a|b","a<b","a>b","a\"b","a/CON.txt","prn","AUX","nul","COM1.foo","LPT9","a.","a ","a\u001fb","x".repeat(241))){
            Memory s=valid(loader);var m=new JSONObject(manifest(s));m.getJSONArray("files").getJSONObject(0).put("path",path);manifest(s,m.toString());check(inspect(s).equals("invalid_package"),"portable path");
        }
        for(String[] pair:List.of(new String[]{"same","same"},new String[]{"A","a"},new String[]{"Straße","STRASSE"},new String[]{"Σ","ς"},new String[]{"\ufb03","FFI"},new String[]{"\ud801\udc00","\ud801\udc28"})){
            Memory s=valid(loader);var m=new JSONObject(manifest(s));var rows=m.getJSONArray("files");rows.getJSONObject(0).put("path",pair[0]);rows.getJSONObject(1).put("path",pair[1]);manifest(s,m.toString());check(inspect(s).equals("invalid_package"),"full casefold duplicate");
        }
        for(String token:List.of("-1","true","1.0","268435457","9223372036854775808")){
            Memory s=valid(loader);manifest(s,manifest(s).replaceFirst("\"size\":\\d+","\"size\":"+token));check(inspect(s).equals("invalid_package"),"size type/bound");
        }
        Memory s=valid(loader);var m=new JSONObject(manifest(s));m.getJSONArray("files").getJSONObject(0).put("size",64*1024*1024);manifest(s,m.toString());check(inspect(s).equals("package_too_large"),"total");check(s.opened.size()==1,"no large allocation");
        s=valid(loader);manifest(s," ".repeat(2*1024*1024+1));check(inspect(s).equals("manifest_too_large"),"manifest bound");
        s=valid(loader);m=new JSONObject(manifest(s));var rows=m.getJSONArray("files");Object first=rows.get(0);while(rows.length()<=10000)rows.put(first);manifest(s,m.toString());check(inspect(s).equals("invalid_package"),"count");
        s=valid(loader);s.bytes.put("extra",new byte[0]);check(inspect(s).equals("inventory_mismatch"),"extra");
        s=valid(loader);s.bytes.remove("resources/static/js/tv.js");check(inspect(s).equals("inventory_mismatch"),"missing");
        s=valid(loader);s.bytes.put("data/events.json",new byte[0]);check(inspect(s).equals("integrity_failure"),"short");
        s=valid(loader);s.bytes.get("data/events.json")[0]^=1;check(inspect(s).equals("integrity_failure"),"hash");
        s=valid(loader);s.bytes.put("data/events.json",java.util.Arrays.copyOf(s.bytes.get("data/events.json"),s.bytes.get("data/events.json").length+1));check(inspect(s).equals("integrity_failure"),"overlong stream");
        s=valid(loader);m=new JSONObject(manifest(s));m.getJSONArray("files").getJSONObject(0).put("sha256","A".repeat(64));manifest(s,m.toString());check(inspect(s).equals("invalid_package"),"digest grammar");
        log.accept("portable paths/full casefold/count/manifest/file/total/hash/tree PASS");
    }
    public static void publicAndResources(Loader loader,Consumer<String> log) throws Exception {
        for(String field:List.of("content_version","id","sort_order"))for(String token:List.of("true","1.0","null","\"1\"")){
            Memory s=valid(loader);String json=text(s.bytes.get("data/events.json")).replaceFirst("\""+field+"\":-?\\d+","\""+field+"\":"+token);
            content(s,"data/events.json",json);check(inspect(s).equals("invalid_public_data"),field+token);
        }
        for(String defect:List.of("extra","secret-setting","unknown-tag","duplicate-link","duplicate-event","duplicate-tag","missing-field","bad-title","bad-image","bad-settings","version-zero")){
            Memory s=valid(loader);JSONObject data=new JSONObject(text(s.bytes.get("data/events.json")));var event=data.getJSONArray("events").getJSONObject(0);
            switch(defect){
                case "extra":data.put("private","secret");break;
                case "secret-setting":data.getJSONObject("settings").put("secret","x");break;
                case "unknown-tag":event.getJSONArray("tag_ids").put(999);break;
                case "duplicate-link":event.getJSONArray("tag_ids").put(1);break;
                case "duplicate-event":data.getJSONArray("events").put(event);break;
                case "duplicate-tag":data.getJSONArray("tags").put(data.getJSONArray("tags").get(0));break;
                case "missing-field":event.remove("place");break;
                case "bad-title":event.put("title",JSONObject.NULL);break;
                case "bad-image":event.put("image_tv",false);break;
                case "bad-settings":data.getJSONObject("settings").put("site_title",1);break;
                case "version-zero":data.put("content_version",0);break;
            }
            content(s,"data/events.json",data.toString());check(inspect(s).equals("invalid_public_data"),defect);
        }
        for(String defect:List.of("tag-id-bool","tag-name-null","tag-extra","event-zero","links-bool")){
            Memory s=valid(loader);JSONObject data=new JSONObject(text(s.bytes.get("data/events.json")));
            var tag=data.getJSONArray("tags").getJSONObject(0);var event=data.getJSONArray("events").getJSONObject(0);
            if(defect.equals("tag-id-bool"))tag.put("id",true);
            if(defect.equals("tag-name-null"))tag.put("name",JSONObject.NULL);
            if(defect.equals("tag-extra"))tag.put("extra","x");
            if(defect.equals("event-zero"))event.put("id",0);
            if(defect.equals("links-bool"))event.put("tag_ids",List.of(true));
            content(s,"data/events.json",data.toString());check(inspect(s).equals("invalid_public_data"),defect);
        }
        for(String reference:List.of("https://example.com/private","/static/uploads/../secret","/static/uploads/missing.png")){
            Memory s=valid(loader);JSONObject data=new JSONObject(text(s.bytes.get("data/events.json")));data.getJSONArray("events").getJSONObject(0).put("image_tv",reference);content(s,"data/events.json",data.toString());
            String expected=reference.startsWith("https")?"unsupported_media_reference":reference.contains("..")?"unsafe_path":"invalid_package";
            check(inspect(s).equals(expected),"media ref");
        }
        String[][] vectors={{"resources/static/css/base.css","/* URL\u001c( x ) */","unsupported_css_dependency"},
            {"resources/static/css/base.css","@\u0131mport 'x';","unsupported_css_dependency"},
            {"resources/static/js/tv.js","// import('x')","unsupported_script_dependency"},
            {"resources/static/js/tv.js","\u00e9require('x')","unsupported_script_dependency"},
            {"resources/templates/tv.html","{% include 'absent.html' %}","missing_display_template"},
            {"resources/templates/tv.html","filename='absent.css'","missing_display_resource"},
            {"resources/translations/en.json","{\"x\":false}","invalid_translation_resource"},
            {"resources/translations/en.json","{","invalid_package"}};
        log.accept("legacy CSS regex diagnostic dotlessI="+java.util.regex.Pattern.compile("@import",java.util.regex.Pattern.CASE_INSENSITIVE|java.util.regex.Pattern.UNICODE_CASE).matcher("@\u0131mport").find()
            +" controlWhitespace="+java.util.regex.Pattern.compile("url[\\u001c]*\\(",java.util.regex.Pattern.CASE_INSENSITIVE|java.util.regex.Pattern.UNICODE_CASE).matcher("URL\u001c(").find());
        for(String[] vector:vectors){Memory s=valid(loader);content(s,vector[0],vector[1]);String actual=inspect(s);check(actual.equals(vector[2]),vector[2]+" actual="+actual);}
        // Deliberately not an image validator: corrupt but correctly hashed image bytes remain UNCHECKED.
        Memory s=valid(loader);content(s,"static/uploads/card.png","not an image");content(s,"resources/static/img/site_icon.png","also not an image");
        check(inspect(s).equals("structural_integrity_ok"),"structural only image boundary");
        log.accept("public exact schema/tag/media/resource closure/dependency regex/image boundary PASS");
    }
    public static void jsonAndUnicode(Loader loader,Consumer<String> log) throws Exception {
        for(String token:List.of("1","-0","9223372036854775808","9".repeat(128)))check(PackageJson.parse(token.getBytes(StandardCharsets.UTF_8)) instanceof BigInteger,"exact integer");
        check(PackageJson.parse("9".repeat(4300).getBytes(StandardCharsets.UTF_8)) instanceof BigInteger,"Python default int digit boundary");
        try{PackageJson.parse("9".repeat(4301).getBytes(StandardCharsets.UTF_8));throw new AssertionError("digit cap");}catch(PackageFailure expected){}
        for(String token:List.of("1.0","1e0","true","false","null","NaN","Infinity","-Infinity"))check(!(PackageJson.parse(token.getBytes(StandardCharsets.UTF_8)) instanceof BigInteger),"not integer");
        for(String json:List.of("{/*x*/}","{'x':1}","{\"x\":1,}","01","1 trailing","\"\\uZZZZ\"","[".repeat(129)+"]".repeat(129))){
            try{PackageJson.parse(json.getBytes(StandardCharsets.UTF_8));throw new AssertionError("bad syntax accepted");}catch(PackageFailure expected){check(expected.code==PackageFailure.Code.invalid_package,"safe parser");}
        }
        check(PackageJson.object(PackageJson.parse("{\"x\":0,\"x\":1}".getBytes(StandardCharsets.UTF_8)),PackageFailure.Code.invalid_package).get("x").equals(BigInteger.ONE),"last wins");
        for(String encoding:List.of("UTF-8","UTF-16LE","UTF-16BE","UTF-32LE","UTF-32BE")){
            String json="{\"x\":\"Пример 😀 Straße\"}";check(PackageJson.object(PackageJson.parse(json.getBytes(encoding)),PackageFailure.Code.invalid_package).get("x").equals("Пример 😀 Straße"),encoding);
            byte[] body=json.getBytes(encoding),bom=encoding.equals("UTF-8")?new byte[]{(byte)239,(byte)187,(byte)191}:encoding.equals("UTF-16LE")?new byte[]{(byte)255,(byte)254}:encoding.equals("UTF-16BE")?new byte[]{(byte)254,(byte)255}:encoding.equals("UTF-32LE")?new byte[]{(byte)255,(byte)254,0,0}:new byte[]{0,0,(byte)254,(byte)255};
            byte[] encoded=new byte[bom.length+body.length];System.arraycopy(bom,0,encoded,0,bom.length);System.arraycopy(body,0,encoded,bom.length,body.length);
            check(PackageJson.object(PackageJson.parse(encoded),PackageFailure.Code.invalid_package).get("x").equals("Пример 😀 Straße"),"BOM "+encoding);
        }
        check(PackageJson.parse(new byte[]{34,(byte)0xed,(byte)0xa0,(byte)0x80,34}).equals("\ud800"),"surrogatepass");
        for(byte[] bad:List.of(new byte[]{(byte)0xc0,(byte)0xaf},new byte[]{34,(byte)0xff,34})){
            try{PackageJson.parse(bad);throw new AssertionError("invalid UTF8");}catch(PackageFailure expected){}
        }
        Memory s=valid(loader);var m=new JSONObject(manifest(s));m.put("unknown",new JSONObject().put("x",1));m.getJSONArray("files").getJSONObject(0).put("unknown","allowed");manifest(s,m.toString());
        check(inspect(s).equals("structural_integrity_ok"),"unknown properties tolerated");
        s=valid(loader);manifest(s,manifest(s).replaceFirst("\\{","{\"unknown\":NaN,"));check(inspect(s).equals("structural_integrity_ok"),"Python nonfinite unknown tolerance");
        s=valid(loader);String huge="9".repeat(128);
        String data=text(s.bytes.get("data/events.json")).replace("\"id\":1","\"id\":"+huge).replace("\"tag_ids\":[1]","\"tag_ids\":["+huge+"]");
        content(s,"data/events.json",data);check(inspect(s).equals("structural_integrity_ok"),"big IDs/reference without Long truncation");
        log.accept("JSON types/big integers/last key/BOM encodings/Unicode/nonfinite unknown tolerance PASS");
    }
    public static void streams(Loader loader,Consumer<String> log) throws Exception {
        Memory original=valid(loader);
        String name="data/events.json";byte[] payload=original.bytes.get(name);
        LocalView.Source changing=new LocalView.Source(){int reads;
            public Set<String> files(){return original.files();}
            public InputStream open(String path)throws IOException{
                if(path.equals(name)&&++reads==2)return new ByteArrayInputStream(new byte[payload.length]);return original.open(path);
            }};
        try{EventsPackage.inspect(changing);throw new AssertionError("changed resource");}catch(PackageFailure e){check(e.code==PackageFailure.Code.source_changed,"reread witness");}
        for(boolean zero:List.of(false,true)){
            LocalView.Source endless=new LocalView.Source(){
                public Set<String> files(){return Set.of();}
                public InputStream open(String path){return new InputStream(){long n;public int read(){return 32;}
                    public int read(byte[] bytes,int off,int len){check(n<=2*1024*1024+1,"bounded stream");if(zero)return 0;java.util.Arrays.fill(bytes,off,off+len,(byte)32);n+=len;return len;}};}
            };
            try{EventsPackage.inspect(endless);throw new AssertionError("unbounded");}catch(PackageFailure e){check(e.code==PackageFailure.Code.manifest_too_large,"stream limit");}
        }
        LocalView.Source secret=new LocalView.Source(){public Set<String> files()throws IOException{throw new IOException("PRIVATE_SECRET_PATH");}public InputStream open(String path)throws IOException{throw new IOException("PRIVATE_SECRET_PATH");}};
        try{EventsPackage.inspect(secret);throw new AssertionError("io");}catch(PackageFailure e){check(e.getMessage().equals("invalid_package")&&e.getCause()==null,"safe IO");}
        LocalView.Source closeSecret=new LocalView.Source(){public Set<String> files(){return Set.of();}public InputStream open(String path){return new ByteArrayInputStream(new byte[2*1024*1024+1]){@Override public void close()throws IOException{throw new IOException("PRIVATE_CLOSE_PATH");}};}};
        try{EventsPackage.inspect(closeSecret);throw new AssertionError("close");}catch(PackageFailure e){check(e.getCause()==null&&e.getSuppressed().length==0&&e.getMessage().equals("manifest_too_large"),"safe close failure");}
        log.accept("bounded generated streams/reread mutation/safe errors PASS");
    }
}
