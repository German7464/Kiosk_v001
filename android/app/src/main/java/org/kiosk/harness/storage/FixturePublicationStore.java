package org.kiosk.harness.storage;

import java.io.*;
import java.nio.channels.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.kiosk.harness.FixtureCatalog;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.packagecore.EventsPackage;
import org.kiosk.harness.binding.*;

/** Shared development publication store; legacy A/B adapter and explicitly authorized captured candidates. */
public final class FixturePublicationStore {
    public interface Checkpoint {void hit(String point) throws IOException;}
    public static final Checkpoint NONE=point->{};
    public record Selection(String id,LocalView view) {}
    public record Startup(String mode,List<Selection> choices) {}
    public final Path root;
    public final AtomicInteger privateReads=new AtomicInteger();
    private final Checkpoint faults;
    private final PreparedAdmission.VerifierProvider admissionVerifiers;
    private String phase="lease";
    public FixturePublicationStore(Path root){this(root,NONE);}
    public FixturePublicationStore(Path root,Checkpoint faults){this(root,faults,PreparedAdmission.UNAVAILABLE);}
    public FixturePublicationStore(Path root,Checkpoint faults,PreparedAdmission.VerifierProvider verifiers){this.root=root;this.faults=faults;this.admissionVerifiers=verifiers;}
    private interface Work<T>{T run() throws Exception;}
    private <T>T leased(Work<T> work) throws IOException {
        try {
            PrivateFiles.directory(root);
            try(FileChannel channel=FileChannel.open(root.resolve("store.lock"),StandardOpenOption.CREATE,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS)){
                FileLock lock;
                try{lock=channel.tryLock();}catch(OverlappingFileLockException busy){throw PrivateFiles.refusal("store_busy");}
                if(lock==null)throw PrivateFiles.refusal("store_busy");
                try{return work.run();}finally{lock.release();}
            }
        }catch(Exception e){
            String message=e.getMessage()==null?"":e.getMessage();
            String safeDetail=Set.of("unsafe_private_tree","unsafe_private_file","private_read_failed","private_write_failed","private_inventory_mismatch","private_integrity_failure","directory_sync_failed","rename_failed","source_changed","source_inventory","store_busy","incomplete_operation","no_valid_publication","store_disk_full").contains(message)?message:"redacted";
            android.util.Log.w("StoredStore","phase="+phase+" type="+e.getClass().getSimpleName()+" code="+safeDetail);
            // Never expose a filesystem path, payload or provider exception/cause.
            String code=Set.of("store_busy","incomplete_operation","no_valid_publication","store_disk_full").contains(message)?message:"store_failed";
            throw PrivateFiles.refusal(code);
        }
    }
    private void checkpoint(Checkpoint operation,String point) throws IOException {
        phase=point;
        if(Thread.currentThread().isInterrupted())throw PrivateFiles.refusal("operation_cancelled");
        operation.hit(point);faults.hit(point);
        // Re-check cancellation after a test/provider checkpoint may have delayed the worker.
        if(Thread.currentThread().isInterrupted())throw PrivateFiles.refusal("operation_cancelled");
        operation.hit(point);
    }
    private void atomic(Path file,String text,Checkpoint operation,String label) throws IOException {
        byte[] bytes=text.getBytes(StandardCharsets.UTF_8);if(bytes.length>(label.equals("authority")||label.equals("admission")?DevelopmentGrant.LIMIT:4096))throw PrivateFiles.refusal("metadata_limit");
        Path temporary=file.resolveSibling("."+file.getFileName()+".tmp");
        checkpoint(operation,label+".before_write");
        try(FileOutputStream out=PrivateFiles.output(temporary)){out.write(bytes);out.flush();out.getFD().sync();}
        checkpoint(operation,label+".before_rename");
        PrivateFiles.rename(temporary,file);
        checkpoint(operation,label+".after_rename");
    }
    private Path revision(String id){DevelopmentGrant.identity(id);return root.resolve("revisions").resolve(id);}
    private PrivateFiles.Source source(Path revision,boolean view){
        try{
            var admitted=AdmissionRecord.load(root,revision.getFileName().toString());
            if(admitted!=null){var r=admitted.request;return new PrivateFiles.Source(revision.resolve(view?"view":"package"),DevelopmentGrant.copyPins(view?r.tv().files():r.pkg().files()),privateReads::incrementAndGet);}
            var grant=DevelopmentGrant.load(root,revision.getFileName().toString());
            if(grant!=null)return new PrivateFiles.Source(revision.resolve(view?"view":"package"),DevelopmentGrant.copyPins(view?grant.permit.tv.files():grant.permit.pkg.files()),privateReads::incrementAndGet);
            var f=PublicationFixtures.identity(revision.getFileName().toString());
            return new PrivateFiles.Source(revision.resolve(view?"view":"package"),view?f.viewFiles():f.packageFiles(),privateReads::incrementAndGet);
        }catch(Exception e){throw new IllegalArgumentException("invalid_development_authority");}
    }
    private void verifyPackage(String id) throws Exception {
        var admitted=AdmissionRecord.load(root,id);
        if(admitted!=null){
            var issuer=PreparedAdmission.require(admissionVerifiers);if(!issuer.issuerId().equals(admitted.issuer))throw PrivateFiles.refusal("admission_issuer_changed");
            var r=admitted.request;Path path=revision(id);
            PreparedAdmission.validate(source(path,false),new PrivateFiles.Source(path.resolve("view-kiosk"),DevelopmentGrant.copyPins(r.kiosk().files()),privateReads::incrementAndGet),
                source(path,true),r,issuer,PreparedAdmission.Phase.PRIVATE_REOPEN,NONE);return;
        }
        var grant=DevelopmentGrant.load(root,id);
        if(grant!=null){var s=source(revision(id),false);s.verifyPins();if(EventsPackage.inspect(s).unchecked.size()!=5)throw PrivateFiles.refusal("inspection_boundary_changed");return;}
        var fixture=PublicationFixtures.identity(id);var packageSource=source(revision(id),false);packageSource.verifyPins();
        var report=EventsPackage.inspect(packageSource);
        if(report.unchecked.size()!=5)throw PrivateFiles.refusal("inspection_boundary_changed");
        // Raw pinned manifest -> PC1 canonical package identity is compiled in the catalog.
        // No general cross-language canonical serializer or complete image verifier is implied.
        String expected=id.equals(PublicationFixtures.A.identity())?"1":"2";
        if(!expected.equals(report.revision))throw PrivateFiles.refusal("revision_mismatch");
    }
    private Selection verify(String id) throws Exception {
        return verify(id,"tv");
    }
    private Selection verify(String id,String mode) throws Exception {
        verifyPackage(id);return view(id,mode);
    }
    private Selection view(String id) throws Exception {
        return view(id,"tv");
    }
    private Selection view(String id,String mode) throws Exception {
        var admitted=AdmissionRecord.load(root,id);
        if(admitted!=null){PublicationFixtures.mode(mode);var r=admitted.request;
            var s=mode.equals("tv")?source(revision(id),true):new PrivateFiles.Source(revision(id).resolve("view-kiosk"),DevelopmentGrant.copyPins(r.kiosk().files()),privateReads::incrementAndGet);
            s.verifyPins();return new Selection(id,LocalView.verify(s,id,mode,r.renderer().trustedJsSha256(),r.renderer().trustedCssSha256()));
        }
        var grant=DevelopmentGrant.load(root,id);
        if(grant!=null){
            PublicationFixtures.mode(mode);var p=grant.permit;
            var s=mode.equals("tv")?source(revision(id),true):new PrivateFiles.Source(revision(id).resolve("view-kiosk"),DevelopmentGrant.copyPins(p.kiosk.files()),privateReads::incrementAndGet);
            s.verifyPins();return new Selection(id,LocalView.verify(s,id,mode,p.renderer.trustedJsSha256(),p.renderer.trustedCssSha256()));
        }
        PublicationFixtures.mode(mode);var fixture=PublicationFixtures.identity(id);
        var s=mode.equals("tv")?source(revision(id),true):new PrivateFiles.Source(root.resolve("kiosk-views").resolve(id).resolve("view"),PublicationFixtures.viewFiles(fixture,mode),privateReads::incrementAndGet);
        s.verifyPins();return new Selection(id,LocalView.verify(s,id,mode,FixtureCatalog.JS,FixtureCatalog.CSS));
    }
    private String resolvedPackage() throws Exception {
        boolean admittedOnly=admissionSelected();
        boolean found=false;
        for(String name:List.of("active.json","active.backup.json")){
            Path path=root.resolve(name);if(!Files.exists(path,LinkOption.NOFOLLOW_LINKS))continue;found=true;
            try {
                var pointer=StoreMetadata.pointer(path);
                for(String id:new String[]{pointer.current(),pointer.previous()}){
                    if(id==null)continue;
                    if(admittedOnly&&!AdmissionRecord.present(root,id))continue;
                    try{verifyPackage(id);return id;}catch(Exception invalid){/* bounded next pointer entry */}
                }
            }catch(Exception invalid){/* bounded backup pointer, never directory selection */}
        }
        if(found)throw PrivateFiles.refusal("no_valid_publication");return null;
    }
    /** At most authoritative resolved package/view and one distinct confirmed receipt. No asset access. */
    public List<Selection> startupChoices() throws IOException {
        return startupChoices("tv");
    }
    public List<Selection> startupChoices(String mode) throws IOException {
        PublicationFixtures.mode(mode);
        return leased(()->choices(mode));
    }
    /** Read mode and eligible records under one lease, including across Activity recreation. */
    public Startup startup() throws IOException {return leased(()->{String mode=selectedMode();return new Startup(mode,List.copyOf(choices(mode)));});}
    private List<Selection> choices(String mode) throws Exception {
            boolean admittedOnly=admissionSelected();
            List<Selection> choices=new ArrayList<>();
            try{String id=resolvedPackage();if(id!=null)choices.add(view(id,mode));}catch(Exception invalid){/* confirmed fallback only */}
            try {
                String id=StoreMetadata.receipt(root.resolve("last-ready-"+mode+".json"),mode);
                if(admittedOnly&&!AdmissionRecord.present(root,id))return choices;
                if(choices.isEmpty()||!choices.get(0).id().equals(id))choices.add(verify(id,mode));
            }catch(Exception invalid){/* safe empty, never scan revisions or incoming */}
            return choices;
    }
    public Selection install(String key,LocalView.Source packageSource,LocalView.Source viewSource,Checkpoint operation) throws IOException {
        return install(key,packageSource,viewSource,null,"tv",operation);
    }
    public Selection install(String key,LocalView.Source packageSource,LocalView.Source viewSource,LocalView.Source kioskSource,String mode,Checkpoint operation) throws IOException {
        PublicationFixtures.mode(mode);
        return leased(()->{
            if(admissionSelected())throw PrivateFiles.refusal("admission_mechanism_conflict");
            if(Files.exists(root.resolve(".development-incoming"),LinkOption.NOFOLLOW_LINKS))throw PrivateFiles.refusal("incomplete_operation");
            var fixture=PublicationFixtures.key(key);String previous=resolvedPackage();
            if(!packageSource.files().equals(fixture.packageFiles().keySet())||!viewSource.files().equals(fixture.viewFiles().keySet()))throw PrivateFiles.refusal("source_inventory");
            if(kioskSource!=null&&!kioskSource.files().equals(PublicationFixtures.viewFiles(fixture,"kiosk").keySet()))throw PrivateFiles.refusal("source_inventory");
            Path incoming=root.resolve(".incoming"),destination=revision(fixture.identity());
            PrivateFiles.directory(root.resolve("revisions"));
            for(Path staging:List.of(incoming,root.resolve(".kiosk-incoming")))if(Files.exists(staging,LinkOption.NOFOLLOW_LINKS)){
                String owner=new String(PrivateFiles.metadata(staging.resolve("operation")),StandardCharsets.UTF_8);
                if(!owner.equals(key))throw PrivateFiles.refusal("incomplete_operation");
            }
            if(!Files.exists(destination,LinkOption.NOFOLLOW_LINKS)){
                if(root.toFile().getUsableSpace()<fixture.bytes()+8192)throw PrivateFiles.refusal("store_disk_full");
                PrivateFiles.directory(incoming);
                atomic(incoming.resolve("operation"),key,operation,"journal");
                boundStaging(incoming,fixture);
                copy(packageSource,incoming.resolve("package"),fixture.packageFiles(),operation,"package");
                copy(viewSource,incoming.resolve("view"),fixture.viewFiles(),operation,"view");
                var p=new PrivateFiles.Source(incoming.resolve("package"),fixture.packageFiles(),privateReads::incrementAndGet);p.verifyPins();
                if(EventsPackage.inspect(p).unchecked.size()!=5)throw PrivateFiles.refusal("inspection_boundary_changed");
                var v=new PrivateFiles.Source(incoming.resolve("view"),fixture.viewFiles(),privateReads::incrementAndGet);v.verifyPins();
                LocalView.verify(v,fixture.identity(),"tv",FixtureCatalog.JS,FixtureCatalog.CSS);
                checkpoint(operation,"stage_verified");PrivateFiles.rename(incoming,destination);checkpoint(operation,"revision_renamed");
            }
            verify(fixture.identity());
            if(kioskSource!=null)prepareKiosk(fixture,kioskSource,operation);
            Selection result=verify(fixture.identity(),mode);
            checkpoint(operation,"preflight_complete");
            if(kioskSource!=null&&!Files.exists(root.resolve("selected-mode.json"),LinkOption.NOFOLLOW_LINKS))atomic(root.resolve("selected-mode.json"),StoreMetadata.mode(mode),operation,"mode");
            if(!fixture.identity().equals(previous)){
                if(previous!=null)atomic(root.resolve("active.backup.json"),new StoreMetadata.Pointer(previous,null).encode(),operation,"backup");
                atomic(root.resolve("active.json"),new StoreMetadata.Pointer(fixture.identity(),previous).encode(),operation,"pointer");
            }
            return result;
        });
    }
    /** Explicit fixed-fixture preparation only; never called from startup/mode switching. */
    private void prepareKiosk(PublicationFixtures.Fixture fixture,LocalView.Source input,Checkpoint operation) throws Exception {
        Path destination=root.resolve("kiosk-views").resolve(fixture.identity());
        if(Files.exists(destination,LinkOption.NOFOLLOW_LINKS)){view(fixture.identity(),"kiosk");return;}
        Path incoming=root.resolve(".kiosk-incoming");PrivateFiles.directory(root.resolve("kiosk-views"));PrivateFiles.directory(incoming);
        atomic(incoming.resolve("operation"),fixture.key(),operation,"kiosk_journal");
        var pins=PublicationFixtures.viewFiles(fixture,"kiosk");
        boundTree(incoming,pins.values(),pins.size());
        copy(input,incoming.resolve("view"),pins,operation,"kiosk");
        var source=new PrivateFiles.Source(incoming.resolve("view"),pins,privateReads::incrementAndGet);source.verifyPins();
        LocalView.verify(source,fixture.identity(),"kiosk",FixtureCatalog.JS,FixtureCatalog.CSS);
        checkpoint(operation,"kiosk_preflight_complete");PrivateFiles.rename(incoming,destination);checkpoint(operation,"kiosk_renamed");
    }
    private void copy(LocalView.Source source,Path target,Map<String,PublicationFixtures.Pin> pins,Checkpoint operation,String kind) throws Exception {
        PrivateFiles.directory(target);
        for(var entry:new TreeMap<>(pins).entrySet()){
            String name=entry.getKey();var pin=entry.getValue();Path file=target.resolve(name);PrivateFiles.directory(file.getParent());
            if(Files.exists(file,LinkOption.NOFOLLOW_LINKS)){
                byte[] existing=LocalView.readBounded(PrivateFiles.open(file),pin.size());
                if(existing.length==pin.size()&&LocalView.digest(existing).equals(pin.sha256()))continue;
            }
            Path part=file.resolveSibling(file.getFileName()+".part");long total=0;MessageDigest hash=MessageDigest.getInstance("SHA-256");
            checkpoint(operation,"copy_open:"+kind+"/"+name);
            try(InputStream input=source.open(name);FileOutputStream output=PrivateFiles.output(part)){
                byte[] block=new byte[256*1024];int count;
                while((count=input.read(block,0,(int)Math.min(block.length,pin.size()-total+1)))!=-1){
                    if(count<=0||count>pin.size()-total)throw PrivateFiles.refusal("source_changed");
                    output.write(block,0,count);hash.update(block,0,count);total+=count;checkpoint(operation,"copy_chunk");
                }
                if(total!=pin.size()||!hex(hash.digest()).equals(pin.sha256()))throw PrivateFiles.refusal("source_changed");
                output.flush();output.getFD().sync();
            }
            PrivateFiles.rename(part,file);checkpoint(operation,"copy_file");
        }
    }
    private static String hex(byte[] bytes){StringBuilder out=new StringBuilder();for(byte b:bytes)out.append(String.format(Locale.ROOT,"%02x",b&255));return out.toString();}
    private void boundStaging(Path incoming,PublicationFixtures.Fixture fixture) throws Exception {
        List<PublicationFixtures.Pin> pins=new ArrayList<>(fixture.packageFiles().values());pins.addAll(fixture.viewFiles().values());boundTree(incoming,pins,pins.size());
    }
    private void boundTree(Path incoming,Collection<PublicationFixtures.Pin> pins,int entries) throws Exception {
        long largest=pins.stream().mapToLong(PublicationFixtures.Pin::size).max().orElse(0);
        long remaining=pins.stream().mapToLong(PublicationFixtures.Pin::size).sum()+largest+8192;int count=0;
        try(var paths=Files.walk(incoming)){
            var iterator=paths.iterator();
            while(iterator.hasNext()){
                Path p=iterator.next();if(++count>16+4*entries||Files.isSymbolicLink(p))throw PrivateFiles.refusal("incomplete_operation");
                if(Files.isRegularFile(p,LinkOption.NOFOLLOW_LINKS)){
                    long size=Files.size(p);if(size>remaining)throw PrivateFiles.refusal("incomplete_operation");remaining-=size;
                }else if(!Files.isDirectory(p,LinkOption.NOFOLLOW_LINKS))throw PrivateFiles.refusal("incomplete_operation");
            }
        }
    }
    /** Caller retains capture ownership; the coordinator transfers/closes it explicitly after this call. */
    public Selection installDevelopment(CapturedCandidate capture,DevelopmentPlaybackAuthority.Permit permit,
                                        CapturedCandidate.Budget budget,Checkpoint operation)throws IOException{
        return leased(()->{
            if(admissionSelected()||AdmissionRecord.present(root,permit.pkg.canonicalIdentity()))throw PrivateFiles.refusal("admission_mechanism_conflict");
            var grant=new DevelopmentGrant(Objects.requireNonNull(permit));String id=permit.pkg.canonicalIdentity();
            if(budget==null||budget.maxBytes()<0||budget.maxFiles()<0||budget.minFreeBytes()<0)throw PrivateFiles.refusal("development_budget");
            var nativeGrant=grant.encode();if(nativeGrant.getBytes(StandardCharsets.UTF_8).length>DevelopmentGrant.LIMIT)throw PrivateFiles.refusal("development_budget");
            long bytes=nativeGrant.getBytes(StandardCharsets.UTF_8).length+8192;int count=2;
            List<PublicationFixtures.Pin> all=new ArrayList<>();
            for(var group:List.of(permit.pkg.files(),permit.kiosk.files(),permit.tv.files()))for(var pin:group.values()){
                if(pin.size()<0||pin.size()>budget.maxBytes()-bytes||++count>budget.maxFiles())throw PrivateFiles.refusal("development_budget");bytes+=pin.size();all.add(new PublicationFixtures.Pin(pin.size(),pin.sha256()));
            }
            if(bytes>budget.maxBytes()||count>budget.maxFiles())throw PrivateFiles.refusal("development_budget");
            String mode=selectedMode();String previous=resolvedPackage();
            if(!capture.report().callerAttestedCanonicalPackageIdentity().equals(id))throw PrivateFiles.refusal("development_witness");
            PublicationBinding.inspect(capture.source(CapturedCandidate.Part.PACKAGE),capture.source(CapturedCandidate.Part.KIOSK),capture.source(CapturedCandidate.Part.TV),permit.pkg,permit.renderer,permit.kiosk,permit.tv);
            Path incoming=root.resolve(".development-incoming"),destination=revision(id);
            for(String old:List.of(".incoming",".kiosk-incoming"))if(Files.exists(root.resolve(old),LinkOption.NOFOLLOW_LINKS))throw PrivateFiles.refusal("incomplete_operation");
            var existing=DevelopmentGrant.load(root,id);
            if(existing!=null&&!existing.fingerprint().equals(grant.fingerprint()))throw PrivateFiles.refusal("development_authority_conflict");
            if(Files.exists(incoming,LinkOption.NOFOLLOW_LINKS)){
                String owner=new String(PrivateFiles.metadata(incoming.resolve("operation")),StandardCharsets.UTF_8);
                if(!owner.equals(grant.fingerprint()))throw PrivateFiles.refusal("incomplete_operation");
            }
            if(!Files.exists(destination,LinkOption.NOFOLLOW_LINKS)){
                long space=root.toFile().getUsableSpace();if(space<budget.minFreeBytes()||bytes>space-budget.minFreeBytes())throw PrivateFiles.refusal("store_disk_full");
                checkpoint(operation,"development.space_checked");PrivateFiles.directory(incoming);
                if(!Files.exists(incoming.resolve("operation")))atomic(incoming.resolve("operation"),grant.fingerprint(),operation,"development_journal");
                boundTree(incoming,all,all.size());
                copy(capture.source(CapturedCandidate.Part.PACKAGE),incoming.resolve("package"),DevelopmentGrant.copyPins(permit.pkg.files()),operation,"development_package");
                copy(capture.source(CapturedCandidate.Part.TV),incoming.resolve("view"),DevelopmentGrant.copyPins(permit.tv.files()),operation,"development_tv");
                copy(capture.source(CapturedCandidate.Part.KIOSK),incoming.resolve("view-kiosk"),DevelopmentGrant.copyPins(permit.kiosk.files()),operation,"development_kiosk");
                bindDevelopment(incoming,permit);checkpoint(operation,"development.stage_verified");
                PrivateFiles.directory(root.resolve("revisions"));PrivateFiles.rename(incoming,destination);checkpoint(operation,"development.revision_renamed");
            }else if(existing==null&&!Files.exists(destination.resolve("operation")))throw PrivateFiles.refusal("development_layout_conflict");
            // Explicit same-witness resume can adopt its complete unreferenced revision; startup never scans it.
            bindDevelopment(destination,permit);
            PrivateFiles.directory(root.resolve("development-authority"));
            if(existing==null)atomic(DevelopmentGrant.path(root,id),nativeGrant,operation,"authority");
            Selection result=verify(id,mode);checkpoint(operation,"preflight_complete");
            if(!id.equals(previous)){
                if(previous!=null)atomic(root.resolve("active.backup.json"),new StoreMetadata.Pointer(previous,null).encode(),operation,"backup");
                atomic(root.resolve("active.json"),new StoreMetadata.Pointer(id,previous).encode(),operation,"pointer");
            }
            return result;
        });
    }
    private void bindDevelopment(Path revision,DevelopmentPlaybackAuthority.Permit p)throws Exception{
        bindWitness(revision,p.pkg,p.renderer,p.kiosk,p.tv);
    }
    private void bindWitness(Path path,DevelopmentWitness.Package pkg,DevelopmentWitness.Renderer renderer,DevelopmentWitness.Artifact kiosk,DevelopmentWitness.Artifact tv)throws Exception{
        PublicationBinding.inspect(new PrivateFiles.Source(path.resolve("package"),DevelopmentGrant.copyPins(pkg.files()),privateReads::incrementAndGet),
            new PrivateFiles.Source(path.resolve("view-kiosk"),DevelopmentGrant.copyPins(kiosk.files()),privateReads::incrementAndGet),
            new PrivateFiles.Source(path.resolve("view"),DevelopmentGrant.copyPins(tv.files()),privateReads::incrementAndGet),pkg,renderer,kiosk,tv);
    }
    private boolean admissionSelected(){try{return AdmissionRecord.present(root,StoreMetadata.pointer(root.resolve("active.json")).current());}catch(Exception e){return false;}}
    /** No permit parameter: the configured native verifier and full local checks always execute here. */
    public Selection installPrepared(CapturedCandidate capture,PreparedAdmission.Request r,Checkpoint operation)throws IOException{
        return leased(()->{
            var issuer=PreparedAdmission.require(admissionVerifiers);r.checkBudgets();
            PreparedAdmission.validate(capture.source(CapturedCandidate.Part.PACKAGE),capture.source(CapturedCandidate.Part.KIOSK),capture.source(CapturedCandidate.Part.TV),r,issuer,PreparedAdmission.Phase.NEW_ACTIVATION,operation);
            String id=r.pkg().canonicalIdentity(),mode=selectedMode();
            if(Files.exists(DevelopmentGrant.path(root,id),LinkOption.NOFOLLOW_LINKS))throw PrivateFiles.refusal("development_conversion_refused");
            String previous;
            try{previous=resolvedPackage();}
            catch(IOException unavailable){
                if(!"no_valid_publication".equals(unavailable.getMessage()))throw unavailable;
                // A newly verified real source can replace an unplayable old test grant without deleting it.
                // Retain its pointer for provenance; every future reopen still independently verifies authority.
                previous=StoreMetadata.pointer(root.resolve("active.json")).current();
            }
            var record=new AdmissionRecord(r,issuer.issuerId());String encoded=record.encode();
            long bytes=encoded.getBytes(StandardCharsets.UTF_8).length+8192;int count=3;List<PublicationFixtures.Pin> all=new ArrayList<>();
            for(var group:List.of(r.pkg().files(),r.kiosk().files(),r.tv().files()))for(var pin:group.values()){
                if(pin.size()<0||pin.size()>r.storage().maxBytes()-bytes||++count>r.storage().maxFiles())throw PrivateFiles.refusal("admission_budget");
                bytes+=pin.size();all.add(new PublicationFixtures.Pin(pin.size(),pin.sha256()));
            }
            if(bytes>r.storage().maxBytes()||count>r.storage().maxFiles())throw PrivateFiles.refusal("admission_budget");
            Path incoming=root.resolve(".admission-incoming"),destination=revision(id);
            for(String old:List.of(".incoming",".kiosk-incoming",".development-incoming"))if(Files.exists(root.resolve(old),LinkOption.NOFOLLOW_LINKS))throw PrivateFiles.refusal("incomplete_operation");
            String fingerprint=r.factsFingerprint()+"\n"+issuer.issuerId();
            if(Files.exists(incoming,LinkOption.NOFOLLOW_LINKS)&&!new String(PrivateFiles.metadata(incoming.resolve("operation")),StandardCharsets.UTF_8).equals(fingerprint))throw PrivateFiles.refusal("incomplete_operation");
            if(!Files.exists(destination,LinkOption.NOFOLLOW_LINKS)){
                long space=root.toFile().getUsableSpace();if(space<r.storage().minFreeBytes()||bytes>space-r.storage().minFreeBytes())throw PrivateFiles.refusal("store_disk_full");
                checkpoint(operation,"admission.space_checked");PrivateFiles.directory(incoming);
                if(!Files.exists(incoming.resolve("operation")))atomic(incoming.resolve("operation"),fingerprint,operation,"admission_journal");
                // Reuse the existing bounded copy and private-file primitives, in the same revision tree.
                boundTree(incoming,all,all.size());
                copy(capture.source(CapturedCandidate.Part.PACKAGE),incoming.resolve("package"),DevelopmentGrant.copyPins(r.pkg().files()),operation,"admission_package");
                copy(capture.source(CapturedCandidate.Part.TV),incoming.resolve("view"),DevelopmentGrant.copyPins(r.tv().files()),operation,"admission_tv");
                copy(capture.source(CapturedCandidate.Part.KIOSK),incoming.resolve("view-kiosk"),DevelopmentGrant.copyPins(r.kiosk().files()),operation,"admission_kiosk");
                bindWitness(incoming,r.pkg(),r.renderer(),r.kiosk(),r.tv());
                atomic(incoming.resolve("admission-required"),"native-local-admission-v1",operation,"admission_marker");
                atomic(incoming.resolve("admission.json"),encoded,operation,"admission");
                checkpoint(operation,"admission.stage_verified");PrivateFiles.directory(root.resolve("revisions"));PrivateFiles.rename(incoming,destination);
            }else{
                var saved=AdmissionRecord.load(root,id);if(saved==null||!saved.request.factsFingerprint().equals(r.factsFingerprint())||!saved.issuer.equals(issuer.issuerId()))throw PrivateFiles.refusal("admission_layout_conflict");
            }
            // Reopen persisted bytes/evidence and consult the issuer again before publishing a pointer.
            Selection result=verify(id,mode);checkpoint(operation,"admission.preflight_complete");
            if(!id.equals(previous)){
                if(previous!=null)atomic(root.resolve("active.backup.json"),new StoreMetadata.Pointer(previous,null).encode(),operation,"backup");
                atomic(root.resolve("active.json"),new StoreMetadata.Pointer(id,previous).encode(),operation,"pointer");
            }return result;
        });
    }
    public String admissionIssuer(String id){try{var record=AdmissionRecord.load(root,id);return record==null?"none":record.issuer;}catch(Exception e){return "unverified";}}
    public boolean developmentAuthorized(String id){try{return DevelopmentGrant.load(root,id)!=null;}catch(Exception e){return false;}}
    public void saveReady(String id) throws IOException {saveReady(id,NONE);}
    public void saveReady(String id,Checkpoint operation) throws IOException {leased(()->{verify(id);atomic(root.resolve("last-ready-tv.json"),StoreMetadata.receipt(id,"tv",root),operation,"receipt");return null;});}
    public void saveReady(String id,String mode,Checkpoint operation) throws IOException {PublicationFixtures.mode(mode);leased(()->{verify(id,mode);atomic(root.resolve("last-ready-"+mode+".json"),StoreMetadata.receipt(id,mode,root),operation,"receipt");return null;});}
    public String selectedMode() throws IOException {
        Path path=root.resolve("selected-mode.json");if(!Files.exists(path,LinkOption.NOFOLLOW_LINKS))return "tv";
        try{return StoreMetadata.mode(path);}catch(Exception e){throw PrivateFiles.refusal("invalid_mode");}
    }
    public String modeOrInvalid(){try{return selectedMode();}catch(IOException e){return "invalid";}}
    public Selection selectMode(String mode,Checkpoint operation) throws IOException {
        PublicationFixtures.mode(mode);return leased(()->{
            String id=resolvedPackage();Selection result=id==null?null:verify(id,mode);
            checkpoint(operation,"mode_preflight_complete");atomic(root.resolve("selected-mode.json"),StoreMetadata.mode(mode),operation,"mode");return result;
        });
    }
    public String pointer(){try{return StoreMetadata.pointer(root.resolve("active.json")).current();}catch(Exception e){return "invalid_or_absent";}}
    public String receipt(){try{return StoreMetadata.receipt(root.resolve("last-ready-tv.json"));}catch(Exception e){return "invalid_or_absent";}}
    public String receipt(String mode){try{return StoreMetadata.receipt(root.resolve("last-ready-"+PublicationFixtures.mode(mode)+".json"),mode);}catch(Exception e){return "invalid_or_absent";}}
    public void diagnostic(String text) throws IOException {leased(()->{atomic(root.resolve("display-state.json"),text,NONE,"diagnostic");return null;});}
}
