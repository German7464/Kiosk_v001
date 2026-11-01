package org.kiosk.harness;
import android.test.InstrumentationTestCase;
import java.nio.file.*;
import java.io.*;
import java.util.*;
import org.kiosk.harness.storage.*;
import org.kiosk.harness.binding.*;

@SuppressWarnings("deprecation")
public class GenericStoreTest extends InstrumentationTestCase {
    private final List<Path> owned=new ArrayList<>();
    private Path root()throws Exception{Path r=getInstrumentation().getTargetContext().getFilesDir().getCanonicalFile().toPath().resolve("generic-store-test-"+UUID.randomUUID());Files.createDirectory(r);owned.add(r);return r;}
    protected PlaybackInputs.Owned input(String name)throws Exception{return GenericInputs.capture(getInstrumentation().getTargetContext(),getInstrumentation().getContext(),name);}
    private String install(FixturePublicationStore s,String name)throws Exception{
        var in=input(name);int reads=in.providerReads().get();try(var c=in.capture()){s.installDevelopment(c,in.permit(),GenericInputs.BUDGET,FixturePublicationStore.NONE);}
        assertEquals(reads,in.providerReads().get());return in.identity();
    }
    private void refused(Work work)throws Exception{try{work.run();fail("refusal required");}catch(IOException expected){assertNull(expected.getCause());}}
    private interface Work{void run()throws Exception;}
    @Override protected void tearDown()throws Exception{for(Path r:owned)try(var walk=Files.walk(r)){for(Path p:walk.sorted(Comparator.reverseOrder()).toList())Files.delete(p);}super.tearDown();}
    public void testTwoGenericIdentitiesAndOwnedPersistence()throws Exception{
        var s=new FixturePublicationStore(root());s.selectMode("kiosk",FixturePublicationStore.NONE);
        String c=install(s,"C");s.saveReady(c,"kiosk",FixturePublicationStore.NONE);String b=install(s,"B");
        assertTrue(s.developmentAuthorized(c));assertTrue(s.developmentAuthorized(b));assertEquals(b,s.pointer());assertEquals(c,s.receipt("kiosk"));
        assertEquals(b,new FixturePublicationStore(s.root).startup().choices().get(0).id());s.selectMode("tv",FixturePublicationStore.NONE);s.saveReady(b);assertEquals(b,s.receipt("tv"));
    }
    public void testRepeatedPrivateStartupDoesNotLeakAuthorityDescriptors()throws Exception{
        var s=new FixturePublicationStore(root());String c=install(s,"C");
        int before=new File("/proc/self/fd").list().length;
        for(int i=0;i<8;i++)assertEquals(c,s.startupChoices().get(0).id());
        int after=new File("/proc/self/fd").list().length;
        android.util.Log.i("GenericStoreDescriptors","before="+before+" after="+after+" startup_loops=8");assertTrue("authority/private read descriptor leak",after<=before+4);
    }
    public void testPointerAndAuthorityBoundaries()throws Exception{
        for(String point:List.of("authority.before_write","authority.before_rename","authority.after_rename","pointer.before_write","pointer.before_rename","pointer.after_rename")){
            var s=new FixturePublicationStore(root());String c=install(s,"C");s.saveReady(c);
            var in=input("B");try(var capture=in.capture()){refused(()->s.installDevelopment(capture,in.permit(),GenericInputs.BUDGET,p->{if(p.equals(point))throw new IOException("fault");}));}
            assertEquals(point.equals("pointer.after_rename")?in.identity():c,s.pointer());assertEquals(c,s.receipt());assertFalse(s.startupChoices().isEmpty());
        }
    }
    public void testInterruptedStageBudgetCancelAndResume()throws Exception{
        var s=new FixturePublicationStore(root());String c=install(s,"C");s.saveReady(c);var in=input("B");var small=in;
        try(var capture=in.capture()){refused(()->s.installDevelopment(capture,small.permit(),new CapturedCandidate.Budget(1,1,0),FixturePublicationStore.NONE));}
        in=input("B");var low=in;try(var capture=in.capture()){refused(()->s.installDevelopment(capture,low.permit(),GenericInputs.BUDGET,p->{if(p.equals("development.space_checked"))throw new IOException("store_disk_full");}));}
        in=input("B");var interrupted=in;try(var capture=in.capture()){refused(()->s.installDevelopment(capture,interrupted.permit(),GenericInputs.BUDGET,p->{if(p.equals("copy_chunk"))throw new IOException("cancelled");}));}
        assertTrue(Files.exists(s.root.resolve(".development-incoming")));assertEquals(c,s.startupChoices().get(0).id());assertEquals(c,s.pointer());
        install(s,"B");assertFalse(Files.exists(s.root.resolve(".development-incoming")));
    }
    public void testModeReceiptCorruptionAndBoundedRecovery()throws Exception{
        var s=new FixturePublicationStore(root());s.selectMode("kiosk",FixturePublicationStore.NONE);String c=install(s,"C");s.saveReady(c,"kiosk",FixturePublicationStore.NONE);
        String b=install(s,"B");refused(()->s.selectMode("tv",p->{if(p.equals("mode.before_rename"))throw new IOException("fault");}));assertEquals("kiosk",s.selectedMode());
        refused(()->s.saveReady(b,"kiosk",p->{if(p.equals("receipt.before_rename"))throw new IOException("fault");}));assertEquals(c,s.receipt("kiosk"));
        Files.write(s.root.resolve("revisions").resolve(b).resolve("view-kiosk/index.html"),new byte[]{1});
        assertEquals(c,s.startupChoices("kiosk").get(0).id());assertEquals(b,s.pointer());
        Files.write(s.root.resolve("active.json"),new byte[]{1});Files.write(s.root.resolve("active.backup.json"),new byte[]{1});
        assertEquals(c,s.startupChoices("kiosk").get(0).id());Files.write(s.root.resolve("last-ready-kiosk.json"),new byte[]{1});assertTrue(s.startupChoices("kiosk").isEmpty());
    }
    public void testLeaseAndReportIsNotAuthority()throws Exception{
        var s=new FixturePublicationStore(root());String c=install(s,"C");var in=input("B");
        try(var capture=in.capture()){refused(()->s.installDevelopment(capture,null,GenericInputs.BUDGET,FixturePublicationStore.NONE));}assertEquals(c,s.pointer());
        var entered=new java.util.concurrent.CountDownLatch(1);var release=new java.util.concurrent.CountDownLatch(1);var failure=new java.util.concurrent.atomic.AtomicReference<Throwable>();
        Thread worker=new Thread(()->{try{var next=input("B");try(var cap=next.capture()){s.installDevelopment(cap,next.permit(),GenericInputs.BUDGET,p->{if(p.equals("development.space_checked")){entered.countDown();try{if(!release.await(5,java.util.concurrent.TimeUnit.SECONDS))throw new IOException("timeout");}catch(InterruptedException stop){Thread.currentThread().interrupt();throw new IOException("cancelled");}}});}}catch(Throwable e){failure.set(e);}});
        worker.start();assertTrue(entered.await(8,java.util.concurrent.TimeUnit.SECONDS));try{refused(()->new FixturePublicationStore(s.root).startup());}finally{release.countDown();worker.join(10000);}assertFalse(worker.isAlive());if(failure.get()!=null)throw new AssertionError(failure.get());
    }
}
