package org.kiosk.harness.binding;

import org.junit.Test;
import static org.junit.Assert.*;
import java.io.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.*;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.storage.PreparedAdmission;

public class ResumableCaptureTest {
    interface Checked{void run()throws Exception;}
    void refused(Checked c)throws Exception{try{c.run();fail("must refuse");}catch(AssertionError e){throw e;}catch(Exception expected){}}
    final class Fixture implements AutoCloseable {
        final Path source=Path.of(System.getProperty("tvPaginationRoot")).resolve("empty"),owned=Files.createTempDirectory("resume-unit-"),root=owned.resolve("capture"),reuse=owned.resolve("accepted");
        final JSONObject prep;final PreparedAdmission.Request request;final List<Long> imageOffsets=new ArrayList<>();String mode="normal";boolean failed;
        Fixture()throws Exception{
            prep=new JSONObject(new String(Files.readAllBytes(source.resolve("preparation.json")),StandardCharsets.UTF_8));String id=prep.getString("package_identity");
            var renderer=new DevelopmentWitness.Renderer(prep.getString("renderer_identity"),"839bb0c182822f7530e0d9c403b3ebddcfff214f871fb52c45d68a6dc68e6238","6c2be9997f2f817149b4cc9227091399336f066ab2762ccf542ca43d436b29f1");
            var pkg=new DevelopmentWitness.Package(id,prep.getString("raw_manifest_sha256"),pins(prep.getJSONObject("package").getJSONObject("files")));
            var k=new DevelopmentWitness.Artifact("kiosk",id,renderer.identity(),pins(prep.getJSONObject("views").getJSONObject("kiosk").getJSONObject("files")));
            var t=new DevelopmentWitness.Artifact("tv",id,renderer.identity(),pins(prep.getJSONObject("views").getJSONObject("tv").getJSONObject("files")));
            request=new PreparedAdmission.Request(pkg,renderer,k,t,"unit-authorized-metadata",Map.of(),new PreparedAdmission.ImageBudget(2000000,33554432,5000,15000),new CapturedCandidate.Budget(8*1024*1024,100,1024));
            for(var part:CapturedCandidate.Part.values()){
                Path base=partRoot(part);String name=part==CapturedCandidate.Part.PACKAGE?"package":part==CapturedCandidate.Part.KIOSK?"view-kiosk":"view";
                try(var files=Files.walk(base)){for(Path f:files.filter(Files::isRegularFile).toList()){
                    String rel=base.relativize(f).toString().replace('\\','/');if(rel.endsWith("site_icon.png"))continue;
                    Path dest=reuse.resolve(id).resolve(name).resolve(rel);Files.createDirectories(dest.getParent());Files.copy(f,dest);
                }}
            }
        }
        Map<String,DevelopmentWitness.Pin> pins(JSONObject json)throws Exception{Map<String,DevelopmentWitness.Pin> result=new TreeMap<>();for(var it=json.keys();it.hasNext();){String name=it.next();var p=json.getJSONObject(name);result.put(name,new DevelopmentWitness.Pin(p.getLong("size"),p.getString("sha256")));}return result;}
        Path partRoot(CapturedCandidate.Part part)throws Exception{return source.resolve(part==CapturedCandidate.Part.PACKAGE?prep.getJSONObject("package").getString("path"):prep.getJSONObject("views").getJSONObject(part==CapturedCandidate.Part.KIOSK?"kiosk":"tv").getString("path"));}
        ResumableCapture.Reply open(CapturedCandidate.Part part,String path,DevelopmentWitness.Pin pin,long offset)throws Exception{
            byte[] full=Files.readAllBytes(partRoot(part).resolve(path));boolean image=path.endsWith("site_icon.png");if(image)imageOffsets.add(offset);
            if(mode.equals("bad-hash")&&image)full[0]^=1;
            if(mode.equals("416")&&image&&offset>0)return new ResumableCapture.Reply(416,0,null,"bytes */"+pin.size(),null,null,new ByteArrayInputStream(new byte[0]));
            boolean reset=mode.equals("200");int status=offset>0&&!reset?206:200;long start=status==206?offset:0;InputStream body=new ByteArrayInputStream(full,(int)start,full.length-(int)start);
            if(mode.equals("interrupt")&&image&&!failed){failed=true;body=new FilterInputStream(body){long left=131072;
                public int read(byte[] b,int off,int n)throws IOException{if(left==0)throw new IOException("owned_cancel");int v=in.read(b,off,(int)Math.min(n,left));if(v>0)left-=v;return v;}
            };}
            return new ResumableCapture.Reply(status,full.length-start,"\""+pin.sha256()+"\"",status==206?"bytes "+start+"-"+(full.length-1)+"/"+full.length:null,null,null,body);
        }
        CapturedCandidate capture(String binding,ResumableCapture.Stats stats)throws Exception{return ResumableCapture.capture(root,reuse,request,binding,false,this::open,s->{},stats);}
        void interrupt()throws Exception{mode="interrupt";refused(()->capture("assignment-1",new ResumableCapture.Stats(request.pkg().canonicalIdentity())));mode="normal";assertEquals(131072,Files.size(prefix()));}
        Path prefix(){return root.resolve("incomplete/PACKAGE/resources/static/img/site_icon.png");}
        public void close()throws Exception{try(var paths=Files.walk(owned)){for(Path p:paths.sorted(Comparator.reverseOrder()).toList())Files.delete(p);}}
    }
    @Test public void interruptedFreshCaptureResumesAndReusesWithoutDuplicatePayload()throws Exception{
        try(var f=new Fixture()){f.interrupt();var stats=new ResumableCapture.Stats(f.request.pkg().canonicalIdentity());try(var c=f.capture("assignment-1",stats)){
            assertEquals(f.request.pkg().canonicalIdentity(),c.report().callerAttestedCanonicalPackageIdentity());assertEquals(131072,stats.resumedOffset);assertTrue(stats.reusedAcceptedBytes>0);assertEquals(List.of(0L,131072L),f.imageOffsets);
            assertTrue(stats.downloadedBytes<1000000);assertTrue(Files.exists(f.root.resolve("incomplete")));
        }assertFalse(Files.exists(f.root.resolve("incomplete")));}
    }
    @Test public void corruptPrefixAndUncommittedTailReconcileBeforeAppend()throws Exception{
        try(var f=new Fixture()){f.interrupt();byte[] b=Files.readAllBytes(f.prefix());b[0]^=1;Files.write(f.prefix(),b);var stats=new ResumableCapture.Stats("candidate");try(var c=f.capture("assignment-1",stats)){assertEquals("prefix_corrupt",stats.reason);assertEquals(0L,(long)f.imageOffsets.get(1));}}
        try(var f=new Fixture()){f.interrupt();Files.write(f.prefix(),new byte[]{1,2,3},StandardOpenOption.APPEND);var stats=new ResumableCapture.Stats("candidate");try(var c=f.capture("assignment-1",stats)){assertEquals("uncommitted_tail",stats.reason);assertEquals(131072,stats.resumedOffset);}}
    }
    @Test public void full200ReplacesAnd416RequiresBoundedRefetch()throws Exception{
        try(var f=new Fixture()){f.interrupt();f.mode="200";var stats=new ResumableCapture.Stats("candidate");try(var c=f.capture("assignment-1",stats)){assertEquals("validator_full_200",stats.reason);}}
        try(var f=new Fixture()){f.interrupt();f.mode="416";try{f.capture("assignment-1",new ResumableCapture.Stats("candidate"));fail();}catch(ResumableCapture.TransferFailure failure){assertEquals(416,failure.status);}assertEquals(0,Files.size(f.prefix()));f.mode="normal";try(var c=f.capture("assignment-1",new ResumableCapture.Stats("candidate"))){assertEquals(0L,(long)f.imageOffsets.get(2));}}
    }
    @Test public void assignmentChangeAndExplicitResyncDiscardOnlyOwnedIncomplete()throws Exception{
        try(var f=new Fixture()){f.interrupt();var stats=new ResumableCapture.Stats("candidate");try(var c=f.capture("assignment-2",stats)){assertEquals("assignment_changed",stats.reason);assertEquals(0L,(long)f.imageOffsets.get(1));}}
        try(var f=new Fixture()){f.interrupt();long before;try(var s=Files.walk(f.reuse)){before=s.filter(Files::isRegularFile).count();}ResumableCapture.discardIncomplete(f.root);assertFalse(Files.exists(f.root.resolve("incomplete")));try(var s=Files.walk(f.reuse)){assertEquals(before,s.filter(Files::isRegularFile).count());}try(var c=f.capture("assignment-1",new ResumableCapture.Stats("candidate"))) {}}
    }
    @Test public void budgetsAndLeaseAndIdempotentCloseProtectOtherCaptures()throws Exception{
        try(var f=new Fixture()){var r=f.request;var small=new PreparedAdmission.Request(r.pkg(),r.renderer(),r.kiosk(),r.tv(),r.preparationReference(),r.windowsImages(),r.images(),new CapturedCandidate.Budget(1000,100,0));refused(()->ResumableCapture.capture(f.root,f.reuse,small,"assignment-1",false,f::open,s->{},new ResumableCapture.Stats("candidate")));
            var first=f.capture("assignment-1",new ResumableCapture.Stats("candidate"));refused(()->f.capture("assignment-1",new ResumableCapture.Stats("candidate")));refused(()->ResumableCapture.discardIncomplete(f.root));first.close();var second=f.capture("assignment-1",new ResumableCapture.Stats("candidate"));first.close();assertTrue(Files.exists(f.root.resolve("incomplete")));second.close();}
    }
    @Test public void strictHeadersRetryAndErrorSemantics()throws Exception{
        var pin=new DevelopmentWitness.Pin(20,"a".repeat(64));
        assertEquals(5,ResumableCapture.validate(new ResumableCapture.Reply(206,15,"\""+pin.sha256()+"\"","bytes 5-19/20",null,null,null),pin,5));
        for(var reply:List.of(new ResumableCapture.Reply(206,15,"W/\""+pin.sha256()+"\"","bytes 5-19/20",null,null,null),new ResumableCapture.Reply(206,15,"\""+pin.sha256()+"\"","bytes 4-19/20",null,null,null),new ResumableCapture.Reply(200,15,"\""+pin.sha256()+"\"",null,null,null,null),new ResumableCapture.Reply(200,20,"\""+pin.sha256()+"\"",null,"gzip",null,null)))refused(()->ResumableCapture.validate(reply,pin,5));
        for(int code:List.of(401,409,429))try{ResumableCapture.validate(new ResumableCapture.Reply(code,0,null,null,null,"5",null),pin,5);fail();}catch(ResumableCapture.TransferFailure failure){assertEquals(code,failure.status);if(code==429)assertEquals(5000,failure.retryMillis);}
        assertEquals(120000,ResumableCapture.retryDelay("999999"));assertEquals(10000,ResumableCapture.retryDelay("invalid"));
    }
    @Test public void abandonedCaptureAccountingAndBoundedWholeHashFailure()throws Exception{
        try(var f=new Fixture()){Files.createDirectories(f.root);for(int i=0;i<95;i++)Files.write(f.root.resolve("old-"+i),new byte[0]);refused(()->f.capture("assignment-1",new ResumableCapture.Stats("candidate")));assertTrue(Files.exists(f.reuse));}
        try(var f=new Fixture()){f.mode="bad-hash";refused(()->f.capture("assignment-1",new ResumableCapture.Stats("candidate")));assertEquals(2,f.imageOffsets.size());assertEquals(0,Files.size(f.prefix()));assertTrue(Files.exists(f.reuse));}
    }
}
