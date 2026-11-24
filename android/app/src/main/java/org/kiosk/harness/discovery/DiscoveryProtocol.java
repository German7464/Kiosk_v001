package org.kiosk.harness.discovery;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.*;
import org.kiosk.harness.delivery.DeliveryJson;

/** Advisory hints only. No delivery state or transport is reachable from this parser. */
public final class DiscoveryProtocol {
    public static final int PORT=47751, SIZE=512, INPUTS=256, RESULTS=32;
    public record Hint(String origin,String label) {}
    public static String nonce(){byte[] b=new byte[16];new SecureRandom().nextBytes(b);StringBuilder s=new StringBuilder();for(byte v:b)s.append(String.format(Locale.ROOT,"%02x",v&255));return s.toString();}
    private static void need(boolean b)throws java.io.IOException{if(!b)throw new java.io.IOException("discovery_refused");}
    public static String origin(String s)throws Exception {
        URI u=new URI(s);
        need("https".equals(u.getScheme())&&u.getHost()!=null&&u.getPort()>0&&u.getPort()<=65535&&u.getRawUserInfo()==null&&u.getRawQuery()==null&&u.getRawFragment()==null&&"".equals(u.getRawPath())&&s.equals("https://"+u.getHost()+":"+u.getPort()));return s;
    }
    public static byte[] query(String nonce)throws Exception {
        need(nonce.matches("[a-f0-9]{32}"));byte[] out=new byte[SIZE];Arrays.fill(out,(byte)' ');
        byte[] json=("{\"protocol\":\"kiosk-discovery-v1\",\"type\":\"query\",\"nonce\":\""+nonce+"\"}").getBytes(StandardCharsets.UTF_8);System.arraycopy(json,0,out,0,json.length);return out;
    }
    public static Hint reply(byte[] data,String nonce)throws Exception {
        need(data.length>0&&data.length<=SIZE&&nonce.matches("[a-f0-9]{32}"));
        var m=DeliveryJson.object(DeliveryJson.parse(data,SIZE));DeliveryJson.keys(m,"protocol","type","nonce","origin","label");
        need("kiosk-discovery-v1".equals(m.get("protocol"))&&"reply".equals(m.get("type"))&&nonce.equals(m.get("nonce")));
        String origin=origin(DeliveryJson.string(m.get("origin"))),label=DeliveryJson.string(m.get("label"));
        need(label.codePointCount(0,label.length())<=64&&printable(label));
        return new Hint(origin,label);
    }
    /** Same common semantics as Python str.isprintable: ASCII space allowed, other Unicode C/Z categories refused. */
    static boolean printable(String label){
        return label.codePoints().allMatch(c->c==0x20||switch(Character.getType(c)){
            case Character.CONTROL,Character.FORMAT,Character.SURROGATE,Character.PRIVATE_USE,Character.UNASSIGNED,
                 Character.SPACE_SEPARATOR,Character.LINE_SEPARATOR,Character.PARAGRAPH_SEPARATOR->false;
            default->true;});
    }
    public static final class Results {
        private int inputs;
        private final Map<String,Hint> hints=new LinkedHashMap<>();
        public boolean full(){return inputs>=INPUTS;}
        public Hint accept(byte[] bytes,String nonce){if(full())return null;inputs++;try{Hint h=reply(bytes,nonce);if(hints.containsKey(h.origin())||hints.size()>=RESULTS)return null;hints.put(h.origin(),h);return h;}catch(Exception invalid){return null;}}
        public List<Hint> hints(){return List.copyOf(hints.values());}
        public int inputs(){return inputs;}
    }
}
