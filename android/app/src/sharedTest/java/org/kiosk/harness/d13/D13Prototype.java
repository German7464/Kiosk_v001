package org.kiosk.harness.d13;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.X509EncodedKeySpec;
import java.util.*;
import static org.kiosk.harness.d13.StrictPrototypeJson.*;

/** Offline synthetic verifier only. No bootstrap, network, credential or activation authority. */
public final class D13Prototype {
    public static final String VECTOR_HASH="88013034624d01d9ff36ab9a9da73b115596f26e5d9734a4072e2387d9da8dcb";
    public static final String ANCHOR_HASH="b702e6c9d2d3546b0ce60746fe0ffc6c21a0e728c23af9c3021610647c1c49d0";
    public static final String GROUP="11111111-1111-4111-8111-111111111111";
    public static final String ORIGIN="https://prototype.invalid:18443";
    static final String ALGORITHM="RSA3072-SHA256-PKCS1-v1_5-PROTOTYPE";
    static final byte[] PREFIX="Kiosk/D13/SYNTHETIC/v0\0".getBytes(StandardCharsets.US_ASCII);
    final RSAPublicKey anchor;
    final byte[] anchorDer,previousPayload;
    final long now,generation;
    public final String signatureProvider,keyProvider;
    public D13Prototype(byte[] der,byte[] previousPayload,long now,long generation)throws Exception {
        require(hash(der).equals(ANCHOR_HASH),"UNTRUSTED_AUTHORITY");anchorDer=der.clone();anchor=publicKey(der);
        this.previousPayload=previousPayload.clone();this.now=now;this.generation=generation;
        Signature providerProbe=Signature.getInstance("SHA256withRSA");providerProbe.initVerify(anchor);
        signatureProvider=providerProbe.getProvider().toString();
        keyProvider=KeyFactory.getInstance("RSA").getProvider().toString();
    }
    public static String hash(byte[] b)throws Exception {StringBuilder s=new StringBuilder();for(byte x:MessageDigest.getInstance("SHA-256").digest(b))s.append(String.format(Locale.ROOT,"%02x",x&255));return s.toString();}
    static byte[] base64(Object v,int max)throws Exception {
        String s=string(v);require(s.length()<=((max+2)/3)*4&&s.length()%4==0,"BASE64_REFUSED");
        byte[] b;try{b=Base64.getDecoder().decode(s);}catch(IllegalArgumentException e){throw new Refused("BASE64_REFUSED");}
        require(b.length<=max&&Base64.getEncoder().encodeToString(b).equals(s),"BASE64_REFUSED");return b;
    }
    static RSAPublicKey publicKey(byte[] der)throws Exception {
        require(der.length>=4&&der.length<=1024&&(der[0]&255)==0x30,"DER_REFUSED");
        int at=2,length=der[1]&255;
        if(length>=128){int n=length&127;require(n>=1&&n<=2&&der.length>=2+n&&(der[2]&255)!=0,"DER_REFUSED");length=0;for(int i=0;i<n;i++)length=(length<<8)|(der[at++]&255);require(length>=128&&(n==1||length>255),"DER_REFUSED");}
        require(at+length==der.length,"DER_REFUSED");
        RSAPublicKey key;try{key=(RSAPublicKey)KeyFactory.getInstance("RSA").generatePublic(new X509EncodedKeySpec(der));}catch(GeneralSecurityException|ClassCastException e){throw new Refused("DER_REFUSED");}
        require(Arrays.equals(key.getEncoded(),der),"DER_REFUSED");require(key.getModulus().bitLength()==3072,"RSA_SIZE_REFUSED");
        require(key.getPublicExponent().equals(java.math.BigInteger.valueOf(65537)),"RSA_EXPONENT_REFUSED");return key;
    }
    public boolean rawSignature(Map<String,Object> envelope)throws Exception {
        Signature s=Signature.getInstance("SHA256withRSA");s.initVerify(anchor);s.update(PREFIX);s.update(base64(envelope.get("payload_base64"),8192));
        try{return s.verify(base64(envelope.get("signature_base64"),384));}catch(SignatureException e){return false;}
    }
    public String verify(byte[] envelope,String peerId,String peerSpki){
        try{verifyChecked(envelope,peerId,peerSpki);return "ACCEPT";}catch(Refused e){return e.code;}catch(java.nio.charset.CharacterCodingException e){return "UTF8_REFUSED";}catch(Exception e){return "MALFORMED_REFUSED";}
    }
    private void verifyChecked(byte[] envelope,String peerId,String peerSpki)throws Exception {
        Map<String,Object> e=object(parse(envelope,16384));keys(e,"schema_version","kind","algorithm","public_spki_base64","signature_base64","payload_base64");
        require(integer(e.get("schema_version"))==0&&string(e.get("kind")).equals("synthetic-d13-not-product"),"UNSUPPORTED");
        require(string(e.get("algorithm")).equals(ALGORITHM),"ALGORITHM_REFUSED");
        byte[] key=base64(e.get("public_spki_base64"),1024);publicKey(key);
        require(MessageDigest.isEqual(key,anchorDer),"UNTRUSTED_AUTHORITY");
        byte[] payload=base64(e.get("payload_base64"),8192),signature=base64(e.get("signature_base64"),384);
        require(signature.length==384,"SIGNATURE_LENGTH_REFUSED");
        require(rawSignature(e),"BAD_SIGNATURE");
        Map<String,Object> p=object(parse(payload,8192));keys(p,"schema_version","kind","group_id","generation","issued_at","expires_at","servers");
        long version=integer(p.get("schema_version")),next=integer(p.get("generation")),issued=integer(p.get("issued_at")),expires=integer(p.get("expires_at"));
        require(version==1&&string(p.get("kind")).equals("kiosk-trust-prototype-not-product"),"UNSUPPORTED");
        String group=string(p.get("group_id"));List<Object> servers=array(p.get("servers"));require(!servers.isEmpty()&&servers.size()<=16,"STRUCTURE_REFUSED");
        Set<String> ids=new HashSet<>();List<Map<String,Object>> parsed=new ArrayList<>();
        for(Object value:servers){Map<String,Object> server=object(value);keys(server,"server_id","origin","roles","spki_sha256");String id=string(server.get("server_id"));uuid(id);require(ids.add(id),"DUPLICATE_ID");
            string(server.get("origin"));String spki=string(server.get("spki_sha256"));require(spki.matches("[0-9a-f]{64}"),"STRUCTURE_REFUSED");List<Object> roles=array(server.get("roles"));require(roles.size()<=4,"STRUCTURE_REFUSED");Set<String> unique=new HashSet<>();for(Object role:roles)require(unique.add(string(role)),"STRUCTURE_REFUSED");parsed.add(server);}
        uuid(group);require(group.equals(GROUP),"GROUP_MISMATCH");
        for(Map<String,Object> server:parsed){String origin=string(server.get("origin"));URI uri;try{uri=new URI(origin);}catch(Exception ex){throw new Refused("ORIGIN_REFUSED");}
            require("https".equals(uri.getScheme())&&uri.getHost()!=null&&uri.getRawUserInfo()==null&&uri.getRawQuery()==null&&uri.getRawFragment()==null&&(uri.getRawPath()==null||uri.getRawPath().isEmpty())&&origin.equals(ORIGIN),"ORIGIN_REFUSED");
            require(array(server.get("roles")).contains("publisher"),"ROLE_DENIED");}
        require(issued<=now&&expires>now&&expires>issued,"EXPIRED_UPDATES_BLOCKED");
        require(next>=generation,"ROLLBACK");require(next!=generation||MessageDigest.isEqual(payload,previousPayload),"GENERATION_CONFLICT");
        Map<String,Object> peer=null;for(Map<String,Object> s:parsed)if(s.get("server_id").equals(peerId))peer=s;
        require(peer!=null,"ROLE_DENIED");require(peer.get("spki_sha256").equals(peerSpki),"SERVER_KEY_MISMATCH");
    }
    private static void uuid(String value)throws Refused {require(value.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),"STRUCTURE_REFUSED");}
}
