package org.kiosk.harness.publishing;

import java.io.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.*;
import static org.kiosk.harness.delivery.DeliveryJson.*;
import static org.kiosk.harness.delivery.DeliveryProtocol.*;

/**
 * Durable native publisher facts: pinned root/policy binding, verified ancestry
 * heads and one exact signed approval awaiting submission.
 *
 * Writes use a flushed temporary file followed by an atomic rename, so a crash
 * either keeps the previous facts or the complete new ones. A corrupt/unreadable
 * state refuses to start rather than silently resetting authority.
 */
public final class PublisherState {
    private static final int LIMIT = 262144;
    private final File file;
    private Map<String,Object> data;

    public PublisherState(File directory)throws Exception{
        if(!directory.isDirectory()&&!directory.mkdirs())throw new IOException("publisher_state_directory");
        file=new File(directory,"publisher-state.json");
        data=load();
    }

    private static long count(Object value)throws Exception{
        if(value instanceof NumberToken)return integer(value);
        need(value instanceof Long||value instanceof Integer);
        return ((Number)value).longValue();
    }

    private Map<String,Object> load()throws Exception{
        if(!file.isFile())return blank();
        byte[] payload=Files.readAllBytes(file.toPath());
        if(payload.length>LIMIT)throw new IOException("publisher_state_limit");
        Map<String,Object> value=json(payload,LIMIT);
        Set<String> required=Set.of("version","policy_floor","heads","pending");
        Set<String> allowed=Set.of("version","policy_floor","heads","pending","maintenance_origin",
            "maintenance_ca");
        need(value.keySet().containsAll(required)&&allowed.containsAll(value.keySet()));
        need(num(value,"version")==1);
        need(count(value.get("policy_floor"))>=0);
        List<Object> heads=array(value.get("heads"));
        need(heads.size()<=32);
        for(Object item:heads)hash(string(item));
        Map<String,Object> pending=object(value.get("pending"));
        if(!pending.isEmpty())keys(pending,"id","approval","chain","candidate");
        if(value.containsKey("maintenance_origin"))NativePageProtocol.origin(string(value.get("maintenance_origin")));
        if(value.containsKey("maintenance_ca"))MaintenanceTrust.certificate(string(value.get("maintenance_ca")));
        return value;
    }

    private static Map<String,Object> blank(){
        Map<String,Object> value=new LinkedHashMap<>();
        value.put("version",1L);
        value.put("policy_floor",0L);
        value.put("heads",new ArrayList<>());
        value.put("pending",new LinkedHashMap<>());
        return value;
    }

    private void save()throws Exception{
        byte[] payload=PublisherAuthority.canonical(data);
        need(payload.length<=LIMIT);
        Path temporary=file.toPath().resolveSibling(file.getName()+".tmp");
        try(FileOutputStream stream=new FileOutputStream(temporary.toFile())){
            stream.write(payload);stream.flush();stream.getFD().sync();
        }
        Files.move(temporary,file.toPath(),StandardCopyOption.REPLACE_EXISTING,
            StandardCopyOption.ATOMIC_MOVE);
    }

    public synchronized Set<String> heads()throws Exception{
        Set<String> result=new HashSet<>();
        for(Object item:array(data.get("heads")))result.add(string(item));
        return result;
    }

    public synchronized long policyFloor()throws Exception{return count(data.get("policy_floor"));}

    /** Explicit trusted Maintenance origin; empty means the authority origin default. */
    public synchronized String maintenanceOrigin()throws Exception{
        Object value=data.get("maintenance_origin");
        return value==null?"":string(value);
    }

    public synchronized void setMaintenanceOrigin(String origin)throws Exception{
        if(origin==null||origin.isEmpty())data.remove("maintenance_origin");
        else{NativePageProtocol.origin(origin);data.put("maintenance_origin",origin);}
        save();
    }

    /** Pinned public Maintenance CA; empty means native page tickets are refused. */
    public synchronized String maintenanceCa()throws Exception{
        Object value=data.get("maintenance_ca");
        return value==null?"":string(value);
    }

    public synchronized void setMaintenanceCa(String pem)throws Exception{
        if(pem==null||pem.isEmpty())data.remove("maintenance_ca");
        else{MaintenanceTrust.certificate(pem);data.put("maintenance_ca",pem);}
        save();
    }

    public synchronized Map<String,Object> pending()throws Exception{
        return new LinkedHashMap<>(object(data.get("pending")));
    }

    public synchronized void recordPending(String identity,Map<String,Object> approval,
            List<Object> chain,String candidateSha)throws Exception{
        hash(identity);
        Map<String,Object> pending=new LinkedHashMap<>();
        pending.put("id",identity);pending.put("approval",approval);
        pending.put("chain",chain);pending.put("candidate",hash(candidateSha));
        data.put("pending",pending);
        save();
    }

    public synchronized void clearPending()throws Exception{
        data.put("pending",new LinkedHashMap<>());
        save();
    }

    /** Called only after the server accepted this exact approval. */
    public synchronized void commit(String identity,long policyVersion)throws Exception{
        hash(identity);
        need(policyVersion>=policyFloor());
        List<Object> heads=new ArrayList<>();
        heads.add(identity);
        data.put("heads",heads);
        data.put("policy_floor",policyVersion);
        data.put("pending",new LinkedHashMap<>());
        save();
    }

    /** Monotonic observation of an installed policy version. */
    public synchronized void observePolicy(long version)throws Exception{
        need(version>=policyFloor());
        if(version>policyFloor()){
            data.put("policy_floor",version);
            save();
        }
    }

    /** Recovery only: clear ancestry/pending facts before a new root is bound. */
    public synchronized void resetForRecovery()throws Exception{
        data=blank();
        save();
    }
}
