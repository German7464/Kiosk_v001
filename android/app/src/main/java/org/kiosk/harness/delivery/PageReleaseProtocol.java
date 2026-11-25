package org.kiosk.harness.delivery;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.PublicKey;
import java.security.Signature;
import java.util.*;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.publishing.PublisherAuthority;
import static org.kiosk.harness.delivery.DeliveryJson.*;

/**
 * Independent Android verifier for page-release-v2 plans, target metadata,
 * data-only pages packages and v4 assignments. Pure JSON/byte logic; no
 * package-supplied executable content is ever trusted.
 */
public final class PageReleaseProtocol {
    public static final long PLAN_VERSION=2, ENVELOPE_VERSION=2, ASSIGNMENT_VERSION=4, MANIFEST_VERSION=2;
    public static final String KIND="page-publication", RENDERER="pages-v1", ENTRYPOINT="data/page-release.json";
    public static final String PROFILE=DeliveryProtocol.PROFILE;
    public static final String SHIPPED_JS_SHA256="3528358ae2bb2f8a85d2c5f58fed6ba8b1c98ea37d842931460657e6f063e20d";
    public static final String SHIPPED_CSS_SHA256="d3fd8af903cacb3e5e5d33df69663002bfb3a9157f432997e448c8d8266a54cf";
    public static final byte[] DOMAIN="Kiosk/PageRelease/v2\0".getBytes(StandardCharsets.US_ASCII);
    public static final byte[] PLAN_DOMAIN="Kiosk/PageReleasePlan/v2\0".getBytes(StandardCharsets.US_ASCII);
    public static final byte[] RENDERER_DOMAIN="Kiosk/PagesRenderer/v1\0".getBytes(StandardCharsets.US_ASCII);
    public static final Set<String> DESTINATIONS=Set.of("android-pages-v1","windows-pages-v1");
    public static final List<String> PROJECTIONS=List.of("kiosk-landscape","kiosk-portrait","tv-landscape","tv-portrait");
    public static final int MAX_DOCUMENT=2*1024*1024, MAX_ENVELOPE=32768, MAX_OBJECTS=1000;
    public static final int MAX_INVENTORY=10001, MAX_METADATA_FILES=30003, MAX_ANCESTRY_NODES=128, MAX_PARENTS=32;
    public static final long MAX_FILE=64L*1024*1024, MAX_TOTAL=192L*1024*1024, MAX_ANCESTRY=512L*1024, MAX_PLAN_SECONDS=90L*86400;

    public static final class Refused extends Exception {
        public final String code;
        public Refused(String code){super(code);this.code=code;}
    }
    public record Files(Map<String,byte[]> packageFiles,Map<String,byte[]> kioskFiles,Map<String,byte[]> tvFiles){
        public Files {
            packageFiles=packageFiles==null?Map.of():Map.copyOf(packageFiles);
            kioskFiles=kioskFiles==null?Map.of():Map.copyOf(kioskFiles);
            tvFiles=tvFiles==null?Map.of():Map.copyOf(tvFiles);
        }
        public static Files packageOnly(Map<String,byte[]> packageFiles){return new Files(packageFiles,Map.of(),Map.of());}
    }
    public record PageAdmission(Map<String,Object> plan,Map<String,Object> target,Map<String,Object> policy,
                                Map<String,Object> metadata,Map<String,Object> publication,
                                Map<String,Object> content,String packageId,String revision,String destination,
                                String projection,String renderer,String contentSha256,String metadataSha256){}
    private record Entry(String path,long size,String sha256){}
    private record Target(Map<String,Object> value,String deviceId,String projection,String destination,
                          Map<String,Object> configuration,Map<String,Object> metadata){}
    private record Selection(List<String> pages,String start,long transition){}

    private PageReleaseProtocol(){}

    static void require(boolean valid,String code)throws Refused{if(!valid)throw new Refused(code);}
    static void fail(String code)throws Refused{throw new Refused(code);}
    static String sha(String value){return LocalView.digest(value.getBytes(StandardCharsets.UTF_8));}
    static String sha(byte[] value){return LocalView.digest(value);}
    static boolean isHash(String value){return value!=null&&value.matches("[a-f0-9]{64}");}
    static String digest(String value)throws Refused{require(isHash(value),"invalid_digest");return value;}
    static String identifier(String value,int maximum)throws Refused{
        require(value!=null&&value.length()>=1&&value.length()<=maximum&&value.matches("[A-Za-z0-9_.-]+"),"invalid_identifier");return value;
    }
    static long signed(Object value)throws Refused{
        require(value instanceof NumberToken,"TYPE_REFUSED");
        String token=((NumberToken)value).token();
        require(token.matches("-?(0|[1-9][0-9]*)"),"TYPE_REFUSED");
        try{return Long.parseLong(token);}catch(NumberFormatException e){throw new Refused("publisher_integer_refused");}
    }
    static long positive(Object value)throws Refused{
        long number=signed(value);require(number>=1,"publisher_integer_refused");return number;
    }
    static String text(Object value)throws Refused{require(value instanceof String,"TYPE_REFUSED");return (String)value;}
    static String name(Object value,int maximum)throws Refused{
        String text=text(value);
        require(!text.trim().isEmpty()&&text.length()<=maximum&&text.indexOf('\0')<0,"page_release_object_payload");
        return text;
    }
    static Map<String,Object> map(Object value)throws Refused{
        try{return object(value);}catch(DeliveryJson.Refused refused){throw new Refused(refused.code);}
    }
    static List<Object> list(Object value)throws Refused{
        try{return array(value);}catch(DeliveryJson.Refused refused){throw new Refused(refused.code);}
    }
    static String str(Map<String,Object> value,String key)throws Refused{return text(value.get(key));}
    static Map<String,Object> obj(Map<String,Object> value,String key)throws Refused{return map(value.get(key));}
    static List<Object> arr(Map<String,Object> value,String key)throws Refused{return list(value.get(key));}
    static void exact(Map<String,Object> value,String... fields)throws Refused{
        try{keys(value,fields);}catch(DeliveryJson.Refused refused){throw new Refused(refused.code);}
    }
    static void exact(Map<String,Object> value,Set<String> fields)throws Refused{
        require(value!=null&&value.keySet().equals(fields),"invalid_fields");
    }
    static void origin(String value)throws Refused{
        try{
            require(value!=null&&value.length()<=255&&value.chars().allMatch(c->c<128),"publisher_origin_refused");
            URI uri=new URI(value);
            require("https".equals(uri.getScheme())&&uri.getHost()!=null&&uri.getPort()>0&&uri.getUserInfo()==null
                &&uri.getRawQuery()==null&&uri.getRawFragment()==null&&"".equals(uri.getRawPath())
                &&value.equals("https://"+uri.getHost()+":"+uri.getPort()),"publisher_origin_refused");
        }catch(Refused refused){throw refused;}catch(Exception malformed){throw new Refused("publisher_origin_refused");}
    }
    static void validity(Map<String,Object> value,long now,long maximum)throws Refused{
        long issued=positive(value.get("issued")),expires=positive(value.get("expires"));
        require(issued<=now&&now<expires&&issued<expires&&expires-issued<=maximum,"publisher_authority_expired");
    }
    public static String rendererBuildId(String jsSha256,String cssSha256)throws Exception{
        digest(jsSha256);digest(cssSha256);
        Map<String,Object> value=new TreeMap<>();value.put("css_sha256",cssSha256);value.put("js_sha256",jsSha256);
        byte[] canonical=PublisherAuthority.canonical(value),input=new byte[RENDERER_DOMAIN.length+canonical.length];
        System.arraycopy(RENDERER_DOMAIN,0,input,0,RENDERER_DOMAIN.length);
        System.arraycopy(canonical,0,input,RENDERER_DOMAIN.length,canonical.length);
        return sha(input);
    }

    public static Map<String,Object> pageVerified(Map<String,Object> envelope,PublicKey key)throws Exception{
        exact(envelope,"payload","signature");
        byte[] payload=DeliveryProtocol.b64(str(envelope,"payload"),MAX_ENVELOPE);
        byte[] signature=DeliveryProtocol.b64(str(envelope,"signature"),384);
        require(signature.length==384,"publisher_encoding_refused");
        Signature verifier=Signature.getInstance("SHA256withRSA");
        verifier.initVerify(key);verifier.update(DOMAIN);verifier.update(payload);
        require(verifier.verify(signature),"publisher_signature_refused");
        Map<String,Object> outer=DeliveryJson.object(DeliveryJson.parse(payload,MAX_ENVELOPE));
        exact(outer,"kind","value","version");
        require(signed(outer.get("version"))==ENVELOPE_VERSION&&KIND.equals(str(outer,"kind")),"publisher_domain_refused");
        require(Arrays.equals(payload,PublisherAuthority.canonical(outer)),"publisher_canonical_refused");
        require(outer.get("value") instanceof Map,"publisher_domain_refused");
        return map(outer.get("value"));
    }

    public static Map<String,Object> validatePlan(Map<String,Object> plan,long now)throws Exception{
        exact(plan,"version","id","group_id","origin","user_id","device_id","policy_version","issued","expires",
            "revision_sha256","dependencies_sha256","targets","parents");
        require(signed(plan.get("version"))==PLAN_VERSION,"publisher_plan_version");
        digest(str(plan,"id"));identifier(str(plan,"group_id"),128);identifier(str(plan,"user_id"),128);
        digest(str(plan,"device_id"));digest(str(plan,"revision_sha256"));digest(str(plan,"dependencies_sha256"));
        origin(str(plan,"origin"));positive(plan.get("policy_version"));validity(plan,now,MAX_PLAN_SECONDS);
        List<Object> targets=arr(plan,"targets");require(targets.size()>=1&&targets.size()<=100,"publisher_target_limit");
        String prior="";
        for(Object item:targets){
            Map<String,Object> target=map(item);
            exact(target,"device_id","profile_id","profile_version","mode","configuration_sha256","projection","destination","renderer","metadata_sha256");
            String device=identifier(str(target,"device_id"),128);require(device.compareTo(prior)>0,"publisher_target_ambiguity");prior=device;
            identifier(str(target,"profile_id"),64);positive(target.get("profile_version"));
            String mode=str(target,"mode");require("tv".equals(mode)||"kiosk".equals(mode),"publisher_mode_refused");
            String projection=str(target,"projection");require(PROJECTIONS.contains(projection),"publisher_projection_refused");
            require(projection.startsWith(mode+"-"),"publisher_projection_refused");
            require(DESTINATIONS.contains(str(target,"destination")),"publisher_metadata_destination");
            digest(str(target,"configuration_sha256"));digest(str(target,"renderer"));digest(str(target,"metadata_sha256"));
        }
        List<Object> parents=arr(plan,"parents");require(parents.size()<=MAX_PARENTS,"publisher_parent_limit");
        prior="";
        for(Object item:parents){String identity=digest(text(item));require(identity.compareTo(prior)>0,"publisher_parent_limit");prior=identity;}
        Map<String,Object> without=new TreeMap<>(plan);without.remove("id");
        byte[] canonical=PublisherAuthority.canonical(without),input=new byte[PLAN_DOMAIN.length+canonical.length];
        System.arraycopy(PLAN_DOMAIN,0,input,0,PLAN_DOMAIN.length);
        System.arraycopy(canonical,0,input,PLAN_DOMAIN.length,canonical.length);
        require(str(plan,"id").equals(sha(input)),"publisher_plan_identity");
        return plan;
    }

    static Map<String,Object> expectedLimits(){
        Map<String,Object> value=new LinkedHashMap<>();
        value.put("capture_bytes",201326592L);value.put("capture_files",30003L);
        value.put("max_live_bytes",33554432L);value.put("max_pixels",2000000L);
        value.put("min_free_bytes",16777216L);value.put("per_image_ms",5000L);
        value.put("total_image_ms",15000L);
        return value;
    }
    public static boolean safePath(String path){
        if(path==null||path.isEmpty()||path.codePointCount(0,path.length())>240)return false;
        if(path.codePoints().anyMatch(c->c<32||"\\:<>\"|?*%#".indexOf(c)>=0))return false;
        for(String part:path.split("/",-1)){
            if(part.isEmpty()||part.equals(".")||part.equals("..")||part.endsWith(".")||part.endsWith(" "))return false;
            String base=part.split("\\.",-1)[0].toUpperCase(Locale.ROOT);
            if(Set.of("CON","PRN","AUX","NUL").contains(base)||base.matches("COM[1-9]|LPT[1-9]"))return false;
        }
        return true;
    }
    static Map<String,Entry> inventoryRows(Object value,String code,int minimum)throws Refused{
        List<Object> rows=list(value);
        require(rows.size()>=minimum&&rows.size()<=MAX_INVENTORY,code);
        Map<String,Entry> result=new LinkedHashMap<>();Set<String> folded=new HashSet<>();
        for(Object item:rows){
            Map<String,Object> row=map(item);exact(row,"path","size","sha256");
            String path=str(row,"path");require(safePath(path),code);
            require(folded.add(path.toLowerCase(Locale.ROOT)),code);
            long size=signed(row.get("size"));require(size>=0&&size<=MAX_FILE,code);
            String hash=digest(str(row,"sha256"));
            result.put(path,new Entry(path,size,hash));
        }
        List<String> names=new ArrayList<>(folded);
        for(String name:names)for(int index=1;index<name.split("/").length;index++){
            String parent=String.join("/",Arrays.copyOf(name.split("/"),index));
            require(!folded.contains(parent),code);
        }
        return result;
    }
    static Map<String,Entry> manifestRows(Object value)throws Refused{
        List<Object> rows=list(value);
        require(rows.size()>=1&&rows.size()<=10000,"publisher_metadata_inventory");
        Map<String,Entry> result=new LinkedHashMap<>();Set<String> folded=new HashSet<>();
        long total=0;
        for(Object item:rows){
            Map<String,Object> row=map(item);exact(row,"path","size","sha256");
            String path=str(row,"path");require(safePath(path), "publisher_metadata_inventory");
            require(folded.add(path.toLowerCase(Locale.ROOT)),"publisher_metadata_inventory");
            long size=signed(row.get("size"));require(size>=0&&size<=MAX_FILE,"publisher_metadata_inventory");
            total+=size;require(total<=MAX_TOTAL,"publisher_metadata_inventory");
            result.put(path,new Entry(path,size,digest(str(row,"sha256"))));
        }
        return result;
    }
    public static Map<String,Object> validateMetadata(Map<String,Object> metadata)throws Exception{
        exact(metadata,"version","destination","revision_sha256","content_sha256","publication");
        require(signed(metadata.get("version"))==PLAN_VERSION&&DESTINATIONS.contains(str(metadata,"destination")),
            "publisher_metadata_destination");
        digest(str(metadata,"revision_sha256"));digest(str(metadata,"content_sha256"));
        Map<String,Object> publication=obj(metadata,"publication");
        exact(publication,"version","package_id","revision","raw_manifest_sha256","renderer","resource_profile",
            "limits","windows_images","package","kiosk","tv");
        require(signed(publication.get("version"))==PLAN_VERSION,"publisher_metadata_version");
        digest(str(publication,"package_id"));digest(str(publication,"raw_manifest_sha256"));digest(str(publication,"revision"));
        require(str(publication,"revision").equals(str(metadata,"revision_sha256")),"publisher_content_substitution");
        Map<String,Object> renderer=obj(publication,"renderer");exact(renderer,"build_id","js_sha256","css_sha256");
        digest(str(renderer,"build_id"));digest(str(renderer,"js_sha256"));digest(str(renderer,"css_sha256"));
        require(str(renderer,"build_id").equals(rendererBuildId(str(renderer,"js_sha256"),str(renderer,"css_sha256"))),
            "publisher_metadata_renderer");
        require(PROFILE.equals(str(publication,"resource_profile")),"publisher_metadata_profile");
        exact(obj(publication,"limits"),"capture_bytes","capture_files","max_live_bytes","max_pixels",
            "min_free_bytes","per_image_ms","total_image_ms");
        Map<String,Object> limits=obj(publication,"limits");
        for(Map.Entry<String,Object> entry:expectedLimits().entrySet())
            require(signed(limits.get(entry.getKey()))==((Number)entry.getValue()).longValue(),"publisher_metadata_profile");
        require(obj(publication,"windows_images").isEmpty(),"publisher_metadata_inventory");
        Map<String,Object> packageGroup=obj(publication,"package");exact(packageGroup,"files");
        Map<String,Entry> entries=inventoryRows(packageGroup.get("files"),"publisher_metadata_inventory",2);
        require(entries.size()<=MAX_METADATA_FILES,"publisher_metadata_inventory");
        require(entries.keySet().stream().filter(name->name.equals("manifest.json")).count()==1,"publisher_metadata_inventory");
        List<Object> manifestFiles=new ArrayList<>();
        for(Map.Entry<String,Entry> entry:entries.entrySet()){
            if(entry.getKey().equals("manifest.json"))continue;
            Map<String,Object> row=new LinkedHashMap<>();row.put("path",entry.getValue().path());
            row.put("size",new NumberToken(Long.toString(entry.getValue().size())));
            row.put("sha256",entry.getValue().sha256());manifestFiles.add(row);
        }
        manifestRows(manifestFiles);
        for(String group:List.of("kiosk","tv")){
            Map<String,Object> view=obj(publication,group);exact(view,"files");
            require(arr(view,"files").isEmpty(),"publisher_metadata_inventory");
        }
        long total=entries.values().stream().mapToLong(Entry::size).sum();
        require(total<=MAX_TOTAL&&PublisherAuthority.canonical(metadata).length<=LocalView.DESCRIPTOR_LIMIT,
            "publisher_metadata_inventory");
        return publication;
    }

    static String pageKind(String identity)throws Refused{
        if(identity!=null&&identity.matches("(dataset|block|layout|page|profile|assignment)-[0-9a-f]{32}"))
            return identity.substring(0,identity.indexOf('-'));
        if(identity!=null&&identity.matches("[1-9][0-9]{0,9}")&&Long.parseLong(identity)<=2147483647L)return "event";
        throw new Refused("page_release_object_identity");
    }
    static String reference(Object value,String expected)throws Refused{
        String identity=text(value);require(pageKind(identity).equals(expected),"page_release_object_payload");return identity;
    }
    static List<String> references(Object value,String expected,int lower,int upper)throws Refused{
        List<Object> items=list(value);require(items.size()>=lower&&items.size()<=upper,"page_release_object_payload");
        List<String> result=new ArrayList<>();Set<String> unique=new HashSet<>();
        for(Object item:items){String identity=reference(item,expected);require(unique.add(identity),"page_release_object_payload");result.add(identity);}
        return result;
    }
    static long bounded(Object value,long lower,long upper)throws Refused{
        long number=signed(value);require(number>=lower&&number<=upper,"page_release_object_payload");return number;
    }
    static Selection selection(Map<String,Object> value)throws Refused{
        exact(value,"pages","start_page","transition_seconds");
        List<String> pages=references(value.get("pages"),"page",1,32);
        String start=str(value,"start_page");require(pages.contains(start),"page_release_object_payload");
        long transition=bounded(value.get("transition_seconds"),5,600);
        return new Selection(pages,start,transition);
    }
    static List<String> pageReferences(String identity,Map<String,Object> payload)throws Refused{
        String kind=pageKind(identity);
        require(signed(payload.get("schema"))==1,"page_release_object_payload");
        switch(kind){
            case "dataset" -> {
                exact(payload,"schema","name","module","events");
                name(payload.get("name"),120);require("events".equals(str(payload,"module")),"page_release_object_payload");
                return references(payload.get("events"),"event",0,100);
            }
            case "block" -> {
                exact(payload,"schema","name","dataset","tags","limit","appearance");
                name(payload.get("name"),120);
                List<Object> tags=list(payload.get("tags"));require(tags.size()<=32,"page_release_object_payload");
                Set<String> unique=new HashSet<>();
                for(Object tag:tags){String text=text(tag);require(unique.add(text)&&!text.trim().isEmpty()&&text.length()<=128&&text.indexOf('\0')<0,"page_release_object_payload");}
                bounded(payload.get("limit"),1,100);
                require("cards".equals(str(payload,"appearance"))||"list".equals(str(payload,"appearance")),"page_release_object_payload");
                return List.of(reference(payload.get("dataset"),"dataset"));
            }
            case "layout" -> {
                exact(payload,"schema","target","columns","rows","placements");
                require(PROJECTIONS.contains(str(payload,"target")),"page_release_object_payload");
                long columns=bounded(payload.get("columns"),1,24),rows=bounded(payload.get("rows"),1,24);
                List<Object> placements=list(payload.get("placements"));require(placements.size()>=1&&placements.size()<=24,"page_release_object_payload");
                Set<String> occupied=new HashSet<>();List<Object> blocks=new ArrayList<>();
                for(Object item:placements){
                    Map<String,Object> placement=map(item);exact(placement,"block","x","y","w","h");
                    blocks.add(placement.get("block"));
                    long x=bounded(placement.get("x"),0,columns-1),y=bounded(placement.get("y"),0,rows-1);
                    long w=bounded(placement.get("w"),1,columns-x),h=bounded(placement.get("h"),1,rows-y);
                    for(long column=x;column<x+w;column++)for(long row=y;row<y+h;row++)
                        require(occupied.add(column+":"+row),"page_release_object_payload");
                }
                return references(blocks,"block",1,24);
            }
            case "page" -> {
                exact(payload,"schema","name","order","layouts","fallback");
                name(payload.get("name"),120);bounded(payload.get("order"),0,10000);
                Map<String,Object> layouts=obj(payload,"layouts");
                require(!layouts.isEmpty()&&PROJECTIONS.containsAll(layouts.keySet()),"page_release_object_payload");
                String fallback=str(payload,"fallback");require(layouts.containsKey(fallback),"page_release_object_payload");
                return references(new ArrayList<>(layouts.values()),"layout",1,4);
            }
            case "profile" -> {
                exact(payload,"schema","name","selection");name(payload.get("name"),120);
                return selection(obj(payload,"selection")).pages();
            }
            case "assignment" -> {
                exact(payload,"schema","device","profile","selection");
                String device=text(payload.get("device"));require(!device.trim().isEmpty()&&device.length()<=128&&device.indexOf('\0')<0,"page_release_object_payload");
                Object profile=payload.get("profile"),inline=payload.get("selection");
                if(profile==null){require(inline!=null,"page_release_object_payload");return selection(map(inline)).pages();}
                require(inline==null,"page_release_object_payload");return List.of(reference(profile,"profile"));
            }
            default -> throw new Refused("page_release_object_identity");
        }
    }
    static void eventPayload(Map<String,Object> payload)throws Exception{
        require(PublisherAuthority.canonical(payload).length<=32768,"page_release_object_payload");
        exact(payload,"title","short_description","full_description","event_date","place","sort_order","status","images","tags");
        for(String field:List.of("title","short_description","full_description","place")){
            String value=str(payload,field);int maximum=field.equals("title")?300:field.equals("short_description")?4096:field.equals("full_description")?16384:512;
            require(value.length()<=maximum&&value.indexOf('\0')<0,"page_release_object_payload");
        }
        if(payload.get("event_date")!=null){String value=str(payload,"event_date");require(value.length()<=64&&value.indexOf('\0')<0,"page_release_object_payload");}
        require(!str(payload,"title").trim().isEmpty(),"page_release_object_payload");
        String status=str(payload,"status");require("active".equals(status)||"hidden".equals(status),"page_release_object_payload");
        long order=signed(payload.get("sort_order"));require(order>=-100000&&order<=100000,"page_release_object_payload");
        List<Object> images=list(payload.get("images")),tags=list(payload.get("tags"));
        require(images.size()<=3&&tags.size()<=32,"page_release_object_payload");
        Set<String> uniqueTags=new HashSet<>();
        for(Object tag:tags){String text=text(tag);require(uniqueTags.add(text)&&!text.trim().isEmpty()&&text.length()<=128&&text.indexOf('\0')<0,"page_release_object_payload");}
        for(Object item:images){
            if(item==null){require(images.size()==3,"page_release_object_payload");continue;}
            String image=text(item);
            require(image.startsWith("/static/uploads/")&&image.indexOf('\\')<0&&image.length()<=512&&image.indexOf('\0')<0
                &&image.indexOf('?')<0&&image.indexOf('#')<0&&image.indexOf('%')<0,"page_release_object_payload");
            String[] parts=image.split("/",-1);
            for(int index=1;index<parts.length;index++)require(!parts[index].isEmpty()&&!parts[index].equals(".")&&!parts[index].equals(".."),"page_release_object_payload");
        }
    }

    public static Map<String,Object> validateRevision(Map<String,Object> revision)throws Exception{
        exact(revision,"plan","objects");
        Map<String,Object> plan=obj(revision,"plan");exact(plan,"included","excluded");
        Map<String,Object> objects=obj(revision,"objects");
        require(objects.size()>=1&&objects.size()<=MAX_OBJECTS,"page_release_object_limit");
        List<Object> included=arr(plan,"included"),excluded=arr(plan,"excluded");
        require(included.size()<=MAX_OBJECTS&&excluded.size()<=MAX_OBJECTS,"page_release_plan_fields");
        Set<String> listed=new HashSet<>();
        for(Object item:included){
            Map<String,Object> entry=map(item);exact(entry,"id","version","author");
            String identity=str(entry,"id");pageKind(identity);positive(entry.get("version"));identifier(str(entry,"author"),128);
            require(listed.add(identity),"page_release_plan_ambiguity");
        }
        for(Object item:excluded){
            Map<String,Object> entry=map(item);exact(entry,"id","version","author","reason");
            String identity=str(entry,"id");pageKind(identity);positive(entry.get("version"));identifier(str(entry,"author"),128);
            String reason=str(entry,"reason");require(reason.matches("[A-Za-z0-9_.-]{1,64}"),"page_release_object_payload");
            require(listed.add(identity),"page_release_plan_ambiguity");
        }
        for(Map.Entry<String,Object> item:objects.entrySet()){
            String identity=item.getKey(),kind=pageKind(identity);Map<String,Object> entry=map(item.getValue());
            exact(entry,"version","payload","dependencies","author");
            positive(entry.get("version"));identifier(str(entry,"author"),128);
            Map<String,Object> payload=obj(entry,"payload"),dependencies=obj(entry,"dependencies");
            List<String> refs;
            if(kind.equals("event")){eventPayload(payload);refs=List.of();}
            else{
                refs=pageReferences(identity,payload);
                if(kind.equals("page")){
                    Map<String,Map<String,Object>> layouts=new LinkedHashMap<>();
                    for(String dependency:refs){
                        require(objects.containsKey(dependency),"page_release_dependency_missing");
                        layouts.put(dependency,obj(map(objects.get(dependency)),"payload"));
                    }
                    for(Map.Entry<String,Object> layout:obj(payload,"layouts").entrySet()){
                        String id=text(layout.getValue());
                        require(layouts.get(id)!=null&&layout.getKey().equals(str(layouts.get(id),"target")),"page_release_object_payload");
                    }
                }
            }
            require(dependencies.keySet().equals(new HashSet<>(refs)),"page_release_dependency_mismatch");
            for(Map.Entry<String,Object> dependency:dependencies.entrySet()){
                long version=positive(dependency.getValue());
                pageKind(dependency.getKey());
                Object found=objects.get(dependency.getKey());
                Map<String,Object> target=found==null?null:map(found);
                require(target!=null,"page_release_dependency_missing");
                require(positive(target.get("version"))==version,"page_release_dependency_version");
            }
        }
        for(Object item:included){
            Map<String,Object> entry=map(item);Object found=objects.get(str(entry,"id"));
            Map<String,Object> target=found==null?null:map(found);
            require(target!=null&&positive(target.get("version"))==positive(entry.get("version"))
                &&str(target,"author").equals(str(entry,"author")),"page_release_plan_entry");
        }
        for(Object item:excluded){
            Map<String,Object> entry=map(item);Object found=objects.get(str(entry,"id"));
            Map<String,Object> target=found==null?null:map(found);
            require(target==null||(positive(target.get("version"))<positive(entry.get("version"))
                &&str(target,"author").equals(str(entry,"author"))),"page_release_plan_entry");
        }
        Set<String> excludedIds=new HashSet<>();
        for(Object item:excluded)excludedIds.add(str(map(item),"id"));
        Set<String> reachable=new HashSet<>();
        ArrayDeque<String> pending=new ArrayDeque<>();
        for(Object item:included)pending.push(str(map(item),"id"));
        while(!pending.isEmpty()){
            String identity=pending.pop();
            if(!reachable.add(identity))continue;
            require(!excludedIds.contains(identity),"page_release_plan_entry");
            Map<String,Object> entry=map(objects.get(identity));
            require(entry!=null,"page_release_dependency_missing");
            for(String dependency:obj(entry,"dependencies").keySet())pending.push(dependency);
        }
        require(PublisherAuthority.canonical(revision).length<=MAX_DOCUMENT,"page_release_document_limit");
        return revision;
    }
    public static String revisionSha256(Map<String,Object> revision)throws Exception{
        validateRevision(revision);
        Map<String,Object> value=new TreeMap<>();value.put("plan",revision.get("plan"));value.put("objects",revision.get("objects"));
        return sha(PublisherAuthority.canonical(value));
    }
    static Map<String,Object> reflow(Map<String,Object> page,Map<String,Map<String,Object>> layouts,String target)throws Refused{
        Map<String,Object> chosen;
        Map<String,Object> named=obj(page,"layouts");
        if(named.containsKey(target))chosen=layouts.get(str(named,target));
        else{
            chosen=layouts.get(str(named,str(page,"fallback")));
            List<Object> placements=arr(chosen,"placements");List<Object> reflowed=new ArrayList<>();
            long index=0;
            for(Object item:placements){
                Map<String,Object> placement=map(item);Map<String,Object> copy=new LinkedHashMap<>();
                copy.put("block",placement.get("block"));copy.put("x",0L);copy.put("y",index++);
                copy.put("w",1L);copy.put("h",1L);reflowed.add(copy);
            }
            Map<String,Object> replacement=new LinkedHashMap<>();
            replacement.put("schema",1L);replacement.put("target",target);replacement.put("columns",1L);
            replacement.put("rows",(long)placements.size());replacement.put("placements",reflowed);
            chosen=replacement;
        }
        return chosen;
    }
    static Map<String,Object> project(Map<String,Object> objects,String device,String target)throws Exception{
        require(PROJECTIONS.contains(target),"page_release_projection");
        Map<String,Object> assignment=null;
        for(Map.Entry<String,Object> item:objects.entrySet()){
            if(!item.getKey().startsWith("assignment-"))continue;
            Map<String,Object> payload=obj(map(item.getValue()),"payload");
            if(device.equals(str(payload,"device"))){require(assignment==null,"page_release_projection_unavailable");assignment=payload;}
        }
        require(assignment!=null,"page_release_projection_unavailable");
        Map<String,Object> selected;
        if(assignment.get("profile")!=null)selected=obj(map(objects.get(str(assignment,"profile"))),"payload");
        else selected=assignment;
        Map<String,Object> selection=assignment.get("profile")!=null?obj(selected,"selection"):obj(assignment,"selection");
        Selection chosen=selection(selection);
        Map<String,Object> page=new LinkedHashMap<>();
        page.put("schema",1L);page.put("target",target);page.put("pages",new ArrayList<>());
        page.put("blocks",new LinkedHashMap<>());page.put("datasets",new LinkedHashMap<>());
        page.put("start_page",chosen.start());page.put("transition_seconds",chosen.transition());
        Set<String> eventIds=new TreeSet<>();
        for(String pageId:chosen.pages()){
            Map<String,Object> pageEntry=map(objects.get(pageId));require(pageEntry!=null,"page_release_projection_unavailable");
            Map<String,Object> pagePayload=obj(pageEntry,"payload");
            Map<String,Map<String,Object>> layouts=new LinkedHashMap<>();
            for(Map.Entry<String,Object> item:obj(pagePayload,"layouts").entrySet()){
                String id=text(item.getValue());Map<String,Object> layoutEntry=map(objects.get(id));
                require(layoutEntry!=null,"page_release_projection_unavailable");
                Map<String,Object> layout=obj(layoutEntry,"payload");
                require(item.getKey().equals(str(layout,"target")),"page_release_projection_unavailable");
                layouts.put(id,layout);
            }
            Map<String,Object> layout=reflow(pagePayload,layouts,target);
            Map<String,Object> projectedPage=new LinkedHashMap<>();
            projectedPage.put("id",pageId);projectedPage.put("version",positive(pageEntry.get("version")));
            projectedPage.put("name",str(pagePayload,"name"));projectedPage.put("columns",signed(layout.get("columns")));
            projectedPage.put("rows",signed(layout.get("rows")));projectedPage.put("placements",arr(layout,"placements"));
            arr(page,"pages").add(projectedPage);
            for(Object item:arr(layout,"placements")){
                String blockId=reference(map(item).get("block"),"block");
                Map<String,Object> blockEntry=map(objects.get(blockId));require(blockEntry!=null,"page_release_projection_unavailable");
                Map<String,Object> block=new LinkedHashMap<>(obj(blockEntry,"payload"));
                block.put("version",positive(blockEntry.get("version")));
                obj(page,"blocks").put(blockId,block);
                String datasetId=reference(block.get("dataset"),"dataset");
                Map<String,Object> datasetEntry=map(objects.get(datasetId));require(datasetEntry!=null,"page_release_projection_unavailable");
                Map<String,Object> dataset=new LinkedHashMap<>(obj(datasetEntry,"payload"));
                dataset.put("version",positive(datasetEntry.get("version")));
                obj(page,"datasets").put(datasetId,dataset);
                for(Object event:arr(dataset,"events"))eventIds.add(text(event));
            }
        }
        return page;
    }

    static int compareText(String left,String right){
        int l=0,r=0;
        while(l<left.length()&&r<right.length()){
            int lc=left.codePointAt(l),rc=right.codePointAt(r);if(lc!=rc)return Integer.compare(lc,rc);
            l+=Character.charCount(lc);r+=Character.charCount(rc);
        }
        return Integer.compare(left.length()-l,right.length()-r);
    }
    static Map<String,Object> publicData(Map<String,Object> objects,Set<String> eventIds)throws Exception{
        List<Object[]> active=new ArrayList<>();TreeSet<String> names=new TreeSet<>(PageReleaseProtocol::compareText);
        for(String identity:eventIds){
            Map<String,Object> entry=map(objects.get(identity));require(entry!=null,"page_release_projection_unavailable");
            Map<String,Object> payload=obj(entry,"payload");eventPayload(payload);
            if(!"active".equals(str(payload,"status")))continue;
            for(Object tag:arr(payload,"tags"))names.add(text(tag));
            String date=payload.get("event_date")==null?"":str(payload,"event_date");
            active.add(new Object[]{signed(payload.get("sort_order")),date,Long.parseLong(identity),payload});
        }
        active.sort((left,right)->{
            int order=Long.compare((Long)left[0],(Long)right[0]);if(order!=0)return order;
            order=compareText((String)left[1],(String)right[1]);
            return order!=0?order:Long.compare((Long)left[2],(Long)right[2]);
        });
        Map<String,Long> tagIds=new LinkedHashMap<>();long next=1;
        for(String name:names)tagIds.put(name,next++);
        List<Object> events=new ArrayList<>();
        for(Object[] item:active){
            Map<String,Object> payload=map(item[3]);List<Object> images=arr(payload,"images");
            String first=images.isEmpty()||images.get(0)==null?null:text(images.get(0));
            String kiosk=first;
            String tv=images.size()>1?(images.get(1)==null?null:text(images.get(1))):first;
            String thumb=images.size()>2?(images.get(2)==null?null:text(images.get(2))):first;
            List<Long> linked=new ArrayList<>();
            for(Object tag:arr(payload,"tags"))linked.add(tagIds.get(text(tag)));
            Collections.sort(linked);
            Map<String,Object> event=new LinkedHashMap<>();
            event.put("id",item[2]);event.put("title",str(payload,"title"));
            event.put("short_description",str(payload,"short_description"));
            event.put("full_description",str(payload,"full_description"));
            event.put("event_date",payload.get("event_date"));event.put("place",str(payload,"place"));
            event.put("image_kiosk",kiosk);event.put("image_tv",tv);event.put("image_thumb",thumb);
            event.put("sort_order",payload.get("sort_order"));event.put("tag_ids",linked);
            events.add(event);
        }
        List<Object> tags=new ArrayList<>();
        for(Map.Entry<String,Long> tag:tagIds.entrySet()){
            Map<String,Object> value=new LinkedHashMap<>();value.put("id",tag.getValue());value.put("name",tag.getKey());tags.add(value);
        }
        Map<String,Object> result=new LinkedHashMap<>();result.put("events",events);result.put("tags",tags);return result;
    }
    public static Map<String,Object> projectTarget(Map<String,Object> revision,String device,String projection)throws Exception{
        validateRevision(revision);
        identifier(device,128);require(PROJECTIONS.contains(projection),"page_release_projection");
        Map<String,Object> objects=obj(revision,"objects");
        Map<String,Object> page=project(objects,device,projection);
        Set<String> eventIds=new TreeSet<>();
        for(Object item:obj(page,"datasets").values())eventIds.addAll(arr(map(item),"events").stream().map(PageReleaseProtocol::uncheckedText).toList());
        Map<String,Object> publicData=publicData(objects,eventIds);
        Map<String,Object> content=new LinkedHashMap<>();
        content.put("page",page);content.put("events",publicData.get("events"));content.put("tags",publicData.get("tags"));
        return content;
    }
    static String uncheckedText(Object value){try{return text(value);}catch(Refused refused){throw new IllegalArgumentException(refused.code);}}
    static void verifyGroup(Map<String,Entry> expected,Map<String,byte[]> files)throws Refused{
        require(files!=null&&files.keySet().equals(expected.keySet()),"page_release_inventory");
        for(Map.Entry<String,Entry> entry:expected.entrySet()){
            byte[] bytes=files.get(entry.getKey());
            require(bytes!=null&&bytes.length==entry.getValue().size()&&sha(bytes).equals(entry.getValue().sha256()),
                "page_release_inventory");
        }
    }
    static Map<String,Object> decodeContent(byte[] payload)throws Exception{
        Map<String,Object> content=map(DeliveryJson.parse(payload,MAX_DOCUMENT));
        require(Arrays.equals(payload,PublisherAuthority.canonical(content)),"page_release_content_canonical");
        exact(content,"page","events","tags");
        map(content.get("page"));list(content.get("events"));list(content.get("tags"));
        return content;
    }
    static Set<String> imagePaths(Map<String,Object> content)throws Refused{
        Set<String> result=new TreeSet<>();
        for(Object item:arr(content,"events")){
            Map<String,Object> event=map(item);
            for(String field:List.of("image_kiosk","image_tv","image_thumb")){
                Object value=event.get(field);if(value==null)continue;
                String image=text(value);require(image.startsWith("/static/uploads/"),"page_release_image_reference");
                String name=image.substring(1),suffix=name.contains(".")?name.substring(name.lastIndexOf('.')+1).toLowerCase(Locale.ROOT):"";
                require(List.of("png","jpg","jpeg","webp","gif").contains(suffix),"page_release_image_reference");
                require(safePath(name),"page_release_image_reference");result.add(name);
            }
        }
        return result;
    }
    static Map<String,Object> parseManifest(byte[] raw,Map<String,Object> publication,Map<String,byte[]> files)throws Exception{
        Map<String,Object> manifest=map(DeliveryJson.parse(raw,MAX_DOCUMENT));
        require(Arrays.equals(raw,PublisherAuthority.canonical(manifest)),"page_release_manifest_canonical");
        exact(manifest,"schema_version","kind","revision","renderer","resource_contract","files","entrypoints");
        require(signed(manifest.get("schema_version"))==MANIFEST_VERSION&&"pages".equals(str(manifest,"kind"))
            &&RENDERER.equals(str(manifest,"renderer"))&&signed(manifest.get("resource_contract"))==1
            &&arr(manifest,"entrypoints").equals(List.of(ENTRYPOINT)),"page_release_manifest_contract");
        digest(str(manifest,"revision"));
        Map<String,Entry> entries=manifestRows(manifest.get("files"));
        Set<String> required=new HashSet<>(entries.keySet());required.add("manifest.json");
        require(files.keySet().equals(required),"page_release_package_inventory");
        for(Entry entry:entries.values()){
            byte[] payload=files.get(entry.path());
            require(payload!=null&&payload.length==entry.size()&&sha(payload).equals(entry.sha256()),"page_release_package_inventory");
        }
        require(sha(PublisherAuthority.canonical(manifest)).equals(str(publication,"package_id")),"page_release_package_identity");
        require(sha(raw).equals(str(publication,"raw_manifest_sha256")),"page_release_manifest_identity");
        require(str(manifest,"revision").equals(str(publication,"revision")),"page_release_revision");
        for(Entry entry:entries.values()){
            if(entry.path().equals(ENTRYPOINT))continue;
            String suffix=entry.path().contains(".")?entry.path().substring(entry.path().lastIndexOf('.')+1).toLowerCase(Locale.ROOT):"";
            require(entry.path().startsWith("static/uploads/")&&List.of("png","jpg","jpeg","webp","gif").contains(suffix),
                "page_release_data_only");
        }
        return manifest;
    }
    public static Map<String,Object> verifyInventory(Map<String,Object> publication,Files files)throws Exception{
        require(files!=null&&files.kioskFiles().isEmpty()&&files.tvFiles().isEmpty(),"page_release_transport_view");
        Map<String,Object> packageGroup=obj(publication,"package");
        Map<String,Entry> expected=inventoryRows(packageGroup.get("files"),"page_release_inventory",2);
        verifyGroup(expected,files.packageFiles());
        byte[] raw=files.packageFiles().get("manifest.json");
        require(raw!=null,"page_release_package_inventory");
        Map<String,Object> manifest=parseManifest(raw,publication,files.packageFiles());
        require(files.packageFiles().containsKey(ENTRYPOINT),"page_release_entrypoint");
        Map<String,Object> content=decodeContent(files.packageFiles().get(ENTRYPOINT));
        Set<String> expectedPaths=new HashSet<>();expectedPaths.add(ENTRYPOINT);expectedPaths.addAll(imagePaths(content));
        Set<String> manifestPaths=new HashSet<>();
        for(Object item:arr(manifest,"files"))manifestPaths.add(str(map(item),"path"));
        require(manifestPaths.equals(expectedPaths),"page_release_image_inventory");
        return manifest;
    }
    public static Map<String,Object> entrypoint(Map<String,Object> metadata,Files files,String projection)throws Exception{
        Map<String,Object> publication=obj(metadata,"publication");
        require(files.packageFiles().containsKey(ENTRYPOINT),"page_release_entrypoint");
        byte[] payload=files.packageFiles().get(ENTRYPOINT);
        require(sha(payload).equals(str(metadata,"content_sha256")),"page_release_content_substitution");
        Map<String,Object> content=decodeContent(payload);
        require(str(obj(content,"page"),"target").equals(projection),"page_release_content_substitution");
        return content;
    }

    static Target validateTarget(Map<String,Object> target,Map<String,Object> planTarget,Map<String,Object> revision,
                                 String revisionHash)throws Exception{
        exact(target,"device_id","projection","destination","configuration","metadata");
        String device=identifier(str(target,"device_id"),128);
        require(device.equals(str(planTarget,"device_id")),"page_release_target_substitution");
        Map<String,Object> configuration=obj(target,"configuration");
        exact(configuration,"version","profile_id","revision","mode");
        require(signed(configuration.get("version"))==1&&positive(configuration.get("revision"))>=1,"page_release_configuration");
        String profile=identifier(str(configuration,"profile_id"),64);
        String mode=str(configuration,"mode");require("tv".equals(mode)||"kiosk".equals(mode),"page_release_mode");
        require(profile.equals(str(planTarget,"profile_id"))&&positive(configuration.get("revision"))==positive(planTarget.get("profile_version"))
            &&mode.equals(str(planTarget,"mode"))
            &&sha(PublisherAuthority.canonical(configuration)).equals(str(planTarget,"configuration_sha256")),
            "page_release_configuration_substitution");
        String projection=str(target,"projection"),destination=str(target,"destination");
        require(DESTINATIONS.contains(destination)&&destination.equals(str(planTarget,"destination"))
            &&PROJECTIONS.contains(projection)&&projection.equals(str(planTarget,"projection"))
            &&projection.startsWith(mode+"-"),"page_release_target_substitution");
        Map<String,Object> metadata=obj(target,"metadata");
        Map<String,Object> publication=validateMetadata(metadata);
        require(str(metadata,"destination").equals(destination)&&str(metadata,"revision_sha256").equals(revisionHash)
            &&sha(PublisherAuthority.canonical(metadata)).equals(str(planTarget,"metadata_sha256"))
            &&str(obj(publication,"renderer"),"build_id").equals(str(planTarget,"renderer")),
            "page_release_metadata_substitution");
        Map<String,Object> content=projectTarget(revision,device,projection);
        require(str(obj(content,"page"),"target").equals(projection)
            &&sha(PublisherAuthority.canonical(content)).equals(str(metadata,"content_sha256")),
            "page_release_content_substitution");
        return new Target(target,device,projection,destination,configuration,metadata);
    }
    public static void checkAncestry(Map<String,Object> current,Set<String> heads,List<Object> ancestry)throws Exception{
        require(heads.size()<=32&&ancestry.size()<=MAX_ANCESTRY_NODES,"publisher_ancestry_limit");
        require(PublisherAuthority.canonical(Map.of("nodes",ancestry)).length<=MAX_ANCESTRY,"publisher_ancestry_limit");
        for(String head:heads)digest(head);
        Map<String,Map<String,Object>> nodes=new HashMap<>();
        for(Object item:ancestry){
            require(item instanceof Map,"publisher_ancestry_refused");
            Map<String,Object> prior=map(item);
            require(signed(prior.get("version"))==PLAN_VERSION,"publisher_ancestry_version");
            validatePlan(prior,signed(prior.get("issued")));
            String identity=str(prior,"id");
            require(!nodes.containsKey(identity)&&!identity.equals(str(current,"id"))
                &&str(prior,"group_id").equals(str(current,"group_id"))&&str(prior,"origin").equals(str(current,"origin"))
                &&signed(prior.get("issued"))<=signed(current.get("issued")),"publisher_ancestry_refused");
            nodes.put(identity,prior);
        }
        Set<String> reached=new HashSet<>();reached.add(str(current,"id"));
        ArrayDeque<String> pending=new ArrayDeque<>();for(Object item:arr(current,"parents"))pending.push(text(item));
        boolean missing=false;
        while(!pending.isEmpty()){
            String identity=pending.pop();if(!reached.add(identity))continue;
            Map<String,Object> prior=nodes.get(identity);
            if(prior!=null)for(Object parent:arr(prior,"parents"))pending.push(text(parent));
            else if(!heads.contains(identity))missing=true;
        }
        require(reached.containsAll(heads),missing?"publisher_ancestry_required":"publisher_known_conflict");
    }
    public static boolean scopeAllows(Map<String,Object> grant,Map<String,Object> plan)throws Exception{
        if(!grant.containsKey("scope"))return true;
        Map<String,Object> scope=obj(grant,"scope");
        if(!arr(scope,"groups").contains(str(plan,"group_id")))return false;
        Set<String> targets=new HashSet<>();for(Object item:arr(scope,"targets"))targets.add(text(item));
        for(Object item:arr(plan,"targets"))if(!targets.contains(str(map(item),"device_id")))return false;
        return true;
    }
    public static Map<String,Object> validateDocument(Map<String,Object> document,long now,Set<String> heads,
                                                      Map<String,Files> files)throws Exception{
        exact(document,"version","plan","revision","targets","ancestry");
        require(signed(document.get("version"))==PLAN_VERSION,"page_release_document_version");
        Map<String,Object> revision=validateRevision(obj(document,"revision"));
        String revisionHash=revisionSha256(revision);
        require(PublisherAuthority.canonical(document).length<=MAX_DOCUMENT,"page_release_document_limit");
        Map<String,Object> plan=validatePlan(obj(document,"plan"),now);
        require(str(plan,"revision_sha256").equals(revisionHash)
            &&str(plan,"dependencies_sha256").equals(sha(PublisherAuthority.canonical(obj(revision,"objects")))),
            "page_release_revision_substitution");
        List<Object> ancestry=arr(document,"ancestry");checkAncestry(plan,heads,ancestry);
        List<Object> targets=arr(document,"targets");require(!targets.isEmpty()&&targets.size()<=100,"page_release_target_limit");
        List<String> identities=new ArrayList<>();
        for(Object item:targets){Map<String,Object> target=map(item);exact(target,"device_id","projection","destination","configuration","metadata");identities.add(str(target,"device_id"));}
        List<String> sorted=new ArrayList<>(new TreeSet<>(identities));
        require(identities.equals(sorted),"page_release_target_ambiguity");
        Map<String,Map<String,Object>> planTargets=new TreeMap<>();
        for(Object item:arr(plan,"targets")){Map<String,Object> target=map(item);require(planTargets.put(str(target,"device_id"),target)==null,"page_release_target_ambiguity");}
        require(planTargets.keySet().equals(new HashSet<>(identities)),"page_release_target_set");
        for(Object item:targets){
            Map<String,Object> target=map(item);
            validateTarget(target,planTargets.get(str(target,"device_id")),revision,revisionHash);
        }
        if(files!=null){
            require(files.keySet().equals(new HashSet<>(identities)),"page_release_files");
            for(Object item:targets){
                Map<String,Object> target=map(item),metadata=obj(target,"metadata");
                Files targetFiles=files.get(str(target,"device_id"));
                Map<String,Object> publication=obj(metadata,"publication");
                verifyInventory(publication,targetFiles);
                Map<String,Object> content=entrypoint(metadata,targetFiles,str(target,"projection"));
                Map<String,Object> expected=projectTarget(revision,str(target,"device_id"),str(target,"projection"));
                require(Arrays.equals(PublisherAuthority.canonical(content),PublisherAuthority.canonical(expected)),
                    "page_release_content_substitution");
            }
        }
        return document;
    }
    public static Map<String,Object> review(Map<String,Object> document,long now,Set<String> heads,
                                            Map<String,Files> files)throws Exception{
        validateDocument(document,now,heads,files);return obj(document,"plan");
    }
    /** Independent review of one exact target package; all targets are still re-derived first. */
    public static Map<String,Object> reviewTarget(Map<String,Object> document,String deviceId,long now,
            Set<String> heads,Files files,String jsSha256,String cssSha256)throws Exception{
        validateDocument(document,now,heads,null);
        identifier(deviceId,128);require(files!=null,"page_release_inventory");
        Map<String,Object> target=null;
        for(Object item:arr(document,"targets")){Map<String,Object> candidate=map(item);
            if(deviceId.equals(str(candidate,"device_id"))){require(target==null,"page_release_target_ambiguity");target=candidate;}}
        require(target!=null,"page_release_target_substitution");
        Map<String,Object> metadata=obj(target,"metadata"),publication=obj(metadata,"publication");
        Map<String,Object> content=entrypoint(metadata,files,str(target,"projection"));
        verifyInventory(publication,files);
        checkLocalRenderer(metadata,jsSha256,cssSha256);
        Map<String,Object> expected=projectTarget(obj(document,"revision"),deviceId,str(target,"projection"));
        require(Arrays.equals(PublisherAuthority.canonical(content),PublisherAuthority.canonical(expected)),
            "page_release_content_substitution");
        Map<String,Object> result=new LinkedHashMap<>();
        result.put("document",document);result.put("target",target);result.put("content",content);
        return result;
    }
    public static void checkLocalRenderer(Map<String,Object> metadata,String jsSha256,String cssSha256)throws Exception{
        digest(jsSha256);digest(cssSha256);
        Map<String,Object> renderer=obj(obj(metadata,"publication"),"renderer");
        require(str(renderer,"js_sha256").equals(jsSha256)&&str(renderer,"css_sha256").equals(cssSha256)
            &&str(renderer,"build_id").equals(rendererBuildId(jsSha256,cssSha256)),"page_release_renderer_mismatch");
    }

    /**
     * Re-derive every target fact available in the approved v4 assignment and
     * re-hash the exact data-only package under the caller's lease. The v4 wire
     * does not carry the frozen revision graph, so target content is bound by the
     * signed metadata content hash, plan target, projection and package closure.
     */
    public static Map<String,Object> recheck(PageAdmission admission,Files files,
                                             String jsSha256,String cssSha256)throws Exception{
        require(admission!=null&&admission.plan()!=null&&admission.target()!=null
            &&admission.metadata()!=null,"page_release_assignment");
        Map<String,Object> plan=validatePlan(admission.plan(),signed(admission.plan().get("issued")));
        Map<String,Object> target=admission.target();
        exact(target,"device_id","projection","destination","configuration","metadata");
        String device=identifier(str(target,"device_id"),128);
        Map<String,Object> planTarget=null;
        for(Object item:arr(plan,"targets")){
            Map<String,Object> candidate=map(item);
            if(str(candidate,"device_id").equals(device)){require(planTarget==null,"page_release_target_ambiguity");planTarget=candidate;}
        }
        require(planTarget!=null,"publisher_target_not_approved");
        Map<String,Object> configuration=obj(target,"configuration");
        exact(configuration,"version","profile_id","revision","mode");
        require(signed(configuration.get("version"))==1&&positive(configuration.get("revision"))>=1,"page_release_configuration");
        String profile=identifier(str(configuration,"profile_id"),64);
        String mode=str(configuration,"mode");require("tv".equals(mode)||"kiosk".equals(mode),"page_release_mode");
        require(profile.equals(str(planTarget,"profile_id"))
            &&positive(configuration.get("revision"))==positive(planTarget.get("profile_version"))
            &&mode.equals(str(planTarget,"mode"))
            &&sha(PublisherAuthority.canonical(configuration)).equals(str(planTarget,"configuration_sha256")),
            "page_release_configuration_substitution");
        String projection=str(target,"projection"),destination=str(target,"destination");
        require(DESTINATIONS.contains(destination)&&destination.equals(str(planTarget,"destination"))
            &&PROJECTIONS.contains(projection)&&projection.equals(str(planTarget,"projection"))
            &&projection.startsWith(mode+"-"),"page_release_target_substitution");
        Map<String,Object> metadata=obj(target,"metadata");
        if(admission.metadata()!=null)require(Arrays.equals(PublisherAuthority.canonical(admission.metadata()),
            PublisherAuthority.canonical(metadata)),"page_release_metadata_substitution");
        Map<String,Object> publication=validateMetadata(metadata);
        String revisionHash=digest(str(metadata,"revision_sha256"));
        require(str(plan,"revision_sha256").equals(revisionHash)
            &&str(metadata,"destination").equals(destination)
            &&sha(PublisherAuthority.canonical(metadata)).equals(str(planTarget,"metadata_sha256"))
            &&str(obj(publication,"renderer"),"build_id").equals(str(planTarget,"renderer")),
            "page_release_metadata_substitution");
        require(admission.destination().equals(destination)&&admission.projection().equals(projection)
            &&admission.packageId().equals(str(publication,"package_id"))
            &&admission.revision().equals(str(plan,"revision_sha256"))
            &&admission.renderer().equals(str(obj(publication,"renderer"),"build_id"))
            &&admission.metadataSha256().equals(sha(PublisherAuthority.canonical(metadata)))
            &&(admission.publication()==null||Arrays.equals(PublisherAuthority.canonical(admission.publication()),
                PublisherAuthority.canonical(publication))),"page_release_assignment");
        checkLocalRenderer(metadata,jsSha256,cssSha256);
        verifyInventory(publication,files);
        Map<String,Object> content=entrypoint(metadata,files,projection);
        require(sha(PublisherAuthority.canonical(content)).equals(admission.contentSha256()),
            "page_release_content_substitution");
        if(admission.content()!=null)require(Arrays.equals(PublisherAuthority.canonical(admission.content()),
            PublisherAuthority.canonical(content)),"page_release_content_substitution");
        return content;
    }

    static void proofMatches(Map<String,Object> proof,Map<String,Object> assignment)throws Exception{
        require(assignment.get("publisher") instanceof Map,"page_release_proof_substitution");
        require(Arrays.equals(PublisherAuthority.canonical(proof),PublisherAuthority.canonical(map(assignment.get("publisher")))),
            "page_release_proof_substitution");
    }
    public static PageAdmission pageAssignment(Map<String,Object> proof,Map<String,Object> assignment,PublicKey root,
                                               String trustedOrigin,long now,long policyFloor,Set<String> heads)throws Exception{
        if(proof.containsKey("ancestry"))exact(proof,"approval","chain","policy","ancestry");
        else exact(proof,"approval","chain","policy");
        exact(assignment,"version","group_id","device_id","profile","generation","revision_sha256","destination",
            "projection","metadata_sha256","metadata","display","publisher");
        proofMatches(proof,assignment);
        String group=str(assignment,"group_id");
        Map<String,Object> policy=PublisherAuthority.policy(obj(proof,"policy"),root,group,trustedOrigin,now,policyFloor);
        PublisherAuthority.Permission permission=PublisherAuthority.permission(arr(proof,"chain"),root,policy,now);
        Map<String,Object> plan=validatePlan(pageVerified(obj(proof,"approval"),permission.key()),now);
        require(str(plan,"group_id").equals(group)&&str(plan,"origin").equals(trustedOrigin)
            &&str(plan,"user_id").equals(str(permission.grant(),"user_id"))
            &&str(plan,"device_id").equals(PublisherAuthority.keyId(permission.key()))
            &&signed(plan.get("policy_version"))==signed(policy.get("version"))
            &&signed(plan.get("issued"))>=signed(permission.grant().get("issued"))
            &&signed(plan.get("expires"))<=signed(permission.grant().get("expires")),"publisher_approval_scope");
        require(scopeAllows(permission.grant(),plan),"publisher_scope_refused");
        checkAncestry(plan,heads,proof.containsKey("ancestry")?arr(proof,"ancestry"):List.of());
        require(signed(assignment.get("version"))==ASSIGNMENT_VERSION,"publisher_assignment_version");
        identifier(str(assignment,"group_id"),128);identifier(str(assignment,"device_id"),128);
        identifier(str(assignment,"profile"),64);positive(assignment.get("generation"));
        String revisionHash=digest(str(assignment,"revision_sha256"));
        String destination=str(assignment,"destination"),projection=str(assignment,"projection");
        require(DESTINATIONS.contains(destination)&&PROJECTIONS.contains(projection),"publisher_target_not_approved");
        digest(str(assignment,"metadata_sha256"));
        Map<String,Object> metadata=obj(assignment,"metadata");
        Map<String,Object> publication=validateMetadata(metadata);
        require(group.equals(str(plan,"group_id"))&&revisionHash.equals(str(plan,"revision_sha256"))
            &&str(assignment,"metadata_sha256").equals(sha(PublisherAuthority.canonical(metadata))),"publisher_content_substitution");
        require(str(assignment,"profile").equals(str(publication,"resource_profile")),"publisher_configuration_substitution");
        Map<String,Object> matched=null;
        for(Object item:arr(plan,"targets")){
            Map<String,Object> candidate=map(item);
            if(str(candidate,"device_id").equals(str(assignment,"device_id"))){require(matched==null,"publisher_target_ambiguity");matched=candidate;}
        }
        require(matched!=null,"publisher_target_not_approved");
        require(str(matched,"destination").equals(destination)&&str(matched,"projection").equals(projection)
            &&str(matched,"metadata_sha256").equals(str(assignment,"metadata_sha256")),"publisher_target_substitution");
        require(str(metadata,"revision_sha256").equals(str(plan,"revision_sha256"))
            &&str(metadata,"destination").equals(str(matched,"destination"))
            &&str(publication,"revision").equals(str(plan,"revision_sha256")),"publisher_content_substitution");
        require(str(obj(publication,"renderer"),"build_id").equals(str(matched,"renderer")),"publisher_renderer_substitution");
        Map<String,Object> display=obj(assignment,"display");
        exact(display,"version","profile_id","revision","mode");
        require(signed(display.get("version"))==1&&positive(display.get("revision"))>=1,"publisher_configuration_substitution");
        String mode=str(display,"mode");require("tv".equals(mode)||"kiosk".equals(mode),"publisher_configuration_substitution");
        identifier(str(display,"profile_id"),64);
        require(str(matched,"profile_id").equals(str(display,"profile_id"))
            &&positive(matched.get("profile_version"))==positive(display.get("revision"))
            &&str(matched,"mode").equals(mode)
            &&str(matched,"configuration_sha256").equals(sha(PublisherAuthority.canonical(display)))
            &&projection.startsWith(mode+"-"),"publisher_configuration_substitution");
        Map<String,Object> target=new LinkedHashMap<>();
        target.put("device_id",str(assignment,"device_id"));target.put("projection",projection);
        target.put("destination",destination);target.put("configuration",display);target.put("metadata",metadata);
        return new PageAdmission(plan,target,policy,metadata,publication,null,str(publication,"package_id"),
            str(plan,"revision_sha256"),destination,projection,str(obj(publication,"renderer"),"build_id"),
            str(metadata,"content_sha256"),sha(PublisherAuthority.canonical(metadata)));
    }
    public static PageAdmission admit(Map<String,Object> proof,Map<String,Object> assignment,PublicKey root,
                                      String trustedOrigin,long now,Files files,String expectedGroup,String expectedDevice,
                                      String expectedProfile,String expectedDestination,String expectedJs,String expectedCss,
                                      long policyFloor,Set<String> heads)throws Exception{
        proofMatches(proof,assignment);
        try{
            identifier(expectedGroup,128);identifier(expectedDevice,128);identifier(expectedProfile,64);
        }catch(Refused refused){throw new Refused("page_release_local_identity");}
        require(PROFILE.equals(expectedProfile)&&DESTINATIONS.contains(expectedDestination),"page_release_local_identity");
        require(str(assignment,"group_id").equals(expectedGroup)&&str(assignment,"device_id").equals(expectedDevice)
            &&str(assignment,"profile").equals(expectedProfile)&&str(assignment,"destination").equals(expectedDestination),
            "page_release_local_identity");
        PageAdmission admission=pageAssignment(proof,assignment,root,trustedOrigin,now,policyFloor,heads);
        checkLocalRenderer(admission.metadata(),expectedJs,expectedCss);
        verifyInventory(admission.publication(),files);
        Map<String,Object> content=entrypoint(admission.metadata(),files,admission.projection());
        return new PageAdmission(admission.plan(),admission.target(),admission.policy(),admission.metadata(),
            admission.publication(),content,admission.packageId(),admission.revision(),admission.destination(),
            admission.projection(),admission.renderer(),admission.contentSha256(),admission.metadataSha256());
    }
}
