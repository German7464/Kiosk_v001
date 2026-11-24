package org.kiosk.harness.publishing;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import static org.kiosk.harness.delivery.DeliveryJson.*;
import static org.kiosk.harness.delivery.DeliveryProtocol.*;

/**
 * Exact-origin HTTPS client for the publisher review routes. Uses the platform
 * trust store (the generic APK explicitly supports the guided user CA). Never
 * disables hostname/TLS validation, never follows redirects and bounds replies.
 */
final class CandidateClient {
    private final String origin;

    CandidateClient(Map<String,Object> authority)throws Exception{
        need(authority!=null);
        origin=str(authority,"origin");
        URI uri=new URI(origin);
        need("https".equals(uri.getScheme())&&uri.getHost()!=null&&uri.getPort()>0
            &&uri.getRawUserInfo()==null&&uri.getRawQuery()==null&&uri.getRawFragment()==null
            &&"".equals(uri.getRawPath())&&origin.equals("https://"+uri.getHost()+":"+uri.getPort()));
    }

    Map<String,Object> candidate(String identity)throws Exception{
        return json(get("/editor/native/candidates/"+hash(identity),2*1024*1024),2*1024*1024);
    }

    Map<String,Object> challenge(String token)throws Exception{
        hash(token);
        Map<String,Object> body=new LinkedHashMap<>();
        body.put("token",token);
        return obj(post("/editor/native/challenge",body),"context");
    }

    void acceptLogin(String token,Map<String,Object> approval,List<Object> chain)throws Exception{
        hash(token);
        Map<String,Object> body=new LinkedHashMap<>();
        body.put("token",token);body.put("approval",approval);body.put("chain",chain);
        Map<String,Object> result=post("/editor/native/accept",body);
        need("accepted".equals(str(result,"state")));
    }

    byte[] publicData(String identity)throws Exception{
        return get("/editor/native/candidates/"+hash(identity)+"/package/data/events.json",
                   PublisherReview.MAX_PUBLIC_DATA);
    }

    Map<String,Object> approve(Map<String,Object> body)throws Exception{
        Map<String,Object> result=post("/editor/native/approve",body);
        need("approved".equals(str(result,"state")));
        return result;
    }

    private HttpURLConnection open(String path)throws Exception{
        need(path.startsWith("/editor/native/candidates/")||path.startsWith("/editor/native/"));
        URL url=new URL(origin+path);
        HttpURLConnection connection=(HttpURLConnection)url.openConnection();
        connection.setInstanceFollowRedirects(false);
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(30000);
        connection.setRequestProperty("Accept","application/json");
        connection.setRequestProperty("Accept-Encoding","identity");
        return connection;
    }

    private byte[] get(String path,int limit)throws Exception{
        HttpURLConnection connection=open(path);
        try{
            connection.setRequestMethod("GET");
            int status=connection.getResponseCode();
            need(status==200);
            need(connection.getHeaderField("Content-Encoding")==null||
                 "identity".equals(connection.getHeaderField("Content-Encoding")));
            String length=connection.getHeaderField("Content-Length");
            if(length!=null)need(Long.parseLong(length)>=0&&Long.parseLong(length)<=limit);
            try(InputStream stream=connection.getInputStream()){
                byte[] payload=stream.readNBytes(limit+1);
                need(payload.length<=limit);return payload;
            }
        }finally{connection.disconnect();}
    }

    private Map<String,Object> post(String path,Map<String,Object> body)throws Exception{
        byte[] payload=PublisherAuthority.canonical(body);
        need(payload.length<=65536);
        HttpURLConnection connection=open(path);
        try{
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type","application/json");
            connection.setFixedLengthStreamingMode(payload.length);
            try(OutputStream stream=connection.getOutputStream()){stream.write(payload);}
            int status=connection.getResponseCode();
            if(status!=200){
                String detail="";
                try(InputStream error=connection.getErrorStream()){
                    if(error!=null){byte[] raw=error.readNBytes(512);detail=new String(raw,StandardCharsets.UTF_8).trim();}
                }catch(Exception ignored){}
                String message="publisher_http_"+status+(detail.isEmpty()?"":":"+detail);
                throw new IOException(message.substring(0,Math.min(300,message.length())));
            }
            try(InputStream stream=connection.getInputStream()){
                byte[] reply=stream.readNBytes(65537);
                need(reply.length<=65536);return json(reply,65536);
            }
        }finally{connection.disconnect();}
    }
}
