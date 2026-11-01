package org.kiosk.harness;

import android.test.InstrumentationTestCase;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.storage.*;

/** Actual private Android filesystem tests; hooks and damaged sources exist only in test APK. */
@SuppressWarnings("deprecation")
public class StoreTest extends InstrumentationTestCase {
    private final List<Path> roots=new ArrayList<>();
    private static void writeText(Path path,String text) throws IOException {Files.write(path,text.getBytes(java.nio.charset.StandardCharsets.UTF_8));}
    private static final String A=PublicationFixtures.A.identity(),B=PublicationFixtures.B.identity();
    private Path root() throws Exception {
        Path base=getInstrumentation().getTargetContext().getFilesDir().getCanonicalFile().toPath();
        Path root=base.resolve("store-test-"+UUID.randomUUID());Files.createDirectory(root);roots.add(root);return root;
    }
    public void testPrivateFilesystemMetadata() throws Exception {
        Path path=root();int index=0;
        for(Path p=path;p!=null;p=p.getParent()){
            var stat=android.system.Os.lstat(p.toString());
            android.util.Log.i("StoreFsDiagnostic","ancestor="+(index++)+" nioLink="+Files.isSymbolicLink(p)+" nioDir="+Files.isDirectory(p,LinkOption.NOFOLLOW_LINKS)+" nativeLink="+android.system.OsConstants.S_ISLNK(stat.st_mode)+" nativeDir="+android.system.OsConstants.S_ISDIR(stat.st_mode));
        }
    }
    private FixturePublicationStore store(Path root){return new FixturePublicationStore(root);}
    private LocalView.Source source(String key,boolean view){return new FixtureAssetSource(getInstrumentation().getTargetContext().getAssets(),PublicationFixtures.key(key),view,new AtomicInteger());}
    private FixturePublicationStore.Selection install(FixturePublicationStore store,String key) throws Exception{return store.install(key,source(key,false),source(key,true),FixturePublicationStore.NONE);}
    private FixturePublicationStore.Selection both(FixturePublicationStore store,String key) throws Exception {
        return store.install(key,source(key,false),source(key,true),new FixtureAssetSource(getInstrumentation().getTargetContext().getAssets(),PublicationFixtures.key(key),"kiosk",new AtomicInteger()),store.selectedMode(),FixturePublicationStore.NONE);
    }
    public void testModesLegacyTVReceiptAndNoPackageReimport() throws Exception {
        Path root=root();readyA(root);var store=store(root);byte[] receipt=Files.readAllBytes(root.resolve("last-ready-tv.json"));
        assertTrue(new String(receipt,StandardCharsets.UTF_8).contains("b4cb5f181559e8f40fccb99ea0edb631fcb18c3c9e60d47a49347deee3bfa354"));
        assertFalse(Files.exists(root.resolve("selected-mode.json")));assertEquals("tv",store.selectedMode());assertEquals("tv",store.startup().mode());assertEquals("tv",store.startup().choices().get(0).view().mode);
        refused(()->store.saveReady(A,"kiosk",FixturePublicationStore.NONE));assertEquals("invalid_or_absent",store.receipt("kiosk"));
        Map<String,String> before=tree(root.resolve("revisions"));AtomicInteger packageReads=new AtomicInteger(),viewReads=new AtomicInteger();var f=PublicationFixtures.A;
        store.install("A",new FixtureAssetSource(getInstrumentation().getTargetContext().getAssets(),f,false,packageReads),new FixtureAssetSource(getInstrumentation().getTargetContext().getAssets(),f,true,viewReads),new FixtureAssetSource(getInstrumentation().getTargetContext().getAssets(),f,"kiosk",viewReads),"tv",FixturePublicationStore.NONE);
        assertEquals(0,packageReads.get());assertEquals(5,viewReads.get());assertEquals(before,tree(root.resolve("revisions")));assertTrue(Arrays.equals(receipt,Files.readAllBytes(root.resolve("last-ready-tv.json"))));
        assertEquals("kiosk",store.selectMode("kiosk",FixturePublicationStore.NONE).view().mode);assertEquals("kiosk",new FixturePublicationStore(root).selectedMode());event("legacy_TV_and_explicit_kiosk_cache_without_package_import",store);
    }
    public void testModesAtomicWriteBoundaries() throws Exception {
        for(String point:List.of("mode.before_write","mode.before_rename","mode.after_rename")){
            Path root=root();var store=store(root);both(store,"A");store.saveReady(A);var fault=new FixturePublicationStore(root,p->{if(p.equals(point))throw new IOException("mode_fault");});
            refused(()->fault.selectMode("kiosk",FixturePublicationStore.NONE));String expected=point.equals("mode.after_rename")?"kiosk":"tv";assertEquals(expected,store.selectedMode());assertEquals(expected,store.startup().mode());assertEquals(expected,store.startup().choices().get(0).view().mode);assertEquals(A,store.pointer());assertEquals(A,store.receipt("tv"));assertEquals("invalid_or_absent",store.receipt("kiosk"));event(point,store);
        }
    }
    public void testModesNoCrossReceiptOnMissingOrCorruptKiosk() throws Exception {
        Path root=root();var store=store(root);both(store,"A");store.saveReady(A);Path view=root.resolve("kiosk-views").resolve(A).resolve("view/index.html");byte[] bytes=Files.readAllBytes(view);
        Files.delete(view);refused(()->store.selectMode("kiosk",FixturePublicationStore.NONE));assertEquals("tv",store.selectedMode());assertEquals(A,store.receipt("tv"));
        Files.write(view,bytes);store.selectMode("kiosk",FixturePublicationStore.NONE);Files.write(root.resolve("last-ready-kiosk.json"),Files.readAllBytes(root.resolve("last-ready-tv.json")));writeText(view,"bad");
        assertTrue(store.startupChoices("kiosk").isEmpty());assertEquals(A,store.startupChoices("tv").get(0).id());assertEquals("invalid_or_absent",store.receipt("kiosk"));event("mode_receipt_cannot_cross",store);
    }
    public void testModesConfirmedFallbackOnlyWithinSelectedMode() throws Exception {
        Path root=root();var store=store(root);both(store,"A");store.selectMode("kiosk",FixturePublicationStore.NONE);store.saveReady(A,"kiosk",FixturePublicationStore.NONE);both(store,"B");
        writeText(root.resolve("kiosk-views").resolve(B).resolve("view/index.html"),"bad");assertEquals(List.of(A),store.startupChoices("kiosk").stream().map(FixturePublicationStore.Selection::id).toList());assertEquals(B,store.pointer());assertEquals("kiosk",store.selectedMode());assertEquals(B,store.startupChoices("tv").get(0).id());event("same_mode_confirmed_A_pointer_B",store);
    }
    public void testModesKioskStageResumeAndCorruptSelectedMode() throws Exception {
        Path root=root();readyA(root);AtomicBoolean fault=new AtomicBoolean();var store=new FixturePublicationStore(root,p->{if(p.equals("copy_chunk")&&fault.compareAndSet(false,true))throw new IOException("interrupted_kiosk_copy");});
        refused(()->both(store,"A"));assertTrue(Files.exists(root.resolve(".kiosk-incoming")));refused(()->both(store,"B"));assertEquals(A,store.startupChoices("tv").get(0).id());
        both(store(root),"A");assertFalse(Files.exists(root.resolve(".kiosk-incoming")));assertNotNull(store.selectMode("kiosk",FixturePublicationStore.NONE));
        writeText(root.resolve("selected-mode.json"),"{\"schema\":true,\"mode\":\"kiosk\"}");refused(store::selectedMode);assertEquals("invalid",store.modeOrInvalid());assertEquals(A,store.receipt("tv"));event("invalid_mode_safe_no_guessed_mode",store);
    }
    public void testModesReceiptFailureDoesNotTouchOtherMode() throws Exception {
        Path root=root();var store=store(root);both(store,"A");store.saveReady(A);byte[] tv=Files.readAllBytes(root.resolve("last-ready-tv.json"));store.selectMode("kiosk",FixturePublicationStore.NONE);
        var fault=new FixturePublicationStore(root,p->{if(p.equals("receipt.before_rename"))throw new IOException("receipt_fault");});refused(()->fault.saveReady(A,"kiosk",FixturePublicationStore.NONE));
        assertEquals("kiosk",store.selectedMode());assertTrue(Arrays.equals(tv,Files.readAllBytes(root.resolve("last-ready-tv.json"))));assertEquals("invalid_or_absent",store.receipt("kiosk"));assertEquals(A,store.pointer());event("mode_receipt_pending_other_receipt_unchanged",store);
    }
    private void readyA(Path root) throws Exception {var store=store(root);install(store,"A");store.saveReady(A);}
    private void event(String name,FixturePublicationStore store) throws Exception {
        android.util.Log.i("StoreTest",new org.json.JSONObject().put("scenario",name).put("pointer",store.pointer()).put("receipt",store.receipt()).put("choices",store.startupChoices().stream().map(FixturePublicationStore.Selection::id).toList()).toString());
    }
    interface Action {void run() throws Exception;}
    private void refused(Action action) throws Exception {
        try{action.run();fail("expected refusal");}catch(IOException e){assertNull(e.getCause());assertFalse(e.getMessage().contains("/"));}
    }
    private Map<String,String> tree(Path root) throws Exception {
        Map<String,String> result=new TreeMap<>();try(var paths=Files.walk(root)){for(var p:paths.toList())if(Files.isRegularFile(p,LinkOption.NOFOLLOW_LINKS))result.put(root.relativize(p).toString(),LocalView.digest(Files.readAllBytes(p)));}return result;
    }
    public void testRoundTripAndNoSourceOnRestart() throws Exception {
        Path root=root();var store=store(root);assertTrue(store.startupChoices().isEmpty());install(store,"A");assertEquals(A,store.pointer());assertEquals("invalid_or_absent",store.receipt());store.saveReady(A);
        install(store,"B");assertEquals(B,store.pointer());assertEquals(A,store.receipt());assertEquals(List.of(B,A),store.startupChoices().stream().map(FixturePublicationStore.Selection::id).toList());
        store.saveReady(B);Map<String,String> before=tree(root);var reboot=store(root);assertEquals(B,reboot.startupChoices().get(0).id());assertEquals(before,tree(root));assertTrue(reboot.privateReads.get()>0);event("round_trip_private_only",reboot);
    }
    public void testBadHashMissingAndCopyErrorKeepA() throws Exception {
        for(String fault:List.of("hash","missing","io")){
            Path root=root();readyA(root);var store=store(root);LocalView.Source normal=source("B",false);
            LocalView.Source bad=new LocalView.Source(){
                public Set<String> files() throws IOException {Set<String> files=new HashSet<>(normal.files());if(fault.equals("missing"))files.remove("data/events.json");return files;}
                public InputStream open(String name) throws IOException {
                    if(!name.equals("data/events.json"))return normal.open(name);
                    if(fault.equals("io"))return new InputStream(){int count;public int read() throws IOException {if(++count>4)throw new IOException("private/path secret");return 0;}};
                    byte[] bytes=LocalView.readBounded(normal.open(name),100000);bytes[0]^=1;return new ByteArrayInputStream(bytes);
                }
            };
            refused(()->store.install("B",bad,source("B",true),FixturePublicationStore.NONE));assertEquals(A,store.pointer());assertEquals(A,store.receipt());assertEquals(A,store.startupChoices().get(0).id());event(fault+"_keeps_A",store);
        }
    }
    public void testWrongViewIdentityAndExtraSourceRefused() throws Exception {
        Path root=root();readyA(root);var store=store(root);
        refused(()->store.install("B",source("B",false),source("A",true),FixturePublicationStore.NONE));
        assertEquals(A,store.pointer());assertEquals(A,store.receipt());assertEquals(A,store.startupChoices().get(0).id());
        LocalView.Source good=source("B",false),extra=new LocalView.Source(){
            public Set<String> files() throws IOException {var files=new HashSet<>(good.files());files.add("extra.txt");return files;}
            public InputStream open(String name) throws IOException {return good.open(name);}
        };
        refused(()->store.install("B",extra,source("B",true),FixturePublicationStore.NONE));assertEquals(A,store.pointer());event("wrong_view_identity_and_extra_source_keep_A",store);
    }
    public void testInterruptedStagingPreservedAndExplicitResume() throws Exception {
        Path root=root();readyA(root);var store=store(root);AtomicBoolean once=new AtomicBoolean();
        refused(()->store.install("B",source("B",false),source("B",true),point->{if(point.equals("copy_file")&&once.compareAndSet(false,true))throw new IOException("interrupted");}));
        Path incoming=root.resolve(".incoming");assertTrue(Files.exists(incoming));Map<String,String> staged=tree(incoming);
        var reboot=store(root);assertEquals(A,reboot.startupChoices().get(0).id());assertEquals(staged,tree(incoming));
        refused(()->install(reboot,"A"));assertEquals(staged,tree(incoming));install(reboot,"B");assertFalse(Files.exists(incoming));assertEquals(B,reboot.pointer());event("interrupted_preserved_then_explicit_resume",reboot);
    }
    public void testEveryPointerCommitBoundary() throws Exception {
        for(String point:List.of("journal.before_write","copy_chunk","stage_verified","revision_renamed","backup.before_rename","backup.after_rename","pointer.before_write","pointer.before_rename","pointer.after_rename")){
            Path root=root();readyA(root);var faulty=new FixturePublicationStore(root,p->{if(p.equals(point))throw new IOException("injected");});
            refused(()->install(faulty,"B"));var reboot=store(root);String expected=point.equals("pointer.after_rename")?B:A;
            assertEquals(expected,reboot.pointer());assertEquals(A,reboot.receipt());assertEquals(expected,reboot.startupChoices().get(0).id());event(point,reboot);
        }
    }
    public void testReceiptBoundariesNeverRollBackPointer() throws Exception {
        for(String point:List.of("receipt.before_write","receipt.before_rename","receipt.after_rename")){
            Path root=root();readyA(root);install(store(root),"B");var faulty=new FixturePublicationStore(root,p->{if(p.equals(point))throw new IOException("receipt_fault");});
            refused(()->faulty.saveReady(B));assertEquals(B,store(root).pointer());assertEquals(point.equals("receipt.after_rename")?B:A,store(root).receipt());event(point,store(root));
        }
    }
    public void testCorruptPointersReceiptAndNoDirectoryScan() throws Exception {
        Path root=root();readyA(root);var store=store(root);install(store,"B");store.saveReady(B);
        writeText(root.resolve("active.json"),"broken");assertEquals(A,store.startupChoices().get(0).id());
        writeText(root.resolve("active.backup.json"),"broken");assertEquals(List.of(B),store.startupChoices().stream().map(FixturePublicationStore.Selection::id).toList());
        writeText(root.resolve("last-ready-tv.json"),"broken");assertTrue(store.startupChoices().isEmpty());assertTrue(Files.exists(root.resolve("revisions").resolve(A)));assertTrue(Files.exists(root.resolve("revisions").resolve(B)));event("both_pointer_and_receipt_corrupt_safe_empty",store);
    }
    public void testCorruptPackagePreviousAndCorruptViewReceiptFallback() throws Exception {
        Path root=root();readyA(root);var store=store(root);install(store,"B");
        Path view=root.resolve("revisions").resolve(B).resolve("view/index.html");byte[] original=Files.readAllBytes(view);writeText(view,"damaged");
        assertEquals(List.of(A),store.startupChoices().stream().map(FixturePublicationStore.Selection::id).toList());event("bad_B_view_confirmed_A",store);
        Files.write(view,original);store.saveReady(B);writeText(root.resolve("revisions").resolve(B).resolve("package/data/events.json"),"bad");
        assertEquals(List.of(A),store.startupChoices().stream().map(FixturePublicationStore.Selection::id).toList());event("bad_B_package_previous_A",store);
    }
    public void testCorruptReceiptDoesNotInvalidateValidPointer() throws Exception {
        Path root=root();readyA(root);var store=store(root);install(store,"B");writeText(root.resolve("last-ready-tv.json"),"{\"schema\":true}");assertEquals(List.of(B),store.startupChoices().stream().map(FixturePublicationStore.Selection::id).toList());event("valid_pointer_bad_receipt",store);
    }
    public void testLeaseRejectsConcurrentPreparation() throws Exception {
        Path root=root();readyA(root);CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);AtomicReference<Throwable> error=new AtomicReference<>();
        Thread owner=new Thread(()->{try{store(root).install("B",source("B",false),source("B",true),point->{if(point.equals("stage_verified")){entered.countDown();try{if(!release.await(10,TimeUnit.SECONDS))throw new IOException("gate_timeout");}catch(InterruptedException e){throw new IOException("interrupted");}}});}catch(Throwable e){error.set(e);}});
        owner.start();try{assertTrue(entered.await(10,TimeUnit.SECONDS));refused(()->install(store(root),"A"));}finally{release.countDown();owner.join(15000);}assertFalse(owner.isAlive());assertNull(error.get());assertEquals(B,store(root).pointer());event("single_writer",store(root));
    }
    public void testSymlinkAndExtraPrivateFileRefused() throws Exception {
        Path root=root();readyA(root);var store=store(root);Path view=root.resolve("revisions").resolve(A).resolve("view");
        writeText(view.resolve("extra"),"x");assertTrue(store.startupChoices().isEmpty());Files.delete(view.resolve("extra"));
        Path file=view.resolve("index.html"),saved=view.resolve("original");Files.move(file,saved);Files.createSymbolicLink(file,saved);assertTrue(store.startupChoices().isEmpty());event("extra_or_link_refusal",store);
    }
    @Override protected void tearDown() throws Exception {
        // Disposable test roots only, never the real experiment or any unfinished production operation.
        for(Path root:roots){assertTrue(root.getFileName().toString().startsWith("store-test-"));try(var paths=Files.walk(root)){for(Path p:paths.sorted(Comparator.reverseOrder()).toList())Files.deleteIfExists(p);}}
        super.tearDown();
    }
}
