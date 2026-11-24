package org.kiosk.harness.publishing;

import java.nio.charset.StandardCharsets;
import java.security.*;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.X509EncodedKeySpec;
import java.util.*;
import org.kiosk.harness.delivery.DeliveryJson;
import static org.kiosk.harness.delivery.DeliveryJson.*;
import static org.kiosk.harness.delivery.DeliveryProtocol.*;
import org.kiosk.harness.core.LocalView;

/** Pure bounded roaming-publish-v1 verifier; no server account/credential authority. */
public final class PublisherAuthority {
    public static final byte[] DOMAIN="Kiosk/RoamingPublish/v1\0".getBytes(StandardCharsets.US_ASCII);
    // Administrator maintenance at day90, with a bounded fourteen-day overlap.
    public static final long AUTHORITY_VALIDITY_SECONDS=(90L+14L)*86400L;
    public record Permission(Map<String,Object> grant,PublicKey key){}
    public record Admission(Map<String,Object> plan,long policyVersion){}
    private static long positive(Map<String,Object> m,String k)throws Exception{long v=num(m,k);need(v>0);return v;}
    private static void validity(Map<String,Object> m,long now,long maximum)throws Exception{
        long issued=positive(m,"issued"),expires=positive(m,"expires");
        need(issued<=now&&now<expires&&expires-issued<=maximum);
    }
    public static PublicKey publicKey(String encoded)throws Exception{
        byte[] raw=b64(encoded,1024);
        PublicKey key=KeyFactory.getInstance("RSA").generatePublic(new X509EncodedKeySpec(raw));
        need(key instanceof RSAPublicKey);
        RSAPublicKey rsa=(RSAPublicKey)key;
        need(rsa.getModulus().bitLength()==3072&&rsa.getPublicExponent().intValue()==65537);
        need(Arrays.equals(raw,key.getEncoded()));return key;
    }
    public static String keyId(PublicKey key){return LocalView.digest(key.getEncoded());}

    /** Existing JSON wire format with Python-compatible escapes. Keys are protocol
     * ASCII; arbitrary user text is UTF-8, never executable input. No floats. */
    public static byte[] canonical(Object value)throws Exception{return jsonText(value).getBytes(StandardCharsets.UTF_8);}
    private static String jsonText(Object value)throws Exception{
        if(value==null)return "null";
        if(value instanceof Map){
            Map<String,Object> map=object(value);ArrayList<String> names=new ArrayList<>(map.keySet());
            names.sort((left,right)->{
                int l=0,r=0;
                while(l<left.length()&&r<right.length()){
                    int lc=left.codePointAt(l),rc=right.codePointAt(r);
                    if(lc!=rc)return Integer.compare(lc,rc);
                    l+=Character.charCount(lc);r+=Character.charCount(rc);
                }return Integer.compare(left.length()-l,right.length()-r);
            });StringJoiner out=new StringJoiner(",","{","}");
            for(String k:names)out.add(jsonText(k)+":"+jsonText(map.get(k)));return out.toString();
        }
        if(value instanceof List){StringJoiner out=new StringJoiner(",","[","]");for(Object item:(List<?>)value)out.add(jsonText(item));return out.toString();}
        if(value instanceof Boolean)return value.toString();
        if(value instanceof DeliveryJson.NumberToken){String n=((DeliveryJson.NumberToken)value).token();need(n.matches("-?(0|[1-9][0-9]*)"));return Long.toString(Long.parseLong(n));}
        if(value instanceof Long||value instanceof Integer)return value.toString();
        need(value instanceof String);String text=(String)value;StringBuilder out=new StringBuilder("\"");
        for(int i=0;i<text.length();i++){
            char c=text.charAt(i);
            if(Character.isHighSurrogate(c)){need(i+1<text.length()&&Character.isLowSurrogate(text.charAt(i+1)));out.append(c).append(text.charAt(++i));continue;}
            need(!Character.isLowSurrogate(c));
            switch(c){case '"':out.append("\\\"");break;case '\\':out.append("\\\\");break;
                case '\b':out.append("\\b");break;case '\f':out.append("\\f");break;
                case '\n':out.append("\\n");break;case '\r':out.append("\\r");break;case '\t':out.append("\\t");break;
                default:if(c<32)out.append(String.format(Locale.ROOT,"\\u%04x",(int)c));else out.append(c);
            }
        }return out.append('"').toString();
    }

    public static Map<String,Object> verified(Map<String,Object> envelope,PublicKey key,String kind)throws Exception{
        keys(envelope,"payload","signature");byte[] payload=b64(str(envelope,"payload"),32768),signature=b64(str(envelope,"signature"),384);
        need(signature.length==384);Signature verifier=Signature.getInstance("SHA256withRSA");
        verifier.initVerify(key);verifier.update(DOMAIN);verifier.update(payload);need(verifier.verify(signature));
        Map<String,Object> outer=object(DeliveryJson.parse(payload,32768));keys(outer,"kind","value","version");
        need(num(outer,"version")==1&&kind.equals(str(outer,"kind"))&&Arrays.equals(payload,canonical(outer)));
        return obj(outer,"value");
    }

    public static Map<String,Object> policy(Map<String,Object> envelope,PublicKey root,String group,String origin,long now,long floor)throws Exception{
        Map<String,Object> value=verified(envelope,root,"policy");
        keys(value,"group_id","origin","version","issued","expires","revoked_devices","revoked_users");
        need(group.equals(str(value,"group_id"))&&origin.equals(str(value,"origin"))&&positive(value,"version")>=floor);
        validity(value,now,AUTHORITY_VALIDITY_SECONDS);
        for(String field:List.of("revoked_devices","revoked_users")){
            List<Object> items=array(value.get(field));need(items.size()<=1024);
            Set<String> seen=new HashSet<>();for(Object item:items){String s=string(item);need(seen.add(s));if(field.equals("revoked_devices"))hash(s);else id(s);}
        }return value;
    }

    public static Permission permission(List<Object> chain,PublicKey root,Map<String,Object> policy,long now)throws Exception{
        need(chain.size()>=1&&chain.size()<=2);PublicKey signer=root;Map<String,Object> parent=null;
        Set<String> base=new HashSet<>(List.of("group_id","origin","user_id","role","device_key","issued","expires","can_delegate"));
        for(Object envelope:chain){
            Map<String,Object> value=verified(object(envelope),signer,"device");
            Set<String> names=new HashSet<>(value.keySet());boolean scoped=names.remove("scope");
            need(names.equals(base));
            Map<String,Object> scope=scoped?scope(object(value.get("scope"))):null;
            need(value.get("can_delegate") instanceof Boolean);
            need(str(value,"group_id").equals(str(policy,"group_id"))&&str(value,"origin").equals(str(policy,"origin")));
            id(str(value,"group_id"));id(str(value,"user_id"));need(List.of("user","administrator").contains(str(value,"role")));
            validity(value,now,AUTHORITY_VALIDITY_SECONDS);PublicKey next=publicKey(str(value,"device_key"));
            need(!array(policy.get("revoked_users")).contains(str(value,"user_id"))&&!array(policy.get("revoked_devices")).contains(keyId(next)));
            if(parent!=null){
                need(Boolean.TRUE.equals(parent.get("can_delegate"))&&Boolean.FALSE.equals(value.get("can_delegate")));
                need(str(value,"group_id").equals(str(parent,"group_id"))&&str(value,"origin").equals(str(parent,"origin")));
                boolean sameUser=str(value,"user_id").equals(str(parent,"user_id"));
                if(sameUser){
                    need(str(value,"role").equals(str(parent,"role")));
                }else{
                    // Only an administrator grant may enroll another account, and a
                    // child always carries an explicit non-widening scope.
                    need("administrator".equals(str(parent,"role"))&&scope!=null);
                }
                if(parent.containsKey("scope")&&scope!=null){
                    Map<String,Object> parentScope=object(parent.get("scope"));
                    need(new HashSet<>(array(parentScope.get("groups"))).containsAll(array(scope.get("groups"))));
                    need(new HashSet<>(array(parentScope.get("targets"))).containsAll(array(scope.get("targets"))));
                    need(new HashSet<>(array(parentScope.get("permissions"))).containsAll(array(scope.get("permissions"))));
                }
                need(num(value,"issued")>=num(parent,"issued")&&num(value,"expires")<=num(parent,"expires")&&!value.get("device_key").equals(parent.get("device_key")));
            }parent=value;signer=next;
        }return new Permission(parent,signer);
    }

    private static Map<String,Object> scope(Map<String,Object> value)throws Exception{
        keys(value,"version","groups","targets","permissions");
        need(num(value,"version")==1);
        String[][] limits={{"groups","64"},{"targets","64"},{"permissions","8"}};
        for(String[] limit:limits){
            List<Object> items=array(value.get(limit[0]));need(!items.isEmpty()&&items.size()<=Integer.parseInt(limit[1]));
            String prior="";
            for(Object item:items){String text=string(item);need(text.compareTo(prior)>0);prior=text;id(text);}
        }
        List<Object> permissions=array(value.get("permissions"));
        need(permissions.contains("publish"));
        for(Object item:permissions)need(List.of("edit","publish").contains(string(item)));
        return value;
    }

    public static Map<String,Object> plan(Map<String,Object> value,long now)throws Exception{
        keys(value,"id","group_id","origin","user_id","device_id","policy_version","issued","expires",
             "publication_sha256","dependencies_sha256","renderer","targets","parents");
        id(str(value,"group_id"));id(str(value,"user_id"));positive(value,"policy_version");validity(value,now,90*86400L);
        for(String f:List.of("id","device_id","publication_sha256","dependencies_sha256","renderer"))hash(str(value,f));
        List<Object> targets=array(value.get("targets"));need(targets.size()>=1&&targets.size()<=100);
        String prior="";
        for(Object item:targets){Map<String,Object> target=object(item);keys(target,"device_id","profile_id","profile_version","mode","configuration_sha256");
            String device=id(str(target,"device_id"));need(device.compareTo(prior)>0);prior=device;
            id(str(target,"profile_id"));positive(target,"profile_version");hash(str(target,"configuration_sha256"));need(List.of("tv","kiosk").contains(str(target,"mode")));
        }
        List<Object> parents=array(value.get("parents"));need(parents.size()<=32);prior="";
        for(Object item:parents){String identity=hash(string(item));need(identity.compareTo(prior)>0);prior=identity;}
        Map<String,Object> without=new TreeMap<>(value);without.remove("id");need(str(value,"id").equals(LocalView.digest(canonical(without))));
        return value;
    }

    /** Current signed parents are hashes of whole prior plans. These records
     * only prove ancestry, never resurrect expired/revoked signing authority. */
    public static void checkAncestry(Map<String,Object> current,Set<String> heads,List<Object> ancestry)throws Exception{
        if(heads.size()>32||ancestry.size()>128||canonical(Map.of("nodes",ancestry)).length>512*1024)
            refuse("publisher_ancestry_limit");
        for(String head:heads)hash(head);
        Map<String,Map<String,Object>> nodes=new HashMap<>();
        for(Object item:ancestry){
            var prior=object(item);plan(prior,positive(prior,"issued"));String identity=str(prior,"id");
            if(nodes.containsKey(identity)||identity.equals(str(current,"id"))||
                !str(prior,"group_id").equals(str(current,"group_id"))||!str(prior,"origin").equals(str(current,"origin"))||
                num(prior,"issued")>num(current,"issued"))refuse("publisher_ancestry_refused");
            nodes.put(identity,prior);
        }
        Set<String> reached=new HashSet<>();reached.add(str(current,"id"));
        ArrayDeque<String> pending=new ArrayDeque<>();
        for(Object item:array(current.get("parents")))pending.push(string(item));
        boolean missing=false;
        while(!pending.isEmpty()){
            String identity=pending.pop();if(!reached.add(identity))continue;
            var prior=nodes.get(identity);
            if(prior!=null){for(Object parent:array(prior.get("parents")))pending.push(string(parent));}
            else if(!heads.contains(identity))missing=true;
        }
        if(!reached.containsAll(heads))refuse(missing?"publisher_ancestry_required":"publisher_known_conflict");
    }

    public static Admission assignment(Map<String,Object> proof,Map<String,Object> assignment,PublicKey root,String origin,long now,long floor,Set<String> heads)throws Exception{
        if(proof.containsKey("ancestry"))keys(proof,"approval","chain","policy","ancestry");else keys(proof,"approval","chain","policy");
        String group=str(assignment,"group_id");
        Map<String,Object> policy=policy(obj(proof,"policy"),root,group,origin,now,floor);
        Permission permission=permission(array(proof.get("chain")),root,policy,now);
        Map<String,Object> plan=plan(verified(obj(proof,"approval"),permission.key(),"publication"),now);
        need(group.equals(str(plan,"group_id"))&&origin.equals(str(plan,"origin"))&&str(permission.grant(),"user_id").equals(str(plan,"user_id")));
        need(keyId(permission.key()).equals(str(plan,"device_id"))&&num(plan,"policy_version")==num(policy,"version"));
        need(num(plan,"issued")>=num(permission.grant(),"issued")&&num(plan,"expires")<=num(permission.grant(),"expires"));
        if(permission.grant().containsKey("scope")){
            Map<String,Object> scope=object(permission.grant().get("scope"));
            need(array(scope.get("groups")).contains(group));
            Set<String> allowed=new HashSet<>();
            for(Object item:array(scope.get("targets")))allowed.add(id(string(item)));
            for(Object item:array(plan.get("targets")))need(allowed.contains(id(str(object(item),"device_id"))));
        }
        checkAncestry(plan,heads,proof.containsKey("ancestry")?array(proof.get("ancestry")):List.of());
        Map<String,Object> publication=obj(assignment,"publication");
        need(LocalView.digest(canonical(publication)).equals(str(plan,"publication_sha256"))&&str(obj(publication,"renderer"),"build_id").equals(str(plan,"renderer")));
        Map<String,Object> match=null;
        for(Object item:array(plan.get("targets"))){Map<String,Object> t=object(item);if(str(t,"device_id").equals(str(assignment,"device_id"))){need(match==null);match=t;}}
        need(match!=null);Map<String,Object> display=obj(assignment,"display");
        need(str(match,"profile_id").equals(str(display,"profile_id"))&&num(match,"profile_version")==num(display,"revision")&&str(match,"mode").equals(str(display,"mode")));
        need(str(match,"configuration_sha256").equals(LocalView.digest(canonical(display))));
        return new Admission(plan,num(policy,"version"));
    }
}
