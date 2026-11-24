package org.kiosk.harness.delivery;

import java.nio.ByteBuffer;
import java.nio.charset.*;
import java.util.*;

/** Bounded native delivery UTF-8 grammar; signatures always use original payload bytes. */
public final class DeliveryJson {
    public static final class Refused extends Exception {
        public final String code;
        public Refused(String code) { super(code); this.code=code; }
    }
    public record NumberToken(String token) {}
    private final String text;
    private int at,nodes;
    private DeliveryJson(String text) { this.text=text; }
    static void require(boolean ok,String code)throws Refused { if(!ok)throw new Refused(code); }
    public static Object parse(byte[] bytes,int maxBytes)throws Exception {
        require(bytes.length<=maxBytes,"JSON_BOUND");
        String text=StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
        DeliveryJson p=new DeliveryJson(text); Object value=p.value(0); p.space();
        require(p.at==text.length(),"JSON_SYNTAX"); return value;
    }
    private char peek(){return at<text.length()?text.charAt(at):'\0';}
    private void take(char c)throws Refused {require(peek()==c,"JSON_SYNTAX");at++;}
    private void space(){while(at<text.length()&&" \r\n\t".indexOf(peek())>=0)at++;}
    private Object value(int depth)throws Exception {
        require(depth<=12&&++nodes<=240000,"JSON_BOUND"); space(); char c=peek();
        if(c=='{'){
            at++;space();Map<String,Object> map=new LinkedHashMap<>();
            if(peek()=='}'){at++;return map;}
            while(true){space();String key=string();require(!map.containsKey(key),"DUPLICATE_JSON_FIELD");space();take(':');map.put(key,value(depth+1));space();if(peek()=='}'){at++;return map;}take(',');}
        }
        if(c=='['){at++;space();List<Object> list=new ArrayList<>();if(peek()==']'){at++;return list;}while(true){list.add(value(depth+1));space();if(peek()==']'){at++;return list;}take(',');}}
        if(c=='"')return string();
        if(text.startsWith("true",at)){at+=4;return true;}
        if(text.startsWith("false",at)){at+=5;return false;}
        if(text.startsWith("null",at)){at+=4;return null;}
        int start=at;if(peek()=='-')at++;
        if(peek()=='0')at++;else digits();
        if(peek()=='.'){at++;digits();}
        if(peek()=='e'||peek()=='E'){at++;if(peek()=='+'||peek()=='-')at++;digits();}
        require(at-start<=32,"JSON_BOUND");return new NumberToken(text.substring(start,at));
    }
    private void digits()throws Refused {int start=at;while(peek()>='0'&&peek()<='9')at++;require(at>start,"JSON_SYNTAX");}
    private String string()throws Refused {
        take('"');StringBuilder out=new StringBuilder();
        while(true){require(at<text.length(),"JSON_SYNTAX");char c=text.charAt(at++);if(c=='"')break;require(c>=32,"JSON_SYNTAX");
            if(c=='\\'){require(at<text.length(),"JSON_SYNTAX");c=text.charAt(at++);switch(c){
                case '"':case '\\':case '/':break;
                case 'b':c='\b';break;case 'f':c='\f';break;case 'n':c='\n';break;case 'r':c='\r';break;case 't':c='\t';break;
                case 'u':int v=0;for(int i=0;i<4;i++){require(at<text.length(),"JSON_SYNTAX");char h=text.charAt(at++);int n="0123456789abcdef".indexOf(Character.toLowerCase(h));require(n>=0,"JSON_SYNTAX");v=(v<<4)|n;}c=(char)v;break;
                default:throw new Refused("JSON_SYNTAX");
            }}out.append(c);require(out.length()<=65536,"JSON_BOUND");
        }
        for(int i=0;i<out.length();i++){char c=out.charAt(i);if(Character.isHighSurrogate(c)){require(i+1<out.length()&&Character.isLowSurrogate(out.charAt(++i)),"UNICODE_REFUSED");}else require(!Character.isLowSurrogate(c),"UNICODE_REFUSED");}
        return out.toString();
    }
    @SuppressWarnings("unchecked") public static Map<String,Object> object(Object v)throws Refused {require(v instanceof Map,"TYPE_REFUSED");return (Map<String,Object>)v;}
    @SuppressWarnings("unchecked") public static List<Object> array(Object v)throws Refused {require(v instanceof List,"TYPE_REFUSED");return (List<Object>)v;}
    public static String string(Object v)throws Refused {require(v instanceof String,"TYPE_REFUSED");return (String)v;}
    public static long integer(Object v)throws Refused {
        require(v instanceof NumberToken,"TYPE_REFUSED");String n=((NumberToken)v).token();require(n.matches("0|[1-9][0-9]*"),"TYPE_REFUSED");
        try{return Long.parseLong(n);}catch(NumberFormatException e){throw new Refused("TYPE_REFUSED");}
    }
    public static void keys(Map<String,Object> v,String... names)throws Refused {require(v.keySet().equals(new HashSet<>(Arrays.asList(names))),"STRUCTURE_REFUSED");}
    /** Reporting/malformed-case construction only; never feeds reconstructed bytes to signature verification. */
    public static String encode(Object value){
        if(value==null)return "null";if(value instanceof NumberToken)return ((NumberToken)value).token();
        if(value instanceof Map){List<String> fields=new ArrayList<>();((Map<?,?>)value).forEach((k,v)->fields.add(encode(k.toString())+":"+encode(v)));return "{"+String.join(",",fields)+"}";}
        if(value instanceof List){List<String> fields=new ArrayList<>();for(Object v:(List<?>)value)fields.add(encode(v));return "["+String.join(",",fields)+"]";}
        if(value instanceof String){StringBuilder out=new StringBuilder("\"");for(char c:((String)value).toCharArray()){if(c=='"'||c=='\\')out.append('\\').append(c);else if(c<32)out.append(String.format(Locale.ROOT,"\\u%04x",(int)c));else out.append(c);}return out.append('"').toString();}
        return value.toString();
    }
}
