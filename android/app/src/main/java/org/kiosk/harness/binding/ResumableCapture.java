package org.kiosk.harness.binding;

import java.io.*;
import java.nio.channels.*;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import org.json.JSONObject;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.storage.PreparedAdmission;

/** One owned incomplete capture, never a publication store or a source of authority. */
public final class ResumableCapture {
    public record Reply(int status,long length,String etag,String range,String encoding,String retryAfter,InputStream body) implements AutoCloseable {
        public void close()throws IOException{if(body!=null)body.close();}
    }
    public interface Transport {Reply open(CapturedCandidate.Part part,String path,DevelopmentWitness.Pin pin,long offset)throws Exception;}
    public interface Observer {void changed(Stats stats)throws IOException;}
    public static final class Stats {
        public long logicalBytes;public boolean transferring;public final String candidate;public long reusedBytes,reusedAcceptedBytes,downloadedBytes,resumedOffset,stagedBytes;public int artifactGets,reusedFiles;public String reason="none";public org.json.JSONArray requests=new org.json.JSONArray();
        public Stats(String candidate){this.candidate=candidate;}
        public JSONObject json()throws Exception{return new JSONObject().put("candidate",candidate).put("reused_bytes",reusedBytes).put("reused_accepted_bytes",reusedAcceptedBytes).put("downloaded_bytes",downloadedBytes).put("resumed_offset",resumedOffset).put("staged_bytes",stagedBytes).put("artifact_gets",artifactGets).put("reused_files",reusedFiles).put("restart_reason",reason).put("requests",requests);}
    }
    public static final class TransferFailure extends IOException {
        public final int status;public final long retryMillis;
        public TransferFailure(String reason,int status,long retryMillis){super(reason);this.status=status;this.retryMillis=retryMillis;}
    }
    private static final String OWNER="Kiosk/ResumableCapture/v1";
    private final Path root,stage,reuse;
    private final PreparedAdmission.Request request;
    private final Map<CapturedCandidate.Part,Map<String,DevelopmentWitness.Pin>> pins;
    private final Transport transport;private final Observer observer;private final Stats stats;
    private JSONObject journal;private long total;
    private ResumableCapture(Path root,Path reuse,PreparedAdmission.Request request,Transport transport,Observer observer,Stats stats){
        this.root=root;stage=root.resolve("incomplete");this.reuse=reuse;this.request=request;this.transport=transport;this.observer=observer;this.stats=stats;
        pins=Map.of(CapturedCandidate.Part.PACKAGE,request.pkg().files(),CapturedCandidate.Part.KIOSK,request.kiosk().files(),CapturedCandidate.Part.TV,request.tv().files());
    }
    public static CapturedCandidate capture(Path root,Path reuse,PreparedAdmission.Request request,String binding,boolean full,Transport transport,Observer observer,Stats stats)throws Exception {
        root=root.toAbsolutePath().normalize();safeAncestors(root);Files.createDirectories(root);
        Path lockPath=root.resolve("transfer.lock");if(Files.isSymbolicLink(lockPath))throw new IOException("unowned_capture");
        FileChannel channel=FileChannel.open(lockPath,StandardOpenOption.CREATE,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS);FileLock lock;
        try{lock=channel.tryLock();if(lock==null)throw new IOException("transfer_busy");}catch(Exception e){channel.close();throw new IOException("transfer_busy");}
        AutoCloseable lease=()->{lock.release();channel.close();};boolean handed=false;
        try{
            var c=new ResumableCapture(root,reuse,request,transport,observer,stats);c.prepare(binding,full);c.run();
            var facts=new CapturedCandidate.PreparedFacts(request.pkg(),request.renderer(),request.kiosk(),request.tv());
            var captured=CapturedCandidate.adopt(c.stage,c.pins,facts,lease);handed=true;return captured;
        }finally{if(!handed)lease.close();}
    }
    private static void safeAncestors(Path path)throws IOException{for(Path p=path;p!=null;p=p.getParent())if(Files.isSymbolicLink(p))throw new IOException("unowned_capture");}
    public static void discardIncomplete(Path root)throws Exception{
        root=root.toAbsolutePath().normalize();safeAncestors(root);if(!Files.exists(root))return;
        try(FileChannel channel=FileChannel.open(root.resolve("transfer.lock"),StandardOpenOption.CREATE,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS)){
            FileLock lock;try{lock=channel.tryLock();}catch(OverlappingFileLockException busy){throw new IOException("transfer_busy");}
            if(lock==null)throw new IOException("transfer_busy");try{
                Path stage=root.resolve("incomplete");if(!Files.exists(stage))return;safeAncestors(stage);
                if(!OWNER.equals(new String(read(stage.resolve("owner"),128),java.nio.charset.StandardCharsets.UTF_8)))throw new IOException("unowned_capture");
                CaptureFiles.deleteOwned(stage);
            }finally{lock.release();}
        }
    }
    private static byte[] read(Path file,int cap)throws IOException {return LocalView.readBounded(Files.newInputStream(file,LinkOption.NOFOLLOW_LINKS),cap);}
    private void prepare(String binding,boolean full)throws Exception {
        request.checkBudgets();long count=4;total=32768;
        for(var group:pins.values())for(var p:group.entrySet()){
            if(!LocalView.safePath(p.getKey())||p.getValue().size()<0||p.getValue().size()>request.storage().maxBytes()-total||++count>request.storage().maxFiles())throw new IOException("capture_budget");total+=p.getValue().size();
        }
        if(Files.exists(stage,LinkOption.NOFOLLOW_LINKS)){
            safeAncestors(stage);Path owner=stage.resolve("owner");
            if(!Files.exists(owner)){try(var children=Files.list(stage)){if(children.findAny().isPresent())throw new IOException("unowned_capture");}Files.delete(stage);}
            else {
                if(!OWNER.equals(new String(read(owner,128),java.nio.charset.StandardCharsets.UTF_8)))throw new IOException("unowned_capture");
                try{journal=new JSONObject(new String(read(stage.resolve("transfer.json"),8192),java.nio.charset.StandardCharsets.UTF_8));}catch(Exception invalid){stats.reason="journal_invalid";}
                if(full||journal==null||!binding.equals(journal.optString("binding"))){stats.reason=full?"full_resync":journal==null?"journal_invalid":"assignment_changed";CaptureFiles.deleteOwned(stage);journal=null;}
            }
        }
        if(!Files.exists(stage)){
            Files.createDirectory(stage);try(FileOutputStream out=new FileOutputStream(stage.resolve("owner").toFile())){out.write(OWNER.getBytes(java.nio.charset.StandardCharsets.UTF_8));out.getFD().sync();}
            journal=new JSONObject().put("version",1).put("binding",binding);save();
        }
        for(var part:CapturedCandidate.Part.values())Files.createDirectories(stage.resolve(part.name()));
        stats.downloadedBytes=journal.optLong("received",0);stats.reusedBytes=journal.optLong("reused",0);stats.reusedAcceptedBytes=journal.optLong("reused_accepted",0);stats.reusedFiles=journal.optInt("reused_files",0);stats.artifactGets=journal.optInt("gets",0);if(journal.optJSONArray("requests")!=null)stats.requests=journal.getJSONArray("requests");
        // Account all owned temporary captures, not accepted/recovery revisions. Never evict them.
        long bytes=0;int files=0,nodes=0;try(var walk=Files.walk(root)){for(var it=walk.iterator();it.hasNext();){Path p=it.next();if(++nodes>request.storage().maxFiles()*4L+128)throw new IOException("capture_budget");if(Files.isSymbolicLink(p))throw new IOException("unowned_capture");if(Files.isRegularFile(p,LinkOption.NOFOLLOW_LINKS)){bytes=Math.addExact(bytes,Files.size(p));if(++files>request.storage().maxFiles())throw new IOException("capture_budget");}}}
        long stageFiles;try(var walk=Files.walk(stage)){stageFiles=walk.filter(p->Files.isRegularFile(p,LinkOption.NOFOLLOW_LINKS)).count();}
        if(files-stageFiles+count>request.storage().maxFiles())throw new IOException("capture_budget");
        long staged=treeBytes(stage);if(bytes>request.storage().maxBytes()||Math.addExact(bytes-staged,total)>request.storage().maxBytes())throw new IOException("capture_budget");
        long needed=Math.max(0,total-staged);if(root.toFile().getUsableSpace()<Math.addExact(request.storage().minFreeBytes(),needed))throw new IOException("capture_disk_full");
        observer.changed(stats);
    }
    private static long treeBytes(Path root)throws IOException{long count=0;try(var walk=Files.walk(root)){for(var it=walk.iterator();it.hasNext();){var p=it.next();if(Files.isSymbolicLink(p))throw new IOException("unowned_capture");if(Files.isRegularFile(p,LinkOption.NOFOLLOW_LINKS))count=Math.addExact(count,Files.size(p));}}return count;}
    private void save()throws Exception{
        journal.put("received",stats.downloadedBytes).put("reused",stats.reusedBytes).put("reused_accepted",stats.reusedAcceptedBytes).put("reused_files",stats.reusedFiles).put("gets",stats.artifactGets).put("requests",stats.requests);
        byte[] bytes=journal.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);if(bytes.length>8192)throw new IOException("capture_journal_bound");
        Path temp=stage.resolve("transfer.tmp");if(Files.isSymbolicLink(temp))throw new IOException("unowned_capture");
        try(FileOutputStream out=new FileOutputStream(temp.toFile())){out.write(bytes);out.getFD().sync();}
        Files.move(temp,stage.resolve("transfer.json"),StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE);
    }
    private static String digest(Path path)throws Exception{try(InputStream in=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS)){MessageDigest md=MessageDigest.getInstance("SHA-256");byte[] block=new byte[65536];int n;while((n=in.read(block))!=-1)md.update(block,0,n);return hex(md.digest());}}
    private static String hex(byte[] bytes){StringBuilder s=new StringBuilder();for(byte b:bytes)s.append(String.format(Locale.ROOT,"%02x",b&255));return s.toString();}
    private static boolean matches(Path path,DevelopmentWitness.Pin pin)throws Exception{return Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)&&!Files.isSymbolicLink(path)&&Files.size(path)==pin.size()&&digest(path).equals(pin.sha256());}
    private Path findReusable(Path root,DevelopmentWitness.Pin pin,boolean revisions)throws Exception {
        if(root==null||!Files.isDirectory(root,LinkOption.NOFOLLOW_LINKS))return null;safeAncestors(root);int visited=0;
        try(var walk=Files.walk(root,32)){for(var it=walk.iterator();it.hasNext()&&visited++<request.storage().maxFiles()*3;){Path p=it.next();if(Files.isSymbolicLink(p))throw new IOException("unowned_reuse_path");
            if(revisions){Path rel=root.relativize(p);if(rel.getNameCount()<3||!Set.of("package","view","view-kiosk").contains(rel.getName(1).toString()))continue;}
            if(matches(p,pin))return p;
        }}return null;
    }
    private void run()throws Exception{
        for(var part:CapturedCandidate.Part.values())for(var item:new TreeMap<>(pins.get(part)).entrySet()){
            String path=item.getKey();var pin=item.getValue();Path dest=CaptureFiles.resolve(stage.resolve(part.name()),path);safeAncestors(dest);Files.createDirectories(dest.getParent());
            if(matches(dest,pin)){stats.stagedBytes+=pin.size();stats.logicalBytes+=pin.size();observer.changed(stats);continue;}
            if(!Files.exists(dest)||Files.size(dest)==0){
                Path existing=findReusable(stage,pin,false);boolean accepted=existing==null;if(existing==null)existing=findReusable(reuse,pin,true);
                if(existing!=null&&!existing.equals(dest)){
                    try(InputStream in=Files.newInputStream(existing,LinkOption.NOFOLLOW_LINKS);FileOutputStream out=new FileOutputStream(dest.toFile())){byte[] block=new byte[65536];int n;long copied=0;while((n=in.read(block))!=-1){if(n>pin.size()-copied)throw new IOException("reuse_changed");if(root.toFile().getUsableSpace()<request.storage().minFreeBytes()+n)throw new IOException("capture_disk_full");out.write(block,0,n);copied+=n;}out.getFD().sync();}
                    if(!matches(dest,pin))throw new IOException("reuse_changed");stats.logicalBytes+=pin.size();stats.reusedBytes+=pin.size();if(accepted)stats.reusedAcceptedBytes+=pin.size();stats.reusedFiles++;save();observer.changed(stats);continue;
                }
            }
            transfer(part,path,pin,dest);observer.changed(stats);
        }
    }
    private long reconcile(CapturedCandidate.Part part,String path,DevelopmentWitness.Pin pin,Path dest)throws Exception{
        if(!Files.exists(dest))return 0;
        JSONObject active=journal.optJSONObject("active");long actual=Files.size(dest),recorded=active==null?-1:active.optLong("length",-1);
        boolean owned=active!=null&&part.name().equals(active.optString("part"))&&path.equals(active.optString("path"))&&pin.sha256().equals(active.optString("sha256"))&&pin.size()==active.optLong("size",-1);
        if(!owned||recorded<0||recorded>actual||recorded>=pin.size()){truncate(dest);stats.reason="prefix_reconcile";return 0;}
        if(actual!=recorded)try(RandomAccessFile file=new RandomAccessFile(dest.toFile(),"rw")){file.setLength(recorded);file.getFD().sync();stats.reason="uncommitted_tail";}
        if(!digest(dest).equals(active.optString("prefix_sha256"))){truncate(dest);stats.reason="prefix_corrupt";return 0;}return recorded;
    }
    private static void truncate(Path path)throws Exception{try(FileOutputStream out=new FileOutputStream(path.toFile())){out.getFD().sync();}}
    public static long retryDelay(String value){try{long seconds=Long.parseLong(value);return Math.max(5000,Math.min(120000,Math.multiplyExact(seconds,1000)));}catch(Exception invalid){return 10000;}}
    private static Object header(String value){return value==null?JSONObject.NULL:value.length()>128||value.indexOf('\r')>=0||value.indexOf('\n')>=0?"invalid_header":value;}
    public static long validate(Reply r,DevelopmentWitness.Pin pin,long offset)throws IOException{
        if(r.status()==401||r.status()==409||r.status()==429)throw new TransferFailure("transfer_http_"+r.status(),r.status(),r.status()==429?retryDelay(r.retryAfter()):0);
        if(r.status()==416)return -1;
        if(r.status()!=200&&r.status()!=206)throw new TransferFailure("transfer_http_refused",r.status(),0);
        if(r.encoding()!=null&&!r.encoding().equalsIgnoreCase("identity"))throw new IOException("transfer_encoding");
        if(!("\""+pin.sha256()+"\"").equals(r.etag()))throw new IOException("transfer_validator");
        long start=r.status()==200?0:offset;
        if(r.status()==206&&(offset<=0||!("bytes "+offset+"-"+(pin.size()-1)+"/"+pin.size()).equals(r.range())))throw new IOException("transfer_range");
        if(r.status()==200&&r.range()!=null)throw new IOException("transfer_range");
        if(r.length()!=pin.size()-start)throw new IOException("transfer_length");return start;
    }
    private void transfer(CapturedCandidate.Part part,String path,DevelopmentWitness.Pin pin,Path dest)throws Exception {
        long offset=reconcile(part,path,pin,dest);long prior=stats.logicalBytes;
        for(int attempt=0;attempt<2;attempt++){
            stats.artifactGets++;try(Reply reply=transport.open(part,path,pin,offset)){
                if(stats.requests.length()>=12)stats.requests.remove(0);
                stats.requests.put(new JSONObject().put("part",part.name()).put("path_sha256",LocalView.digest(path.getBytes(java.nio.charset.StandardCharsets.UTF_8))).put("file_sha256",pin.sha256()).put("size",pin.size()).put("offset",offset).put("status",reply.status()).put("etag",header(reply.etag())).put("content_range",header(reply.range())).put("if_range",offset==0?JSONObject.NULL:"\""+pin.sha256()+"\"").put("range",offset==0?JSONObject.NULL:"bytes="+offset+"-"));save();
                long start=validate(reply,pin,offset);
                if(start<0){if(reply.length()!=0||!("bytes */"+pin.size()).equals(reply.range()))throw new IOException("transfer_416_invalid");truncate(dest);stats.reason="range_416";journal.remove("active");save();throw new TransferFailure("range_416_refetch",416,0);}
                if(start==0){if(offset>0)stats.reason="validator_full_200";truncate(dest);}else stats.resumedOffset=start;
                MessageDigest md=MessageDigest.getInstance("SHA-256");if(start>0)try(InputStream old=Files.newInputStream(dest)){byte[] block=new byte[65536];int n;while((n=old.read(block))!=-1)md.update(block,0,n);}
                stats.transferring=true;stats.logicalBytes=prior+start;observer.changed(stats);long written=start;try(FileOutputStream out=new FileOutputStream(dest.toFile(),start>0)){
                    byte[] block=new byte[65536];int n;while((n=reply.body().read(block))!=-1){
                        if(Thread.currentThread().isInterrupted())throw new InterruptedIOException("transfer_cancelled");if(n>pin.size()-written)throw new IOException("transfer_trailing");
                        if(root.toFile().getUsableSpace()<request.storage().minFreeBytes()+n)throw new IOException("capture_disk_full");
                        out.write(block,0,n);md.update(block,0,n);written+=n;out.getFD().sync();
                        String prefix;try{prefix=hex(((MessageDigest)md.clone()).digest());}catch(CloneNotSupportedException unavailable){prefix=digest(dest);}
                        journal.put("active",new JSONObject().put("part",part.name()).put("path",path).put("size",pin.size()).put("sha256",pin.sha256()).put("length",written).put("prefix_sha256",prefix));
                        stats.downloadedBytes+=n;stats.logicalBytes=prior+written;save();observer.changed(stats);
                    }
                }
                if(written!=pin.size())throw new IOException("transfer_short");
                if(!matches(dest,pin)){truncate(dest);offset=0;stats.reason="complete_hash_mismatch";if(attempt==1)throw new IOException("transfer_hash_exhausted");continue;}
                journal.remove("active");save();return;
            }
        }
        throw new IOException("transfer_exhausted");
    }
}
