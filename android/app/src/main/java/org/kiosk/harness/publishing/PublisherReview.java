package org.kiosk.harness.publishing;

import java.nio.charset.StandardCharsets;
import java.security.PublicKey;
import java.util.*;
import org.kiosk.harness.core.LocalView;
import static org.kiosk.harness.delivery.DeliveryJson.*;
import static org.kiosk.harness.delivery.DeliveryProtocol.*;

/**
 * Native trusted review of one prepared roaming publication.
 *
 * The reviewer recomputes the exact frozen-draft public data from the candidate
 * plan's own objects/settings/revision and compares it with the downloaded
 * data/events.json bytes. Only then may it produce the publication signature.
 * This is the Android counterpart of the Python mapping and is intentionally
 * independent of the server's export result.
 */
public final class PublisherReview {
    public static final int MAX_PUBLIC_DATA = 16*1024*1024;
    private static final Map<String,Integer> TEXT=Map.of("title",300,"short_description",4096,
        "full_description",16384,"event_date",64,"place",512);
    private static final Map<String,Integer> SETTINGS=Map.of("site_title",300,"interface_language",8,
        "site_icon",512,"tv_slide_duration",16,"kiosk_label",300,"kiosk_heading",300,
        "kiosk_description",2000);

    private PublisherReview() {}

    private static int compare(String left,String right){
        int l=0,r=0;
        while(l<left.length()&&r<right.length()){
            int lc=left.codePointAt(l),rc=right.codePointAt(r);
            if(lc!=rc)return Integer.compare(lc,rc);
            l+=Character.charCount(lc);r+=Character.charCount(rc);
        }
        return Integer.compare(left.length()-l,right.length()-r);
    }

    private static long eventId(String identity)throws Exception{
        need(identity.matches("[1-9][0-9]{0,9}"));
        long value=Long.parseLong(identity);
        need(value<=2147483647L);
        return value;
    }

    private static String text(Map<String,Object> payload,String name,int maximum)throws Exception{
        String value=str(payload,name);need(value.length()<=maximum&&value.indexOf('\0')<0);return value;
    }

    /** Deterministic mapping of exactly these frozen revisions; mirrors the Python module. */
    public static Map<String,Object> derive(Map<String,Object> objects,Map<String,Object> settings,
            long contentVersion)throws Exception{
        need(contentVersion>=1&&objects.size()>=1&&objects.size()<=1000);
        List<Object[]> active=new ArrayList<>();
        TreeSet<String> names=new TreeSet<>(PublisherReview::compare);
        for(var entry:objects.entrySet()){
            long number=eventId(entry.getKey());
            Map<String,Object> payload=obj(object(entry.getValue()),"payload");
            String status=str(payload,"status");
            need("active".equals(status)||"hidden".equals(status));
            if(!"active".equals(status))continue;
            for(var field:TEXT.entrySet()) {
                if(field.getKey().equals("event_date") && payload.containsKey("event_date") && payload.get("event_date")==null)continue;
                text(payload,field.getKey(),field.getValue());
            }
            need(!str(payload,"title").trim().isEmpty());
            List<Object> images=array(payload.get("images"));need(images.size()<=3);
            for(Object item:images){
                if(item==null && images.size()==3)continue;
                String image=string(item);
                need(image.startsWith("/static/uploads/")&&image.indexOf('\\')<0&&!image.contains(".."));
            }
            List<Object> tags=array(payload.get("tags"));need(tags.size()<=32);
            Set<String> unique=new HashSet<>();
            for(Object item:tags){
                String tag=string(item);need(unique.add(tag)&&!tag.trim().isEmpty()&&tag.length()<=128&&tag.indexOf('\0')<0);
                names.add(tag);
            }
            active.add(new Object[]{num(payload,"sort_order"),payload.get("event_date")==null?"":str(payload,"event_date"),number,payload});
        }
        active.sort((left,right)->{
            int order=Long.compare((Long)left[0],(Long)right[0]);
            if(order!=0)return order;
            order=compare((String)left[1],(String)right[1]);
            return order!=0?order:Long.compare((Long)left[2],(Long)right[2]);
        });
        Map<String,Long> tagIds=new LinkedHashMap<>();
        long index=1;
        for(String name:names)tagIds.put(name,index++);
        List<Object> events=new ArrayList<>();
        for(Object[] item:active){
            Map<String,Object> payload=object(item[3]);
            List<Object> images=array(payload.get("images"));
            String first=images.isEmpty()||images.get(0)==null?null:string(images.get(0));
            String kiosk=first;
            String tv=images.size()>1?(images.get(1)==null?null:string(images.get(1))):first;
            String thumb=images.size()>2?(images.get(2)==null?null:string(images.get(2))):first;
            List<Long> linked=new ArrayList<>();
            for(Object tag:array(payload.get("tags")))linked.add(tagIds.get(string(tag)));
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
        Map<String,Object> publicSettings=new LinkedHashMap<>();
        for(var entry:settings.entrySet()){
            Integer maximum=SETTINGS.get(entry.getKey());
            String value=entry.getValue() instanceof String?(String)entry.getValue():null;
            need(maximum!=null&&value!=null&&value.length()<=maximum&&value.indexOf('\0')<0);
            publicSettings.put(entry.getKey(),value);
        }
        List<Object> tags=new ArrayList<>();
        for(var entry:tagIds.entrySet()){
            Map<String,Object> tag=new LinkedHashMap<>();
            tag.put("id",entry.getValue());tag.put("name",entry.getKey());tags.add(tag);
        }
        Map<String,Object> data=new LinkedHashMap<>();
        data.put("content_version",contentVersion);data.put("events",events);
        data.put("tags",tags);data.put("settings",publicSettings);
        return data;
    }

    /** Validate the candidate binding; returns the exact plan that may be signed. */
    public static Map<String,Object> verify(Map<String,Object> document,byte[] publicData,long now,
            Set<String> heads,PublicKey expected)throws Exception{
        Map<String,Object> plan=PublisherAuthority.plan(obj(document,"plan"),now);
        Map<String,Object> objects=obj(document,"objects");
        long version=num(document,"content_version");
        Map<String,Object> derived=derive(objects,obj(document,"settings"),version);
        Map<String,Object> actual=object(parse(publicData,MAX_PUBLIC_DATA));
        need(Arrays.equals(PublisherAuthority.canonical(derived),PublisherAuthority.canonical(actual)));
        Map<String,Object> metadata=obj(document,"publication");
        need(str(metadata,"revision").equals(Long.toString(version)));
        Map<String,Object> dataEntry=null;
        for(Object item:array(obj(metadata,"package").get("files"))){
            Map<String,Object> entry=object(item);
            if("data/events.json".equals(str(entry,"path"))){need(dataEntry==null);dataEntry=entry;}
        }
        need(dataEntry!=null&&num(dataEntry,"size")==publicData.length);
        need(str(dataEntry,"sha256").equals(LocalView.digest(publicData)));
        need(LocalView.digest(PublisherAuthority.canonical(metadata)).equals(str(plan,"publication_sha256")));
        need(str(obj(metadata,"renderer"),"build_id").equals(str(plan,"renderer")));
        need(LocalView.digest(PublisherAuthority.canonical(objects)).equals(str(plan,"dependencies_sha256")));
        if(expected!=null)need(PublisherAuthority.keyId(expected).equals(str(plan,"device_id")));
        PublisherAuthority.checkAncestry(plan,heads,
            document.containsKey("ancestry")?array(document.get("ancestry")):List.of());
        return plan;
    }

    /** One explicit Publish: verify exact bytes, then sign exactly this plan. */
    public static Map<String,Object> approve(PublisherKey key,Map<String,Object> document,
            byte[] publicData,long now,Set<String> heads)throws Exception{
        Map<String,Object> plan=verify(document,publicData,now,heads,key.publicKey());
        return PublisherEnvelope.sign(key,"publication",plan);
    }

    /** Independent v2 review: closure, exact bytes, target projection and pinned renderer. */
    public static Map<String,Object> reviewPage(Map<String,Object> document,
            Map<String,org.kiosk.harness.delivery.PageReleaseProtocol.Files> files,long now,Set<String> heads,
            String rendererJs,String rendererCss)throws Exception{
        Map<String,Object> plan=org.kiosk.harness.delivery.PageReleaseProtocol.review(document,now,heads,files);
        for(Object item:array(document.get("targets"))){
            Map<String,Object> target=object(item);
            org.kiosk.harness.delivery.PageReleaseProtocol.checkLocalRenderer(obj(target,"metadata"),rendererJs,rendererCss);
        }
        return plan;
    }

    /**
     * Structural v2 review for a native publisher that has the immutable document but no
     * transport bytes. The frozen revision, dependency closure, every target projection,
     * signed metadata and pinned renderer are re-derived; the client verifies bytes on activation.
     */
    public static Map<String,Object> reviewPageDocument(Map<String,Object> document,long now,Set<String> heads,
            String rendererJs,String rendererCss)throws Exception{
        Map<String,Object> plan=org.kiosk.harness.delivery.PageReleaseProtocol.review(document,now,heads,null);
        for(Object item:array(document.get("targets"))){
            Map<String,Object> target=object(item);
            org.kiosk.harness.delivery.PageReleaseProtocol.checkLocalRenderer(obj(target,"metadata"),rendererJs,rendererCss);
        }
        return plan;
    }

    /** Exact package bytes for one target; the full document is re-derived first. */
    public static Map<String,Object> reviewPageTarget(Map<String,Object> document,String deviceId,
            org.kiosk.harness.delivery.PageReleaseProtocol.Files files,long now,Set<String> heads,
            String rendererJs,String rendererCss)throws Exception{
        return org.kiosk.harness.delivery.PageReleaseProtocol.reviewTarget(document,deviceId,now,heads,
            files,rendererJs,rendererCss);
    }

    /** Exact immutable facts for the single explicit page Publish; no draft text or paths. */
    public static Map<String,Object> pageReviewSummary(Map<String,Object> document,
            Map<String,org.kiosk.harness.delivery.PageReleaseProtocol.Files> files,long now,Set<String> heads,
            String rendererJs,String rendererCss)throws Exception{
        return pageReviewFacts(document,reviewPage(document,files,now,heads,rendererJs,rendererCss));
    }

    /** Same immutable summary without requiring every target package in memory. */
    public static Map<String,Object> pageReviewSummary(Map<String,Object> document,long now,Set<String> heads,
            String rendererJs,String rendererCss)throws Exception{
        return pageReviewFacts(document,reviewPageDocument(document,now,heads,rendererJs,rendererCss));
    }

    private static Map<String,Object> pageReviewFacts(Map<String,Object> document,Map<String,Object> plan)throws Exception{
        Map<String,Object> revisionPlan=obj(obj(document,"revision"),"plan");
        List<Object> included=new ArrayList<>(),excluded=new ArrayList<>();
        for(Object item:array(revisionPlan.get("included"))){Map<String,Object> entry=object(item);
            Map<String,Object> row=new LinkedHashMap<>();row.put("id",str(entry,"id"));
            row.put("version",num(entry,"version"));row.put("author",str(entry,"author"));included.add(row);}
        for(Object item:array(revisionPlan.get("excluded"))){Map<String,Object> entry=object(item);
            Map<String,Object> row=new LinkedHashMap<>();row.put("id",str(entry,"id"));
            row.put("version",num(entry,"version"));row.put("author",str(entry,"author"));
            row.put("reason",str(entry,"reason"));excluded.add(row);}
        Map<String,Map<String,Object>> planTargets=new LinkedHashMap<>();
        for(Object item:array(plan.get("targets"))){Map<String,Object> target=object(item);
            planTargets.put(str(target,"device_id"),target);}
        List<Object> targets=new ArrayList<>();
        for(Object item:array(document.get("targets"))){Map<String,Object> target=object(item);
            Map<String,Object> signed=planTargets.get(str(target,"device_id"));
            need(signed!=null);
            Map<String,Object> configuration=obj(target,"configuration"),metadata=obj(target,"metadata");
            Map<String,Object> publication=obj(metadata,"publication"),renderer=obj(publication,"renderer");
            Map<String,Object> row=new LinkedHashMap<>();row.put("device_id",str(target,"device_id"));
            row.put("projection",str(target,"projection"));row.put("destination",str(target,"destination"));
            row.put("profile_id",str(configuration,"profile_id"));row.put("profile_version",num(configuration,"revision"));
            row.put("mode",str(configuration,"mode"));row.put("configuration_sha256",str(signed,"configuration_sha256"));
            row.put("metadata_sha256",str(signed,"metadata_sha256"));row.put("content_sha256",str(metadata,"content_sha256"));
            row.put("renderer",str(signed,"renderer"));row.put("package_id",str(publication,"package_id"));
            row.put("raw_manifest_sha256",str(publication,"raw_manifest_sha256"));
            row.put("renderer_js_sha256",str(renderer,"js_sha256"));
            row.put("renderer_css_sha256",str(renderer,"css_sha256"));targets.add(row);}
        Map<String,Object> summary=new LinkedHashMap<>();summary.put("plan_id",str(plan,"id"));
        summary.put("revision_sha256",str(plan,"revision_sha256"));summary.put("policy_version",num(plan,"policy_version"));
        summary.put("group_id",str(plan,"group_id"));summary.put("user_id",str(plan,"user_id"));
        summary.put("publisher_device_id",str(plan,"device_id"));summary.put("issued",num(plan,"issued"));
        summary.put("expires",num(plan,"expires"));summary.put("parents",array(plan.get("parents")));
        summary.put("included",included);
        summary.put("excluded",excluded);summary.put("targets",targets);return summary;
    }

    /** One explicit page Publish: review exact bytes, then sign exactly this v2 plan. */
    public static Map<String,Object> approvePage(PublisherKey key,Map<String,Object> document,
            Map<String,org.kiosk.harness.delivery.PageReleaseProtocol.Files> files,long now,Set<String> heads,
            String rendererJs,String rendererCss)throws Exception{
        Map<String,Object> plan=reviewPage(document,files,now,heads,rendererJs,rendererCss);
        need(str(plan,"device_id").equals(PublisherAuthority.keyId(key.publicKey())));
        return PublisherEnvelope.signPage(key,plan);
    }

    public static byte[] utf8(String value){return value.getBytes(StandardCharsets.UTF_8);}
}
