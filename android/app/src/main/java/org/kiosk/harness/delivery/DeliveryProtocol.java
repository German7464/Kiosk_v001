package org.kiosk.harness.delivery;

import java.io.*;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.security.cert.CertificateFactory;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.X509EncodedKeySpec;
import java.util.*;
import org.kiosk.harness.binding.*;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.storage.PreparedAdmission;
import static org.kiosk.harness.delivery.DeliveryJson.*;

/** Frozen device-delivery-v1 schema, distinct from the synthetic v0 prototype. */
public final class DeliveryProtocol {
    public static final String PROFILE="events-phone-lab-v1";
    public static final String BUILD="5913c239644a5b49cebeca375669a59bda739f14051f6bfbae62b3ec8047e2d1";
    // Same renderer code/assets, before the source-file/bytecode ID bug was fixed.
    // Signed metadata stays unchanged. Remove this alias on an actual renderer change.
    public static boolean rendererCompatible(String value){return BUILD.equals(value)||
        (BUILD.equals("5913c239644a5b49cebeca375669a59bda739f14051f6bfbae62b3ec8047e2d1")&&
         value.equals("b55c9bdc54af16ce69b6b6b6be15375adc5891dc70b84eb2292de00cd59d49a6"));}
    public static final String JS="839bb0c182822f7530e0d9c403b3ebddcfff214f871fb52c45d68a6dc68e6238";
    public static final String CSS="6c2be9997f2f817149b4cc9227091399336f066ab2762ccf542ca43d436b29f1";
    public record Bootstrap(String id,String group,String server,String origin,String ca,String keyId,PublicKey key,long issued,long expires){
        /** SHA-256 of the DER-encoded TLS root certificate; the offline-root fingerprint the operator must verify independently for first trust. */
        public String caFingerprint()throws Exception {
            var certs=CertificateFactory.getInstance("X.509").generateCertificates(new ByteArrayInputStream(ca.getBytes(StandardCharsets.US_ASCII)));
            need(certs.size()==1);
            return LocalView.digest(certs.iterator().next().getEncoded());
        }
    }
    public record Trust(long generation,long issued,long expires,String digest){}
    public record Assignment(long generation,String metadata,PreparedAdmission.Request request,DisplayProfile display){
        public Assignment(long generation,String metadata,PreparedAdmission.Request request){this(generation,metadata,request,DisplayProfile.legacy());}
    }
    public static void need(boolean valid)throws IOException {if(!valid)throw new IOException("delivery_refused");}
    /** A fixed, meaningful reason crosses the native UI boundary instead of a generic refusal. */
    public static void refuse(String code)throws IOException {throw new IOException(code);}
    public static Map<String,Object> json(byte[] bytes,int limit)throws Exception {return object(parse(bytes,limit));}
    public static Map<String,Object> obj(Map<String,Object> m,String k)throws Exception{return object(m.get(k));}
    public static String str(Map<String,Object> m,String k)throws Exception{return string(m.get(k));}
    public static long num(Map<String,Object> m,String k)throws Exception{return integer(m.get(k));}
    public static void version(Map<String,Object> m)throws Exception {need(num(m,"version")==1);}
    public static String id(String s)throws Exception{need(s.matches("[A-Za-z0-9_.-]{1,128}"));return s;}
    public static String hash(String s)throws Exception{need(s.matches("[a-f0-9]{64}"));return s;}
    public static byte[] b64(String s,int max)throws Exception{
        need(s.length()<=((max+2)/3)*4);byte[] b=Base64.getDecoder().decode(s);
        need(b.length<=max&&Base64.getEncoder().encodeToString(b).equals(s));return b;
    }
    /**
     * SHA-256 of the exact bootstrap bytes. Showing it is only useful when the operator compares it
     * with a value received through a separate trusted channel; the display alone authenticates nothing.
     */
    public static String bootstrapDigest(byte[] bytes){return LocalView.digest(bytes);}
    public static Bootstrap bootstrap(byte[] bytes,long now)throws Exception {
        var m=json(bytes,16384);keys(m,"version","bootstrap_id","group_id","server_id","origin","tls_ca_pem","group_key_id","group_spki_base64","issued_at","expires_at");version(m);
        String origin=str(m,"origin");URI uri=new URI(origin);
        need("https".equals(uri.getScheme())&&uri.getHost()!=null&&uri.getPort()>0&&uri.getRawUserInfo()==null&&uri.getRawQuery()==null&&uri.getRawFragment()==null&&"".equals(uri.getRawPath())&&origin.equals("https://"+uri.getHost()+":"+uri.getPort()));
        byte[] der=b64(str(m,"group_spki_base64"),1024);String keyId=hash(str(m,"group_key_id"));need(LocalView.digest(der).equals(keyId));
        PublicKey key=KeyFactory.getInstance("RSA").generatePublic(new X509EncodedKeySpec(der));
        need(key instanceof RSAPublicKey&&((RSAPublicKey)key).getModulus().bitLength()==3072&&((RSAPublicKey)key).getPublicExponent().equals(java.math.BigInteger.valueOf(65537)));
        long issued=num(m,"issued_at"),expires=num(m,"expires_at");need(issued<=now&&now<expires&&issued<expires);
        return new Bootstrap(id(str(m,"bootstrap_id")),id(str(m,"group_id")),id(str(m,"server_id")),origin,str(m,"tls_ca_pem"),keyId,key,issued,expires);
    }
    /** Envelope version decides the verifier: v1 keeps leaf-pin/old domain, v2 uses the issuer pin. Never inferred. */
    public static int envelopeVersion(byte[] bytes)throws Exception {
        var m=json(bytes,16384);long v=num(m,"version");need(v==1||v==2);return (int)v;
    }
    public record IssuerTrust(Trust trust,String issuerPin){}
    /**
     * lan-trust-lifecycle-v2 group trust: envelope/payload version 2, domain "Kiosk/GroupTrust/v2"+NUL,
     * ASCII canonical payload, and the pinned TLS issuer (intermediate) SPKI that may legitimately
     * rotate the serving leaf. A v1 envelope is refused here rather than reinterpreted.
     */
    public static IssuerTrust trustV2(byte[] bytes,Bootstrap b,String servedIssuer,long now,long prior,String priorDigest)throws Exception {
        var m=json(bytes,16384);keys(m,"version","key_id","algorithm","payload_base64","signature_base64");
        need(num(m,"version")==2);
        need(b.keyId.equals(str(m,"key_id"))&&"RSA3072-SHA256-PKCS1-v1_5".equals(str(m,"algorithm")));
        byte[] payload=b64(str(m,"payload_base64"),8192),sig=b64(str(m,"signature_base64"),384);need(sig.length==384);
        for(byte ch:payload)need(ch>=0);String text=new String(payload,StandardCharsets.US_ASCII);
        need(canonical(json(payload,8192)).equals(text));
        Signature verifier=Signature.getInstance("SHA256withRSA");verifier.initVerify(b.key);
        verifier.update("Kiosk/GroupTrust/v2\0".getBytes(StandardCharsets.US_ASCII));verifier.update(payload);need(verifier.verify(sig));
        var p=json(payload,8192);keys(p,"version","group_id","generation","issued_at","expires_at","servers");need(num(p,"version")==2);
        long gen=num(p,"generation"),issued=num(p,"issued_at"),expires=num(p,"expires_at");String digest=LocalView.digest(payload);
        need(b.group.equals(str(p,"group_id"))&&gen>0);
        need(gen>prior||(gen==prior&&digest.equals(priorDigest)));
        if(!(issued<=now&&now<expires&&issued<expires))refuse("authority_window_refused");
        var servers=array(p.get("servers"));need(servers.size()==1);var s=object(servers.get(0));
        keys(s,"server_id","origin","tls_issuer_spki_sha256","roles");
        String issuer=hash(str(s,"tls_issuer_spki_sha256"));
        need(b.server.equals(str(s,"server_id"))&&b.origin.equals(str(s,"origin"))&&array(s.get("roles")).equals(List.of("publisher")));
        need(issuer.matches("[a-f0-9]{64}")&&issuer.equals(servedIssuer));
        return new IssuerTrust(new Trust(gen,issued,expires,digest),issuer);
    }
    public static Trust trust(byte[] bytes,Bootstrap b,String peer,long now,long prior,String priorDigest)throws Exception {
        var m=json(bytes,16384);keys(m,"version","key_id","algorithm","payload_base64","signature_base64");version(m);
        need(b.keyId.equals(str(m,"key_id"))&&"RSA3072-SHA256-PKCS1-v1_5".equals(str(m,"algorithm")));
        byte[] payload=b64(str(m,"payload_base64"),8192),sig=b64(str(m,"signature_base64"),384);need(sig.length==384);
        Signature verifier=Signature.getInstance("SHA256withRSA");verifier.initVerify(b.key);verifier.update("Kiosk/GroupTrust/v1\0".getBytes(StandardCharsets.US_ASCII));verifier.update(payload);need(verifier.verify(sig));
        var p=json(payload,8192);keys(p,"version","group_id","generation","issued_at","expires_at","servers");version(p);
        long gen=num(p,"generation"),issued=num(p,"issued_at"),expires=num(p,"expires_at");String digest=LocalView.digest(payload);
        need(b.group.equals(str(p,"group_id"))&&gen>0);
        need(gen>prior||(gen==prior&&digest.equals(priorDigest)));
        if(!(issued<=now&&now<expires&&issued<expires))refuse("authority_window_refused");
        var servers=array(p.get("servers"));need(servers.size()==1);var s=object(servers.get(0));keys(s,"server_id","origin","tls_spki_sha256","roles");
        need(b.server.equals(str(s,"server_id"))&&b.origin.equals(str(s,"origin"))&&hash(str(s,"tls_spki_sha256")).equals(peer)&&array(s.get("roles")).equals(List.of("publisher")));
        return new Trust(gen,issued,expires,digest);
    }
    public static Map<String,DevelopmentWitness.Pin> inventory(Map<String,Object> p,String name)throws Exception {
        var group=obj(p,name);keys(group,"files");Map<String,DevelopmentWitness.Pin> pins=new TreeMap<>();Set<String> folded=new HashSet<>();
        for(Object item:array(group.get("files"))){var f=object(item);keys(f,"path","size","sha256");String path=str(f,"path");
            need(LocalView.safePath(path)&&folded.add(path.toLowerCase(Locale.ROOT)));need(pins.put(path,new DevelopmentWitness.Pin(num(f,"size"),hash(str(f,"sha256"))))==null);
        }need(!pins.isEmpty()&&pins.size()<=10001&&pins.containsKey(name.equals("package")?"manifest.json":"view.json"));return pins;
    }
    public static String canonical(Object value){
        if(value instanceof Map){Map<String,Object> sorted=new TreeMap<>();((Map<?,?>)value).forEach((k,v)->sorted.put((String)k,v));List<String> fields=new ArrayList<>();sorted.forEach((k,v)->fields.add(encode(k)+":"+canonical(v)));return "{"+String.join(",",fields)+"}";}
        if(value instanceof List){List<String> values=new ArrayList<>();for(Object v:(List<?>)value)values.add(canonical(v));return "["+String.join(",",values)+"]";}
        return encode(value);
    }
    public static Assignment assignment(byte[] bytes,Bootstrap b,String device,long prior,String priorMetadata)throws Exception {
        var m=json(bytes,2*1024*1024);boolean extended=num(m,"version")==2;
        if(extended)keys(m,"version","group_id","device_id","profile","generation","metadata_sha256","publication","display");
        else {keys(m,"version","group_id","device_id","profile","generation","metadata_sha256","publication");version(m);}
        DisplayProfile display=extended?DisplayProfile.parse(obj(m,"display")):DisplayProfile.legacy();
        long gen=num(m,"generation");String metadata=hash(str(m,"metadata_sha256"));
        need(b.group.equals(str(m,"group_id"))&&device.equals(str(m,"device_id"))&&PROFILE.equals(str(m,"profile"))&&gen>0&&gen>=prior&&(gen!=prior||metadata.equals(priorMetadata)));
        var p=obj(m,"publication");keys(p,"version","package_id","revision","raw_manifest_sha256","renderer","resource_profile","limits","windows_images","package","kiosk","tv");version(p);
        need(metadata.equals(LocalView.digest(canonical(p).getBytes(StandardCharsets.UTF_8))));
        id(str(p,"revision"));need(PROFILE.equals(str(p,"resource_profile")));
        var r=obj(p,"renderer");keys(r,"build_id","js_sha256","css_sha256");need(rendererCompatible(str(r,"build_id"))&&JS.equals(str(r,"js_sha256"))&&CSS.equals(str(r,"css_sha256")));
        var l=obj(p,"limits");keys(l,"max_pixels","max_live_bytes","per_image_ms","total_image_ms","capture_bytes","capture_files","min_free_bytes");
        need(num(l,"max_pixels")==2000000&&num(l,"max_live_bytes")==33554432&&num(l,"per_image_ms")==5000&&num(l,"total_image_ms")==15000&&num(l,"capture_bytes")==201326592&&num(l,"capture_files")==30003&&num(l,"min_free_bytes")==16777216);
        String packageId=hash(str(p,"package_id"));var pkg=new DevelopmentWitness.Package(packageId,hash(str(p,"raw_manifest_sha256")),inventory(p,"package"));
        need(pkg.files().get("manifest.json").sha256().equals(pkg.rawManifestSha256()));
        var renderer=new DevelopmentWitness.Renderer(BUILD,JS,CSS);
        var kiosk=new DevelopmentWitness.Artifact("kiosk",packageId,BUILD,inventory(p,"kiosk"));var tv=new DevelopmentWitness.Artifact("tv",packageId,BUILD,inventory(p,"tv"));
        Map<String,PreparedAdmission.WindowsImage> images=new TreeMap<>();for(var e:obj(p,"windows_images").entrySet()){
            need(LocalView.safePath(e.getKey()));var i=object(e.getValue());keys(i,"sha256","result");need("VERIFIED".equals(str(i,"result")));images.put(e.getKey(),new PreparedAdmission.WindowsImage(hash(str(i,"sha256")),PreparedAdmission.WindowsResult.VERIFIED));
        }
        return new Assignment(gen,metadata,new PreparedAdmission.Request(pkg,renderer,kiosk,tv,metadata,images,new PreparedAdmission.ImageBudget(2000000,33554432,5000,15000),new CapturedCandidate.Budget(201326592,30003,16777216)),display);
    }
}
