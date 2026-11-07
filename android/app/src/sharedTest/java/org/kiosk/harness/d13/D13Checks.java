package org.kiosk.harness.d13;

import java.nio.charset.StandardCharsets;
import java.security.*;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.RSAPublicKeySpec;
import java.util.*;
import static org.kiosk.harness.d13.StrictPrototypeJson.*;

/** Identical JVM/platform checks; org.json is diagnostic only, not an acceptance parser. */
public final class D13Checks {
    static byte[] bytes(String text){return text.getBytes(StandardCharsets.UTF_8);}
    static byte[] encoded(Object value){return bytes(encode(value));}
    static void check(boolean yes,String label){if(!yes)throw new AssertionError(label);}
    interface Attempt {void run()throws Exception;}
    private static void rejects(List<Object> out,String label,String code,Attempt test)throws Exception {
        String actual="ACCEPT";try{test.run();}catch(Refused e){actual=e.code;}catch(java.nio.charset.CharacterCodingException e){actual="UTF8_REFUSED";}
        check(code.equals(actual),label+": "+actual+" != "+code);out.add(Map.of("name",label,"outcome",actual));
    }
    public static Map<String,Object> run(byte[] input,byte[] windows)throws Exception {
        check(D13Prototype.hash(input).equals(D13Prototype.VECTOR_HASH),"independent vector pin");
        Map<String,Object> fixture=object(parse(input,65536));
        byte[] der=D13Prototype.base64(fixture.get("trusted_group_spki_base64"),1024);
        check(D13Prototype.hash(der).equals(D13Prototype.ANCHOR_HASH),"independent authority pin");
        check(Arrays.equals(D13Prototype.base64(fixture.get("domain_prefix_base64"),64),D13Prototype.PREFIX),"domain prefix");
        check(integer(fixture.get("now"))==1793577600L&&integer(fixture.get("current_generation"))==7&&fixture.get("group_id").equals(D13Prototype.GROUP),"fixture context");
        D13Prototype verifier=new D13Prototype(der,D13Prototype.base64(fixture.get("current_payload_base64"),8192),1793577600L,7);
        Map<String,Boolean> windowsRaw=new HashMap<>();for(Object value:array(parse(windows,65536))){Map<String,Object> w=object(value);check(w.get("expected_signature_valid").equals(w.get("actual_signature_valid")),"PC1 Windows signature result");windowsRaw.put(string(w.get("name")),(Boolean)w.get("actual_signature_valid"));}
        List<Object> cases=array(fixture.get("cases"));check(cases.size()==18&&windowsRaw.size()==18,"18 cases");List<Object> results=new ArrayList<>();int labelMismatches=0,accepted=0;
        Map<String,Object> validEnvelope=null;String peer=null,spki=null;
        for(Object c:cases){Map<String,Object> item=object(c),e=object(item.get("envelope"));String name=string(item.get("name")),expected=string(item.get("expected"));
            boolean raw=verifier.rawSignature(e);check(windowsRaw.containsKey(name),"Windows case present");
            boolean sameRaw=windowsRaw.get(name)==raw;
            check(sameRaw||(name.equals("wrong-public-key")&&raw&&!windowsRaw.get(name)),"unexplained raw signature difference: "+name);
            String actual=verifier.verify(encoded(e),string(item.get("peer_server_id")),string(item.get("peer_spki_sha256")));
            if(actual.equals("ACCEPT"))accepted++;check(actual.equals("ACCEPT")==expected.equals("ACCEPT"),"accept/refuse: "+name);
            if(!actual.equals(expected)){labelMismatches++;check(name.equals("wrong-public-key")&&actual.equals("UNTRUSTED_AUTHORITY")&&expected.equals("BAD_SIGNATURE"),"unexplained label mismatch "+name+": "+actual);}
            Map<String,Object> result=new LinkedHashMap<>();result.put("name",name);result.put("expected",expected);result.put("actual",actual);result.put("raw_signature_matches_windows",sameRaw);result.put("raw_signature_valid_fixed_anchor",raw);result.put("pc1_reported_signature_valid",windowsRaw.get(name));results.add(result);
            if(name.equals("valid-list")){validEnvelope=e;peer=string(item.get("peer_server_id"));spki=string(item.get("peer_spki_sha256"));}
        }
        check(accepted==1&&validEnvelope!=null&&labelMismatches==1,"case totals");
        List<Object> supplemental=new ArrayList<>();final String peerId=peer,peerKey=spki;final Map<String,Object> good=validEnvelope;
        String[] malformed={"{\"x\":1,\"x\":2}","{\"x\":null,\"x\":0}","{\"x\":1,\"\\u0078\":2}","{\"a\":{\"x\":1,\"x\":2}}","{\"a\":1}{}","{/*x*/\"a\":1}","{'a':1}","{\"a\":1,}","[1,]","{\"a\":NaN}","{\"a\":Infinity}","{\"a\":01}","{\"a\":1e}","\ufeff{}","\"\\ud800\""};
        for(int i=0;i<malformed.length;i++){String code=i<4?"DUPLICATE_JSON_FIELD":i==14?"UNICODE_REFUSED":"JSON_SYNTAX";String text=malformed[i];rejects(supplemental,"strict-json-"+i,code,()->parse(bytes(text),8192));}
        rejects(supplemental,"malformed-utf8","UTF8_REFUSED",()->parse(new byte[]{(byte)0xc0,(byte)0xaf},8192));
        rejects(supplemental,"depth-bound","JSON_BOUND",()->parse(bytes("[".repeat(14)+"0"+"]".repeat(14)),8192));
        rejects(supplemental,"byte-bound","JSON_BOUND",()->parse(bytes(" ".repeat(8193)),8192));
        rejects(supplemental,"node-bound","JSON_BOUND",()->parse(bytes("["+"0,".repeat(2048)+"0]"),8192));
        rejects(supplemental,"number-token-bound","JSON_BOUND",()->parse(bytes("1".repeat(33)),8192));
        rejects(supplemental,"string-bound","JSON_BOUND",()->parse(bytes("\""+"a".repeat(65537)+"\""),70000));
        for(String n:List.of("1.0","1e0","-0","9223372036854775808"))rejects(supplemental,"integer-lexeme-"+n,"TYPE_REFUSED",()->integer(parse(bytes(n),128)));
        rejects(supplemental,"boolean-not-integer","TYPE_REFUSED",()->integer(Boolean.TRUE));
        check(string(parse(bytes("\"\\ud83d\\ude00\""),128)).codePointCount(0,2)==1,"paired surrogate");
        check(integer(parse(bytes("0"),16))==0,"integer zero");
        rejects(supplemental,"base64-whitespace","BASE64_REFUSED",()->D13Prototype.base64("Y Q==",16));
        rejects(supplemental,"base64-unpadded","BASE64_REFUSED",()->D13Prototype.base64("YQ",16));
        rejects(supplemental,"base64-unused-bits","BASE64_REFUSED",()->D13Prototype.base64("YR==",16));
        rejects(supplemental,"base64-trailing-data","BASE64_REFUSED",()->D13Prototype.base64("YQ==AAAA",16));
        byte[] trailing=Arrays.copyOf(der,der.length+1);rejects(supplemental,"DER-trailing-data","DER_REFUSED",()->D13Prototype.publicKey(trailing));
        byte[] indefinite=der.clone();indefinite[1]=(byte)128;rejects(supplemental,"DER-indefinite-length","DER_REFUSED",()->D13Prototype.publicKey(indefinite));
        RSAPublicKey authority=D13Prototype.publicKey(der);
        byte[] small=KeyFactory.getInstance("RSA").generatePublic(new RSAPublicKeySpec(authority.getModulus().shiftRight(1024).setBit(0),authority.getPublicExponent())).getEncoded();
        rejects(supplemental,"RSA2048-public-only","RSA_SIZE_REFUSED",()->D13Prototype.publicKey(small));
        byte[] wrongExponent=KeyFactory.getInstance("RSA").generatePublic(new RSAPublicKeySpec(authority.getModulus(),java.math.BigInteger.valueOf(3))).getEncoded();
        rejects(supplemental,"RSA-exponent","RSA_EXPONENT_REFUSED",()->D13Prototype.publicKey(wrongExponent));
        List<Map<String,Object>> changed=new ArrayList<>();List<String> labels=new ArrayList<>(),codes=new ArrayList<>();
        Map<String,Object> e=new LinkedHashMap<>(good);e.put("schema_version",new NumberToken("1"));changed.add(e);labels.add("envelope-version");codes.add("UNSUPPORTED");
        e=new LinkedHashMap<>(good);e.put("schema_version",true);changed.add(e);labels.add("envelope-boolean-version");codes.add("TYPE_REFUSED");
        e=new LinkedHashMap<>(good);e.put("extra",true);changed.add(e);labels.add("unknown-field");codes.add("STRUCTURE_REFUSED");
        e=new LinkedHashMap<>(good);e.put("public_spki_base64",Base64.getEncoder().encodeToString(trailing));changed.add(e);labels.add("envelope-DER-trailing");codes.add("DER_REFUSED");
        e=new LinkedHashMap<>(good);e.put("signature_base64","YQ==");changed.add(e);labels.add("signature-length");codes.add("SIGNATURE_LENGTH_REFUSED");
        e=new LinkedHashMap<>(good);e.put("payload_base64",Base64.getEncoder().encodeToString(bytes("{invalid")));changed.add(e);labels.add("signature-before-payload-json");codes.add("BAD_SIGNATURE");
        e=new LinkedHashMap<>(good);e.put("payload_base64",Base64.getEncoder().encodeToString(bytes(" "+new String(D13Prototype.base64(good.get("payload_base64"),8192),StandardCharsets.UTF_8))));changed.add(e);labels.add("exact-byte-whitespace-change");codes.add("BAD_SIGNATURE");
        for(int i=0;i<changed.size();i++){String actual=verifier.verify(encoded(changed.get(i)),peer,spki);check(actual.equals(codes.get(i)),labels.get(i)+": "+actual);supplemental.add(Map.of("name",labels.get(i),"outcome",actual));}
        String duplicate="{\"algorithm\":\"X\","+encode(good).substring(1);check(verifier.verify(bytes(duplicate),peerId,peerKey).equals("DUPLICATE_JSON_FIELD"),"duplicate envelope field");supplemental.add(Map.of("name","duplicate-envelope-key","outcome","DUPLICATE_JSON_FIELD"));
        String stockDuplicate;try{org.json.JSONObject j=new org.json.JSONObject("{\"generation\":7,\"generation\":8}");stockDuplicate="ACCEPTED value="+j.get("generation");}catch(Exception ex){stockDuplicate="REFUSED "+ex.getClass().getSimpleName();}
        String stockCoercion;try{stockCoercion=String.valueOf(new org.json.JSONObject("{\"generation\":\"7\"}").getLong("generation"));}catch(Exception ex){stockCoercion="REFUSED";}
        Map<String,Object> report=new LinkedHashMap<>();report.put("scope","SYNTHETIC_OFFLINE_TEST_ONLY");report.put("vectors_sha256",D13Prototype.hash(input));report.put("anchor_spki_sha256",D13Prototype.hash(der));report.put("windows_results_sha256",D13Prototype.hash(windows));report.put("signature_provider",verifier.signatureProvider);report.put("key_factory_provider",verifier.keyProvider);report.put("rsa_bits",authority.getModulus().bitLength());report.put("case_results",results);report.put("label_mismatches",labelMismatches);report.put("supplemental",supplemental);report.put("stock_json_duplicate_behavior",stockDuplicate);report.put("stock_json_string_getLong",stockCoercion);report.put("model",EnrollmentModel.run());return report;
    }
}
