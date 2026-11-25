package org.kiosk.harness.publishing;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLSocketFactory;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.delivery.PageReleaseProtocol;
import static org.kiosk.harness.delivery.DeliveryJson.*;
import static org.kiosk.harness.delivery.DeliveryProtocol.*;

/**
 * Exact-origin HTTPS client for the publisher review routes. Legacy v1 routes use
 * the platform trust store (the generic APK explicitly supports the guided user CA).
 * Native /api/page/native routes additionally require one locally configured public
 * Maintenance CA and pin it, so a user-installed CA cannot impersonate Maintenance.
 * Never disables hostname/TLS validation, never follows redirects, bounds replies.
 */
final class CandidateClient {
    record Artifact(String path,long size,String sha256){}
    private final String origin;
    private final String token;
    private final SSLSocketFactory maintenanceSockets;

    CandidateClient(Map<String,Object> authority)throws Exception{this(authority,null,null);}

    CandidateClient(String origin,String token,String maintenanceCa)throws Exception{
        this(Map.of("origin",origin),token,maintenanceCa);
    }

    /** A ticket token is bound to one exact configured origin; it never enters a URL. */
    CandidateClient(Map<String,Object> authority,String token,String maintenanceCa)throws Exception{
        need(authority!=null);
        origin=str(authority,"origin");
        URI uri=new URI(origin);
        need("https".equals(uri.getScheme())&&uri.getHost()!=null&&uri.getPort()>0
            &&uri.getRawUserInfo()==null&&uri.getRawQuery()==null&&uri.getRawFragment()==null
            &&"".equals(uri.getRawPath())&&origin.equals("https://"+uri.getHost()+":"+uri.getPort()));
        this.token=token==null?null:NativePageProtocol.token(token);
        this.maintenanceSockets=token==null?null:MaintenanceTrust.sockets(maintenanceCa);
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

    /** Native ticket: open the frozen v2 document through the trusted Maintenance origin. */
    Map<String,Object> nativeOpen(Map<String,Object> approval,List<Object> chain)throws Exception{
        requireToken();
        Map<String,Object> result=post(NativePageProtocol.OPEN_PATH,
            NativePageProtocol.openBody(approval,chain),2*1024*1024+65536);
        need(num(result,"version")==1);
        return obj(result,"document");
    }

    /** Fetch and hash every signed package file from its exact per-target route. */
    Map<String,PageReleaseProtocol.Files> nativePageArtifacts(Map<String,Object> document)
            throws Exception{
        requireToken();
        Map<String,PageReleaseProtocol.Files> result=new TreeMap<>();
        for(Object item:array(document.get("targets"))){
            Map<String,Object> target=object(item);
            String device=str(target,"device_id");
            List<Artifact> inventory=packageInventory(obj(target,"metadata"));
            Map<String,byte[]> files=new TreeMap<>();
            for(Artifact entry:inventory){
                byte[] payload=get(NativePageProtocol.packageRoute(device,entry.path()),(int)entry.size());
                need(payload.length==entry.size()&&LocalView.digest(payload).equals(entry.sha256()));
                files.put(entry.path(),payload);
            }
            need(result.put(device,PageReleaseProtocol.Files.packageOnly(files))==null);
        }
        return result;
    }

    Map<String,Object> nativeApprove(Map<String,Object> body)throws Exception{
        requireToken();
        return approveResponse(post(NativePageProtocol.APPROVE_PATH,body));
    }

    /** Contract: approved v2 ack carries an explicit distribution object. */
    static Map<String,Object> approveResponse(Map<String,Object> result)throws Exception{
        need(num(result,"version")==1&&"approved".equals(str(result,"state")));
        need(result.get("distribution") instanceof Map);
        return result;
    }

    private void requireToken()throws Exception{need(token!=null);}

    /** Validate the signed inventory before any artifact byte is requested. */
    static List<Artifact> packageInventory(Map<String,Object> metadata)throws Exception{
        Map<String,Object> publication=PageReleaseProtocol.validateMetadata(metadata);
        for(String group:List.of("kiosk","tv"))
            need(array(obj(publication,group).get("files")).isEmpty());
        List<Artifact> result=new ArrayList<>();
        boolean entrypoint=false;
        for(Object item:array(obj(publication,"package").get("files"))){
            Map<String,Object> row=object(item);
            String path=str(row,"path");
            need(PageReleaseProtocol.safePath(path));
            if(path.equals(PageReleaseProtocol.ENTRYPOINT))entrypoint=true;
            else if(!path.equals("manifest.json")&&!upload(path))
                throw new IOException("page_release_data_only");
            result.add(new Artifact(path,num(row,"size"),hash(str(row,"sha256"))));
        }
        if(!entrypoint)throw new IOException("page_release_entrypoint");
        result.sort(Comparator.comparingInt(entry->entry.path().equals("manifest.json")?0:
            entry.path().equals(PageReleaseProtocol.ENTRYPOINT)?1:2));
        return result;
    }

    static String artifactUrl(String identity,String path)throws Exception{
        hash(identity);
        return "/editor/native/candidates/"+identity+"/package/"+encodePath(path);
    }

    /** JSON string byte escaping without trusting any transport-supplied path alias. */
    static String encodePath(String path)throws Exception{
        need(PageReleaseProtocol.safePath(path));
        StringBuilder encoded=new StringBuilder();
        for(byte value:path.getBytes(StandardCharsets.UTF_8)){
            int byteValue=value&0xff;
            char character=(char)byteValue;
            if((character>='A'&&character<='Z')||(character>='a'&&character<='z')
                ||(character>='0'&&character<='9')||character=='-'||character=='_'||character=='.'
                ||character=='/'||character=='~')encoded.append(character);
            else encoded.append('%').append(String.format(Locale.ROOT,"%02X",byteValue));
        }
        return encoded.toString();
    }

    private static boolean upload(String path){
        if(!path.startsWith("static/uploads/"))return false;
        int dot=path.lastIndexOf('.');
        if(dot<0)return false;
        return List.of(".png",".jpg",".jpeg",".webp",".gif")
            .contains(path.substring(dot).toLowerCase(Locale.ROOT));
    }

    Map<String,Object> approve(Map<String,Object> body)throws Exception{
        Map<String,Object> result=post("/editor/native/approve",body);
        need("approved".equals(str(result,"state")));
        return result;
    }

    private HttpURLConnection open(String path)throws Exception{
        need(path.startsWith("/editor/native/candidates/")||path.startsWith("/editor/native/")
            ||path.startsWith("/api/page/native/"));
        if(path.startsWith("/api/page/native/"))requireToken();
        else need(token==null);
        URL url=new URL(origin+path);
        HttpURLConnection connection=(HttpURLConnection)url.openConnection();
        if(path.startsWith("/api/page/native/")){
            need(maintenanceSockets!=null);
            ((HttpsURLConnection)connection).setSSLSocketFactory(maintenanceSockets);
        }
        connection.setInstanceFollowRedirects(false);
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(30000);
        connection.setRequestProperty("Accept","application/octet-stream, application/json;q=0.1");
        connection.setRequestProperty("Accept-Encoding","identity");
        if(token!=null)connection.setRequestProperty("Authorization",NativePageProtocol.authorization(token));
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
        return post(path,body,65536);
    }

    private Map<String,Object> post(String path,Map<String,Object> body,int limit)throws Exception{
        need(limit>=1);
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
                if(token!=null)message=message.replace(token,"[redacted]");
                throw new IOException(message.substring(0,Math.min(300,message.length())));
            }
            try(InputStream stream=connection.getInputStream()){
                byte[] reply=stream.readNBytes(limit+1);
                need(reply.length<=limit);return json(reply,limit);
            }
        }finally{connection.disconnect();}
    }
}
