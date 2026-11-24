package org.kiosk.harness.packagecore;

import java.math.BigInteger;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import static org.kiosk.harness.packagecore.PackageFailure.Code.*;
import static org.kiosk.harness.packagecore.PackageJson.*;

final class PackageSchema {
    static final Set<String> SETTINGS=Set.of("site_title","interface_language","site_icon","tv_slide_duration","kiosk_label","kiosk_heading","kiosk_description");
    private static final Set<String> EVENT=Set.of("id","title","short_description","full_description","event_date","place","image_kiosk","image_tv","image_thumb","sort_order","tag_ids");
    static void manifest(Map<String,Object> manifest) throws PackageFailure {
        if(!BigInteger.ONE.equals(integer(manifest.get("schema_version"),invalid_package))
            || !"events-v1".equals(manifest.get("renderer")))throw PackageFailure.fail(invalid_package);
        String revision=string(manifest.get("revision"),invalid_package);
        if(revision.isEmpty()||revision.codePointCount(0,revision.length())>128)throw PackageFailure.fail(invalid_package);
    }
    static BigInteger data(Map<String,Object> data) throws PackageFailure {
        if(!data.keySet().equals(Set.of("content_version","events","tags","settings")))throw PackageFailure.fail(invalid_public_data);
        BigInteger version=positive(data.get("content_version"));
        Map<String,Object> settings=object(data.get("settings"),invalid_public_data);
        if(!SETTINGS.containsAll(settings.keySet()))throw PackageFailure.fail(invalid_public_data);
        for(Object value:settings.values())string(value,invalid_public_data);
        Set<BigInteger> tags=new HashSet<>(),events=new HashSet<>();
        for(Object value:array(data.get("tags"),invalid_public_data)) {
            Map<String,Object> tag=object(value,invalid_public_data);
            if(!tag.keySet().equals(Set.of("id","name"))||!tags.add(positive(tag.get("id"))))throw PackageFailure.fail(invalid_public_data);
            string(tag.get("name"),invalid_public_data);
        }
        for(Object value:array(data.get("events"),invalid_public_data)) {
            Map<String,Object> event=object(value,invalid_public_data);
            if(!event.keySet().equals(EVENT)||!events.add(positive(event.get("id"))))throw PackageFailure.fail(invalid_public_data);
            integer(event.get("sort_order"),invalid_public_data);
            for(String field:Set.of("title","short_description","full_description","place"))string(event.get(field),invalid_public_data);
            for(String field:Set.of("event_date","image_kiosk","image_tv","image_thumb"))if(event.get(field)!=null)string(event.get(field),invalid_public_data);
            Set<BigInteger> links=new HashSet<>();
            for(Object link:array(event.get("tag_ids"),invalid_public_data)) {
                BigInteger id=integer(link,invalid_public_data);
                if(!tags.contains(id)||!links.add(id))throw PackageFailure.fail(invalid_public_data);
            }
        }
        return version;
    }
    private static BigInteger positive(Object value) throws PackageFailure {
        BigInteger n=integer(value,invalid_public_data);if(n.signum()<1)throw PackageFailure.fail(invalid_public_data);return n;
    }
}
