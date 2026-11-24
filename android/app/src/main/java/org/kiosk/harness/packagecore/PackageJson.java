package org.kiosk.harness.packagecore;

import java.math.BigInteger;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import static org.kiosk.harness.packagecore.PackageFailure.Code.*;

/** Package JSON semantics independent of org.json on JVM/Android. Integer tokens never coerce. */
final class PackageJson {
    private final String text;
    private int at;
    private PackageJson(String text) { this.text=text; }
    static Object parse(byte[] bytes) throws Exception {
        String encoding="UTF-8"; int skip=0;
        if (bytes.length>=4 && bytes[0]==0 && bytes[1]==0 && (bytes[2]&255)==254 && (bytes[3]&255)==255) { encoding="UTF-32BE"; skip=4; }
        else if (bytes.length>=4 && (bytes[0]&255)==255 && (bytes[1]&255)==254 && bytes[2]==0 && bytes[3]==0) { encoding="UTF-32LE"; skip=4; }
        else if (bytes.length>=3 && (bytes[0]&255)==239 && (bytes[1]&255)==187 && (bytes[2]&255)==191) skip=3;
        else if (bytes.length>=2 && (bytes[0]&255)==254 && (bytes[1]&255)==255) { encoding="UTF-16BE"; skip=2; }
        else if (bytes.length>=2 && (bytes[0]&255)==255 && (bytes[1]&255)==254) { encoding="UTF-16LE"; skip=2; }
        else if (bytes.length>=4 && bytes[0]==0) encoding=bytes[1]==0 ? "UTF-32BE" : "UTF-16BE";
        else if (bytes.length>=4 && bytes[1]==0) encoding=bytes[2]==0 && bytes[3]==0 ? "UTF-32LE" : "UTF-16LE";
        else if (bytes.length==2 && bytes[0]==0) encoding="UTF-16BE";
        else if (bytes.length==2 && bytes[1]==0) encoding="UTF-16LE";
        String value=decode(bytes,skip,encoding);
        PackageJson parser=new PackageJson(value);
        Object result=parser.value(0); parser.space();
        if (parser.at!=value.length()) throw PackageFailure.fail(invalid_package);
        return result;
    }
    private char peek() { return at<text.length()?text.charAt(at):'\0'; }
    private void space() { while(at<text.length() && " \r\n\t".indexOf(peek())>=0) at++; }
    private void take(char c) throws PackageFailure { if(peek()!=c)throw PackageFailure.fail(invalid_package); at++; }
    private Object value(int depth) throws Exception {
        space(); char c=peek();
        if(c=='{' || c=='[') {
            if(depth>=128)throw PackageFailure.fail(invalid_package);
            at++; space();
            if(c=='{') {
                Map<String,Object> map=new LinkedHashMap<>();
                if(peek()=='}'){at++;return map;}
                while(true){ space(); String key=string(); space(); take(':'); map.put(key,value(depth+1)); space(); if(peek()=='}'){at++;return map;} take(','); }
            }
            List<Object> list=new ArrayList<>();
            if(peek()==']'){at++;return list;}
            while(true){list.add(value(depth+1));space();if(peek()==']'){at++;return list;}take(',');}
        }
        if(c=='"')return string();
        String[] tokens={"true","false","null","NaN","Infinity","-Infinity"};
        Object[] values={Boolean.TRUE,Boolean.FALSE,null,Double.NaN,Double.POSITIVE_INFINITY,Double.NEGATIVE_INFINITY};
        for(int i=0;i<tokens.length;i++)if(text.startsWith(tokens[i],at)){at+=tokens[i].length();return values[i];}
        int start=at;
        if(c=='-')at++;
        if(peek()=='0')at++;else digits();
        boolean integer=true;
        if(peek()=='.'){integer=false;at++;digits();}
        if(peek()=='e'||peek()=='E'){integer=false;at++;if(peek()=='+'||peek()=='-')at++;digits();}
        String number=text.substring(start,at);
        // Branches must remain separate: a numeric ternary can promote/coerce integer values.
        if(integer){if(number.length()-(number.startsWith("-")?1:0)>4300)throw PackageFailure.fail(invalid_package);return new BigInteger(number);}
        return Double.valueOf(number);
    }
    // json.loads(bytes) uses surrogatepass; JSON escapes and encoded lone surrogates stay strings.
    private static String decode(byte[] bytes,int start,String encoding) throws PackageFailure {
        StringBuilder out=new StringBuilder();
        boolean little=encoding.endsWith("LE");
        int width=encoding.startsWith("UTF-32")?4:encoding.startsWith("UTF-16")?2:1;
        if(width>1){
            if((bytes.length-start)%width!=0)throw PackageFailure.fail(invalid_package);
            for(int i=start;i<bytes.length;i+=width){
                long code=0;
                for(int n=0;n<width;n++)code=(code<<8)|(bytes[i+(little?width-1-n:n)]&255);
                if(code>0x10ffff)throw PackageFailure.fail(invalid_package);
                out.appendCodePoint((int)code);
            }
        }else{
            for(int i=start;i<bytes.length;){
                int first=bytes[i++]&255,n,code,min;
                if(first<128){out.append((char)first);continue;}
                if(first>=194&&first<=223){n=1;code=first&31;min=128;}
                else if(first>=224&&first<=239){n=2;code=first&15;min=2048;}
                else if(first>=240&&first<=244){n=3;code=first&7;min=65536;}
                else throw PackageFailure.fail(invalid_package);
                if(i+n>bytes.length)throw PackageFailure.fail(invalid_package);
                while(n-->0){int next=bytes[i++]&255;if((next&192)!=128)throw PackageFailure.fail(invalid_package);code=code*64+(next&63);}
                if(code<min||code>0x10ffff)throw PackageFailure.fail(invalid_package);
                out.appendCodePoint(code);
            }
        }
        return out.toString();
    }
    private void digits() throws PackageFailure {
        int start=at;while(peek()>='0'&&peek()<='9')at++;
        if(start==at)throw PackageFailure.fail(invalid_package);
    }
    private String string() throws PackageFailure {
        take('"');StringBuilder result=new StringBuilder();
        while(at<text.length()) {
            char c=text.charAt(at++);
            if(c=='"')return result.toString();
            if(c<32)throw PackageFailure.fail(invalid_package);
            if(c=='\\'){
                if(at>=text.length())throw PackageFailure.fail(invalid_package);
                c=text.charAt(at++);
                if(c=='u'){
                    int code=0;
                    for(int i=0;i<4;i++){if(at>=text.length())throw PackageFailure.fail(invalid_package);char h=text.charAt(at++);int n="0123456789abcdef".indexOf(Character.toLowerCase(h));if(n<0)throw PackageFailure.fail(invalid_package);code=code*16+n;}
                    c=(char)code;
                } else {
                    int index="\"\\/bfnrt".indexOf(c);
                    if(index<0)throw PackageFailure.fail(invalid_package);
                    c="\"\\/\b\f\n\r\t".charAt(index);
                }
            }
            result.append(c);
        }
        throw PackageFailure.fail(invalid_package);
    }
    @SuppressWarnings("unchecked") static Map<String,Object> object(Object value, PackageFailure.Code code) throws PackageFailure {
        if(!(value instanceof Map))throw PackageFailure.fail(code);return (Map<String,Object>)value;
    }
    static List<?> array(Object value, PackageFailure.Code code) throws PackageFailure {
        if(!(value instanceof List))throw PackageFailure.fail(code);return (List<?>)value;
    }
    static String string(Object value, PackageFailure.Code code) throws PackageFailure {
        if(!(value instanceof String))throw PackageFailure.fail(code);return (String)value;
    }
    static BigInteger integer(Object value, PackageFailure.Code code) throws PackageFailure {
        if(!(value instanceof BigInteger))throw PackageFailure.fail(code);return (BigInteger)value;
    }
}
