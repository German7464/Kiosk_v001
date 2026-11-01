package org.kiosk.harness.packagecore;

import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import static org.kiosk.harness.packagecore.PackageFailure.Code.*;
import static org.kiosk.harness.packagecore.PackageJson.*;

final class PackageResources {
    private static final String SPACE="[\\u0009-\\u000d\\u001c-\\u0020\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]";
    static final Set<String> REQUIRED=Set.of("static/css/base.css","static/js/kiosk_home.js","static/js/kiosk_events.js",
        "static/js/tv.js","static/js/admin_flash.js","static/img/site_icon.png","templates/base.html",
        "templates/kiosk_home.html","templates/kiosk_events.html","templates/tv.html",
        "translations/en.json","translations/ru.json","translations/de.json");
    static Set<String> references(Map<String,Object> data) throws PackageFailure {
        Set<String> result=new HashSet<>();
        for(Object value:array(data.get("events"),invalid_public_data)){
            Map<String,Object> event=object(value,invalid_public_data);
            for(String field:Set.of("image_kiosk","image_tv","image_thumb"))add(result,event.get(field));
        }
        add(result,object(data.get("settings"),invalid_public_data).get("site_icon"));
        return result;
    }
    private static void add(Set<String> refs,Object value) throws PackageFailure {
        if(value==null||value.equals(""))return;
        String reference=string(value,unsupported_media_reference);
        if(!reference.startsWith("/static/uploads/"))throw PackageFailure.fail(unsupported_media_reference);
        String name=reference.substring(1);
        if(!PackageInventory.safe(name))throw PackageFailure.fail(unsafe_path);
        refs.add(name);
    }
    static void closure(Set<String> inventory,Set<String> references) throws PackageFailure {
        // Python attempts referenced media before exact closure; a missing media path wraps to invalid_package.
        if(!inventory.containsAll(references))throw PackageFailure.fail(invalid_package);
        Set<String> expected=new HashSet<>(references);expected.add("data/events.json");
        for(String name:REQUIRED)expected.add("resources/"+name);
        if(!expected.equals(inventory))throw PackageFailure.fail(reference_closure_failure);
    }
    static void check(Map<String,byte[]> payloads) throws Exception {
        for(var entry:payloads.entrySet()){
            String name=entry.getKey();byte[] bytes=entry.getValue();
            if(name.startsWith("resources/translations/")){
                Map<String,Object> translations=object(PackageJson.parse(bytes),invalid_translation_resource);
                for(Object value:translations.values())string(value,invalid_translation_resource);
            }
            if(name.endsWith(".css")&&Pattern.compile("@[iI\u0130\u0131][mM][pP][oO][rR][tT]|[uU][rR][lL]"+SPACE+"*\\(").matcher(text(bytes)).find())
                throw PackageFailure.fail(unsupported_css_dependency);
            // Python's bytes regex uses ASCII word/space semantics and is case-sensitive.
            if(name.endsWith(".js")&&Pattern.compile("(?<![A-Za-z0-9_])import[ \\t\\n\\r\\f\\x0b]*(?:\\(|[A-Za-z0-9_*{])|(?<![A-Za-z0-9_])require[ \\t\\n\\r\\f\\x0b]*\\(").matcher(new String(bytes,StandardCharsets.ISO_8859_1)).find())
                throw PackageFailure.fail(unsupported_script_dependency);
            if(name.startsWith("resources/templates/")){
                dependencies(text(bytes),"\\{%\\s*(?:extends|include)\\s+['\"]([^'\"]+)['\"]","resources/templates/",payloads,missing_display_template);
                dependencies(text(bytes),"filename=['\"]([^'\"]+)['\"]","resources/static/",payloads,missing_display_resource);
            }
        }
    }
    private static void dependencies(String text,String regex,String prefix,Map<String,byte[]> payloads,PackageFailure.Code code) throws PackageFailure {
        Matcher matcher=Pattern.compile(regex.replace("\\s",SPACE)).matcher(text);
        while(matcher.find())if(!payloads.containsKey(prefix+matcher.group(1)))throw PackageFailure.fail(code);
    }
    private static String text(byte[] bytes) throws Exception {
        String value=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
        return value.startsWith("\ufeff")?value.substring(1):value;
    }
}
