package org.kiosk.harness.delivery;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.*;
import org.junit.*;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.publishing.*;
import static org.junit.Assert.*;
import static org.kiosk.harness.delivery.DeliveryJson.*;
import static org.kiosk.harness.delivery.DeliveryProtocol.*;

public class PageReleaseProtocolTest {
    private static final long NOW=2_000_000_100L;
    private static final String GROUP="group-stage6",ORIGIN="https://kiosk.example:20443",USER="user1";
    private static final String ENTRY=PageReleaseProtocol.ENTRYPOINT,IMAGE="static/uploads/card.png";
    private static final String KIOSK_DEVICE="screen-android",TV_DEVICE="screen-tv";
    private static Fixture fixture;

    @BeforeClass public static void prepare()throws Exception{fixture=build();}

    private static NumberToken n(long value){return new NumberToken(Long.toString(value));}
    private static Map<String,Object> m(Object... values){
        if(values.length%2!=0)throw new IllegalArgumentException("pairs");
        Map<String,Object> result=new LinkedHashMap<>();
        for(int i=0;i<values.length;i+=2)result.put((String)values[i],values[i+1]);
        return result;
    }
    private static List<Object> a(Object... values){return new ArrayList<>(Arrays.asList(values));}
    private static byte[] bytes(String value){return value.getBytes(StandardCharsets.UTF_8);}
    private static String sha(Object value)throws Exception{return LocalView.digest(PublisherAuthority.canonical(value));}
    private static Map<String,Object> copy(Map<String,Object> value)throws Exception{
        return object(parse(PublisherAuthority.canonical(value),PageReleaseProtocol.MAX_DOCUMENT));
    }
    private static Map<String,Object> row(String path,byte[] payload)throws Exception{
        return m("path",path,"size",n(payload.length),"sha256",LocalView.digest(payload));
    }
    private static Map<String,Object> limits(){
        return m("capture_bytes",n(201326592),"capture_files",n(30003),"max_live_bytes",n(33554432),
            "max_pixels",n(2000000),"min_free_bytes",n(16777216),"per_image_ms",n(5000),"total_image_ms",n(15000));
    }
    private static String planId(Map<String,Object> plan)throws Exception{
        Map<String,Object> body=new TreeMap<>(plan);body.remove("id");
        byte[] canonical=PublisherAuthority.canonical(body),domain=PageReleaseProtocol.PLAN_DOMAIN;
        byte[] input=new byte[domain.length+canonical.length];
        System.arraycopy(domain,0,input,0,domain.length);System.arraycopy(canonical,0,input,domain.length,canonical.length);
        return LocalView.digest(input);
    }
    private static Map<String,Object> v1Envelope(PrivateKey key,String kind,Map<String,Object> value)throws Exception{
        byte[] payload=PublisherAuthority.canonical(m("kind",kind,"value",value,"version",n(1)));
        Signature signer=Signature.getInstance("SHA256withRSA");signer.initSign(key);
        signer.update(PublisherAuthority.DOMAIN);signer.update(payload);
        return m("payload",Base64.getEncoder().encodeToString(payload),
            "signature",Base64.getEncoder().encodeToString(signer.sign()));
    }

    private static final class SoftwareKey implements PublisherKey{
        private final KeyPair pair;
        SoftwareKey(KeyPair pair){this.pair=pair;}
        public PublicKey publicKey(){return pair.getPublic();}
        public byte[] sign(byte[] domain,byte[] payload)throws Exception{
            Signature signer=Signature.getInstance("SHA256withRSA");signer.initSign(pair.getPrivate());
            signer.update(domain);signer.update(payload);return signer.sign();
        }
        public String label(){return "stage6-test";}
    }

    private record TargetData(String device,String projection,String destination,Map<String,Object> configuration,
                              Map<String,Object> metadata,String metadataSha,byte[] content,Map<String,byte[]> packageFiles,
                              List<Object> innerRows,String packageId,String rawManifestSha,String renderer){}
    private record Fixture(KeyPair root,KeyPair device,Map<String,Object> policy,List<Object> chain,
                           Map<String,Object> revision,String revisionHash,Map<String,TargetData> targets,
                           Map<String,Object> document,Map<String,PageReleaseProtocol.Files> files){}
    private record PackageCase(Map<String,Object> document,Map<String,PageReleaseProtocol.Files> files){}

    private static Fixture build()throws Exception{
        KeyPairGenerator generator=KeyPairGenerator.getInstance("RSA");generator.initialize(3072);
        KeyPair root=generator.generateKeyPair(),device=generator.generateKeyPair();
        long policyExpiry=NOW+5000;
        Map<String,Object> policy=m("group_id",GROUP,"origin",ORIGIN,"version",n(1),"issued",n(NOW-10),
            "expires",n(policyExpiry),"revoked_devices",a(),"revoked_users",a());
        Map<String,Object> grant=m("group_id",GROUP,"origin",ORIGIN,"user_id",USER,"role","administrator",
            "device_key",Base64.getEncoder().encodeToString(device.getPublic().getEncoded()),
            "issued",n(NOW-10),"expires",n(policyExpiry),"can_delegate",false);
        List<Object> chain=a(v1Envelope(root.getPrivate(),"device",grant));

        String dataset="dataset-"+"1".repeat(32),block="block-"+"2".repeat(32);
        String kioskLayout="layout-"+"3".repeat(32),tvLayout="layout-"+"4".repeat(32);
        String page="page-"+"5".repeat(32),kioskAssignment="assignment-"+"6".repeat(32),tvAssignment="assignment-"+"7".repeat(32);
        Map<String,Object> eventPayload=m("title","Opening night","short_description","Doors open",
            "full_description","Full event description","event_date","2026-11-25","place","Main hall",
            "sort_order",n(1),"status","active","images",a("/static/uploads/card.png"),"tags",a("News"));
        Map<String,Object> datasetPayload=m("schema",n(1),"name","Events","module","events","events",a("1001"));
        Map<String,Object> blockPayload=m("schema",n(1),"name","Featured","dataset",dataset,"tags",a(),
            "limit",n(5),"appearance","cards");
        Map<String,Object> kioskLayoutPayload=m("schema",n(1),"target","kiosk-landscape","columns",n(2),"rows",n(1),
            "placements",a(m("block",block,"x",n(0),"y",n(0),"w",n(1),"h",n(1))));
        Map<String,Object> tvLayoutPayload=m("schema",n(1),"target","tv-landscape","columns",n(3),"rows",n(1),
            "placements",a(m("block",block,"x",n(0),"y",n(0),"w",n(1),"h",n(1))));
        Map<String,Object> pagePayload=m("schema",n(1),"name","Home","order",n(0),
            "layouts",m("kiosk-landscape",kioskLayout,"tv-landscape",tvLayout),"fallback","kiosk-landscape");
        Map<String,Object> selection=m("pages",a(page),"start_page",page,"transition_seconds",n(15));
        Map<String,Object> kioskAssignmentPayload=m("schema",n(1),"device",KIOSK_DEVICE,"profile",null,"selection",selection);
        Map<String,Object> tvAssignmentPayload=m("schema",n(1),"device",TV_DEVICE,"profile",null,"selection",selection);
        Map<String,Object> objects=m(
            "1001",m("version",n(1),"payload",eventPayload,"dependencies",m(),"author","alice"),
            dataset,m("version",n(1),"payload",datasetPayload,"dependencies",m("1001",n(1)),"author","alice"),
            block,m("version",n(1),"payload",blockPayload,"dependencies",m(dataset,n(1)),"author","alice"),
            kioskLayout,m("version",n(1),"payload",kioskLayoutPayload,"dependencies",m(block,n(1)),"author","alice"),
            tvLayout,m("version",n(1),"payload",tvLayoutPayload,"dependencies",m(block,n(1)),"author","alice"),
            page,m("version",n(1),"payload",pagePayload,"dependencies",m(kioskLayout,n(1),tvLayout,n(1)),"author","alice"),
            kioskAssignment,m("version",n(1),"payload",kioskAssignmentPayload,"dependencies",m(page,n(1)),"author","alice"),
            tvAssignment,m("version",n(1),"payload",tvAssignmentPayload,"dependencies",m(page,n(1)),"author","alice"));
        List<Object> included=a();
        for(String id:List.of("1001",dataset,block,kioskLayout,tvLayout,page,kioskAssignment,tvAssignment))
            included.add(m("id",id,"version",n(1),"author","alice"));
        List<Object> excluded=a(m("id","1002","version",n(2),"author","alice","reason","working"));
        Map<String,Object> revision=m("plan",m("included",included,"excluded",excluded),"objects",objects);
        String revisionHash=PageReleaseProtocol.revisionSha256(revision);
        TargetData kiosk=buildTarget(revision,revisionHash,KIOSK_DEVICE,"kiosk-landscape","kiosk","kiosk-profile","android-pages-v1");
        TargetData tv=buildTarget(revision,revisionHash,TV_DEVICE,"tv-landscape","tv","tv-profile","android-pages-v1");
        List<Object> planTargets=a(kioskPlanTarget(kiosk),kioskPlanTarget(tv));
        Map<String,Object> plan=m("version",n(2),"group_id",GROUP,"origin",ORIGIN,"user_id",USER,
            "device_id",PublisherAuthority.keyId(device.getPublic()),"policy_version",n(1),"issued",n(NOW),
            "expires",n(NOW+600),"revision_sha256",revisionHash,"dependencies_sha256",sha(objects),
            "targets",planTargets,"parents",a());
        plan.put("id",planId(plan));
        Map<String,Object> document=m("version",n(2),"plan",plan,"revision",revision,
            "targets",a(documentTarget(kiosk),documentTarget(tv)),"ancestry",a());
        Map<String,PageReleaseProtocol.Files> files=new TreeMap<>();
        files.put(KIOSK_DEVICE,new PageReleaseProtocol.Files(kiosk.packageFiles(),Map.of(),Map.of()));
        files.put(TV_DEVICE,new PageReleaseProtocol.Files(tv.packageFiles(),Map.of(),Map.of()));
        return new Fixture(root,device,policy,chain,revision,revisionHash,Map.of(KIOSK_DEVICE,kiosk,TV_DEVICE,tv),document,files);
    }

    private static TargetData buildTarget(Map<String,Object> revision,String revisionHash,String device,
            String projection,String mode,String profile,String destination)throws Exception{
        Map<String,Object> content=PageReleaseProtocol.projectTarget(revision,device,projection);
        byte[] contentBytes=PublisherAuthority.canonical(content),entry=contentBytes,image=bytes("synthetic-png");
        List<Object> innerRows=a(row(ENTRY,entry),row(IMAGE,image));
        Map<String,Object> manifest=m("schema_version",n(2),"kind","pages","revision",revisionHash,
            "renderer","pages-v1","resource_contract",n(1),"files",innerRows,"entrypoints",a(ENTRY));
        byte[] raw=PublisherAuthority.canonical(manifest);
        Map<String,byte[]> packageFiles=new TreeMap<>();
        packageFiles.put("manifest.json",raw);packageFiles.put(ENTRY,entry);packageFiles.put(IMAGE,image);
        List<Object> packageRows=a(row("manifest.json",raw),row(ENTRY,entry),row(IMAGE,image));
        String renderer=PageReleaseProtocol.rendererBuildId(PageReleaseProtocol.SHIPPED_JS_SHA256,
            PageReleaseProtocol.SHIPPED_CSS_SHA256);
        Map<String,Object> publication=m("version",n(2),"package_id",sha(manifest),"revision",revisionHash,
            "raw_manifest_sha256",LocalView.digest(raw),
            "renderer",m("build_id",renderer,"js_sha256",PageReleaseProtocol.SHIPPED_JS_SHA256,
                "css_sha256",PageReleaseProtocol.SHIPPED_CSS_SHA256),
            "resource_profile",PageReleaseProtocol.PROFILE,"limits",limits(),"windows_images",m(),
            "package",m("files",packageRows),"kiosk",m("files",a()),"tv",m("files",a()));
        Map<String,Object> metadata=m("version",n(2),"destination",destination,"revision_sha256",revisionHash,
            "content_sha256",LocalView.digest(contentBytes),"publication",publication);
        Map<String,Object> configuration=m("version",n(1),"profile_id",profile,"revision",n(1),"mode",mode);
        return new TargetData(device,projection,destination,configuration,metadata,sha(metadata),contentBytes,
            packageFiles,innerRows,str(publication,"package_id"),str(publication,"raw_manifest_sha256"),renderer);
    }
    private static Map<String,Object> kioskPlanTarget(TargetData value)throws Exception{
        return m("device_id",value.device(),"profile_id",str(value.configuration(),"profile_id"),
            "profile_version",n(1),"mode",str(value.configuration(),"mode"),
            "configuration_sha256",sha(value.configuration()),"projection",value.projection(),
            "destination",value.destination(),"renderer",value.renderer(),"metadata_sha256",value.metadataSha());
    }
    private static Map<String,Object> documentTarget(TargetData value){
        return m("device_id",value.device(),"projection",value.projection(),"destination",value.destination(),
            "configuration",value.configuration(),"metadata",value.metadata());
    }
    private static Map<String,Object> proof(Fixture value,Map<String,Object> approval,List<Object> ancestry)throws Exception{
        return m("approval",approval,"chain",value.chain(),
            "policy",v1Envelope(value.root().getPrivate(),"policy",value.policy()),"ancestry",ancestry);
    }
    private static Map<String,Object> assignment(Fixture value,String device,Map<String,Object> proof){
        TargetData target=value.targets().get(device);
        return m("version",n(4),"group_id",GROUP,"device_id",device,"profile",PageReleaseProtocol.PROFILE,
            "generation",n(1),"revision_sha256",value.revisionHash(),"destination",target.destination(),
            "projection",target.projection(),"metadata_sha256",target.metadataSha(),"metadata",target.metadata(),
            "display",target.configuration(),"publisher",proof);
    }
    private static PageReleaseProtocol.PageAdmission admit(Fixture value,String device,Map<String,Object> proof,
            PageReleaseProtocol.Files files,Set<String> heads)throws Exception{
        TargetData target=value.targets().get(device);
        return PageReleaseProtocol.admit(proof,assignment(value,device,proof),value.root().getPublic(),ORIGIN,NOW,
            files,GROUP,device,PageReleaseProtocol.PROFILE,target.destination(),PageReleaseProtocol.SHIPPED_JS_SHA256,
            PageReleaseProtocol.SHIPPED_CSS_SHA256,0,heads);
    }
    private static PageReleaseProtocol.Refused refused(Attempt attempt)throws Exception{
        try{attempt.run();}
        catch(PageReleaseProtocol.Refused refusal){return refusal;}
        throw new AssertionError("invalid page release was accepted");
    }
    private interface Attempt{void run()throws Exception;}

    @Test public void documentedLiteralVectorsMatchCanonicalDomains()throws Exception{
        Map<String,Object> vectors;
        try(InputStream stream=PageReleaseProtocolTest.class.getResourceAsStream("/stage6/page-release-vectors.json")){
            assertNotNull(stream);vectors=object(parse(stream.readAllBytes(),65536));
        }
        assertEquals(str(vectors,"renderer_build_id"),PageReleaseProtocol.rendererBuildId(
            str(vectors,"renderer_js_sha256"),str(vectors,"renderer_css_sha256")));
        Map<String,Object> metadata=object(parse(bytes(str(vectors,"metadata_canonical")),65536));
        assertArrayEquals(bytes(str(vectors,"metadata_canonical")),PublisherAuthority.canonical(metadata));
        assertEquals(str(vectors,"metadata_sha256"),sha(metadata));
        assertSame(metadata.get("publication"),PageReleaseProtocol.validateMetadata(metadata));
        Map<String,Object> plan=object(parse(bytes(str(vectors,"plan_canonical")),65536));
        assertArrayEquals(bytes(str(vectors,"plan_canonical")),PublisherAuthority.canonical(plan));
        assertEquals(planId(plan),str(plan,"id"));
        PageReleaseProtocol.validatePlan(plan,2_000_000_100L);
    }

    @Test public void excludedRowsCannotReuseOldObjectsUnderAnotherAuthorOrInjectReviewText()throws Exception{
        Map<String,Object> revision=copy(fixture.revision());
        Map<String,Object> objects=obj(revision,"objects");
        Map<String,Object> old=copy(object(objects.get("1001")));
        objects.put("1002",old);
        PageReleaseProtocol.revisionSha256(revision);

        Map<String,Object> changedAuthor=copy(revision);
        Map<String,Object> excluded=object(array(obj(changedAuthor,"plan").get("excluded")).get(0));
        excluded.put("author","mallory");
        assertEquals("page_release_plan_entry",refused(()->PageReleaseProtocol.revisionSha256(changedAuthor)).code);

        Map<String,Object> injected=copy(revision);
        Map<String,Object> injectedRow=object(array(obj(injected,"plan").get("excluded")).get(0));
        injectedRow.put("reason","draft reason with spaces");
        assertEquals("page_release_object_payload",refused(()->PageReleaseProtocol.revisionSha256(injected)).code);

        Map<String,Object> closure=copy(revision);
        Map<String,Object> closureObjects=obj(closure,"objects");
        String datasetId=closureObjects.keySet().stream().filter(id->id.startsWith("dataset-")).findFirst().orElseThrow();
        Map<String,Object> datasetEntry=object(closureObjects.get(datasetId));
        Map<String,Object> datasetPayload=obj(datasetEntry,"payload");
        List<Object> events=new ArrayList<>(array(datasetPayload.get("events")));events.add("1002");
        datasetPayload.put("events",events);
        Map<String,Object> dependencies=new LinkedHashMap<>(obj(datasetEntry,"dependencies"));
        dependencies.put("1002",n(1));datasetEntry.put("dependencies",dependencies);
        assertEquals("page_release_plan_entry",refused(()->PageReleaseProtocol.revisionSha256(closure)).code);
    }

    @Test public void twoTargetReviewRederivesProjectionAndClosedDataOnlyPackage()throws Exception{
        Map<String,Object> plan=PageReleaseProtocol.review(fixture.document(),NOW,Set.of(),fixture.files());
        assertEquals(2,array(plan.get("targets")).size());
        TargetData kiosk=fixture.targets().get(KIOSK_DEVICE);
        Map<String,Object> content=PageReleaseProtocol.entrypoint(kiosk.metadata(),fixture.files().get(KIOSK_DEVICE),kiosk.projection());
        assertEquals("kiosk-landscape",str(object(content.get("page")),"target"));
        assertEquals("Opening night",str(object(array(content.get("events")).get(0)),"title"));
        assertEquals("News",str(object(array(content.get("tags")).get(0)),"name"));
        assertArrayEquals(PublisherAuthority.canonical(PageReleaseProtocol.projectTarget(fixture.revision(),KIOSK_DEVICE,"kiosk-landscape")),
            PublisherAuthority.canonical(content));
        Set<String> packagePaths=fixture.files().get(KIOSK_DEVICE).packageFiles().keySet();
        assertEquals(Set.of("manifest.json",ENTRY,IMAGE),packagePaths);
        assertTrue(fixture.files().get(KIOSK_DEVICE).kioskFiles().isEmpty());
        assertTrue(fixture.files().get(KIOSK_DEVICE).tvFiles().isEmpty());
    }

    @Test public void pageReviewSummaryShowsExactPlanTargetsAndAuthors()throws Exception{
        Map<String,Object> summary=PublisherReview.pageReviewSummary(fixture.document(),fixture.files(),NOW,
            Set.of(),PageReleaseProtocol.SHIPPED_JS_SHA256,PageReleaseProtocol.SHIPPED_CSS_SHA256);
        assertEquals(str(obj(fixture.document(),"plan"),"id"),str(summary,"plan_id"));
        assertEquals(fixture.revisionHash(),str(summary,"revision_sha256"));
        assertEquals(8,array(summary.get("included")).size());
        assertEquals("working",str(object(array(summary.get("excluded")).get(0)),"reason"));
        assertEquals("alice",str(object(array(summary.get("included")).get(0)),"author"));
        assertEquals(2,array(summary.get("targets")).size());
        Map<String,Object> kiosk=object(array(summary.get("targets")).get(0));TargetData target=fixture.targets().get(KIOSK_DEVICE);
        assertEquals(KIOSK_DEVICE,str(kiosk,"device_id"));assertEquals(target.projection(),str(kiosk,"projection"));
        assertEquals(target.destination(),str(kiosk,"destination"));assertEquals(target.metadataSha(),str(kiosk,"metadata_sha256"));
        assertEquals(LocalView.digest(target.content()),str(kiosk,"content_sha256"));
        assertEquals(target.renderer(),str(kiosk,"renderer"));
    }

    @Test public void structuralPublishReviewRederivesEveryTargetAndRefusesSubstitution()throws Exception{
        Map<String,Object> summary=PublisherReview.pageReviewSummary(fixture.document(),NOW,Set.of(),
            PageReleaseProtocol.SHIPPED_JS_SHA256,PageReleaseProtocol.SHIPPED_CSS_SHA256);
        assertEquals(str(obj(fixture.document(),"plan"),"id"),str(summary,"plan_id"));
        assertTrue(array(summary.get("parents")).isEmpty());
        Map<String,Object> kiosk=object(array(summary.get("targets")).get(0));TargetData target=fixture.targets().get(KIOSK_DEVICE);
        assertEquals(target.packageId(),str(kiosk,"package_id"));
        assertEquals(target.rawManifestSha(),str(kiosk,"raw_manifest_sha256"));
        assertEquals(PageReleaseProtocol.SHIPPED_JS_SHA256,str(kiosk,"renderer_js_sha256"));
        assertEquals(PageReleaseProtocol.SHIPPED_CSS_SHA256,str(kiosk,"renderer_css_sha256"));

        Map<String,Object> plan=PublisherReview.reviewPageDocument(fixture.document(),NOW,Set.of(),
            PageReleaseProtocol.SHIPPED_JS_SHA256,PageReleaseProtocol.SHIPPED_CSS_SHA256);
        Map<String,Object> approval=PublisherEnvelope.signPage(new SoftwareKey(fixture.device()),plan);
        assertEquals(str(obj(fixture.document(),"plan"),"id"),str(
            PageReleaseProtocol.pageVerified(approval,fixture.device().getPublic()),"id"));

        assertEquals("page_release_renderer_mismatch",refused(()->PublisherReview.reviewPageDocument(
            fixture.document(),NOW,Set.of(),"a".repeat(64),PageReleaseProtocol.SHIPPED_CSS_SHA256)).code);

        Map<String,Object> tampered=new LinkedHashMap<>(fixture.document());List<Object> targets=new ArrayList<>();
        for(Object item:array(tampered.get("targets"))){Map<String,Object> copy=new LinkedHashMap<>(object(item));
            if(KIOSK_DEVICE.equals(str(copy,"device_id"))){Map<String,Object> metadata=new LinkedHashMap<>(obj(copy,"metadata"));
                metadata.put("content_sha256","9".repeat(64));copy.put("metadata",metadata);}
            targets.add(copy);}
        tampered.put("targets",targets);
        assertEquals("page_release_metadata_substitution",refused(()->PageReleaseProtocol.review(
            tampered,NOW,Set.of(),null)).code);
    }

    @Test public void v4AdmissionRequiresExactLocalIdentityRendererAndSignedTarget()throws Exception{
        Map<String,Object> approval=PublisherReview.approvePage(new SoftwareKey(fixture.device()),fixture.document(),
            fixture.files(),NOW,Set.of(),PageReleaseProtocol.SHIPPED_JS_SHA256,PageReleaseProtocol.SHIPPED_CSS_SHA256);
        Map<String,Object> signed=proof(fixture,approval,a());
        PageReleaseProtocol.PageAdmission admitted=admit(fixture,KIOSK_DEVICE,signed,
            fixture.files().get(KIOSK_DEVICE),Set.of());
        assertEquals(KIOSK_DEVICE,admitted.target().get("device_id"));
        assertEquals(PageReleaseProtocol.PROFILE,PageReleaseProtocol.validateMetadata(admitted.metadata()).get("resource_profile"));

        Map<String,Object> optional=new LinkedHashMap<>(signed);optional.remove("ancestry");
        assertEquals(KIOSK_DEVICE,admit(fixture,KIOSK_DEVICE,optional,
            fixture.files().get(KIOSK_DEVICE),Set.of()).target().get("device_id"));

        TargetData target=fixture.targets().get(KIOSK_DEVICE);
        assertEquals("page_release_local_identity",refused(()->PageReleaseProtocol.admit(signed,
            assignment(fixture,KIOSK_DEVICE,signed),fixture.root().getPublic(),ORIGIN,NOW,
            fixture.files().get(KIOSK_DEVICE),"other-group",KIOSK_DEVICE,PageReleaseProtocol.PROFILE,
            target.destination(),PageReleaseProtocol.SHIPPED_JS_SHA256,PageReleaseProtocol.SHIPPED_CSS_SHA256,0,Set.of())).code);
        assertEquals("page_release_local_identity",refused(()->PageReleaseProtocol.admit(signed,
            assignment(fixture,KIOSK_DEVICE,signed),fixture.root().getPublic(),ORIGIN,NOW,
            fixture.files().get(KIOSK_DEVICE),GROUP,"other-device",PageReleaseProtocol.PROFILE,
            target.destination(),PageReleaseProtocol.SHIPPED_JS_SHA256,PageReleaseProtocol.SHIPPED_CSS_SHA256,0,Set.of())).code);
        assertEquals("page_release_local_identity",refused(()->PageReleaseProtocol.admit(signed,
            assignment(fixture,KIOSK_DEVICE,signed),fixture.root().getPublic(),ORIGIN,NOW,
            fixture.files().get(KIOSK_DEVICE),GROUP,KIOSK_DEVICE,PageReleaseProtocol.PROFILE,
            "windows-pages-v1",PageReleaseProtocol.SHIPPED_JS_SHA256,PageReleaseProtocol.SHIPPED_CSS_SHA256,0,Set.of())).code);
        assertEquals("page_release_renderer_mismatch",refused(()->PageReleaseProtocol.admit(signed,
            assignment(fixture,KIOSK_DEVICE,signed),fixture.root().getPublic(),ORIGIN,NOW,
            fixture.files().get(KIOSK_DEVICE),GROUP,KIOSK_DEVICE,PageReleaseProtocol.PROFILE,
            target.destination(),"a".repeat(64),PageReleaseProtocol.SHIPPED_CSS_SHA256,0,Set.of())).code);

        Map<String,Object> variant=assignment(fixture,KIOSK_DEVICE,signed);
        variant.put("projection","tv-landscape");
        assertEquals("publisher_target_substitution",refused(()->PageReleaseProtocol.admit(signed,variant,
            fixture.root().getPublic(),ORIGIN,NOW,fixture.files().get(KIOSK_DEVICE),GROUP,KIOSK_DEVICE,
            PageReleaseProtocol.PROFILE,target.destination(),PageReleaseProtocol.SHIPPED_JS_SHA256,
            PageReleaseProtocol.SHIPPED_CSS_SHA256,0,Set.of())).code);

        Map<String,Object> display=new LinkedHashMap<>(target.configuration());display.put("profile_id","other-profile");
        Map<String,Object> changed=assignment(fixture,KIOSK_DEVICE,signed);changed.put("display",display);
        assertEquals("publisher_configuration_substitution",refused(()->PageReleaseProtocol.admit(signed,changed,
            fixture.root().getPublic(),ORIGIN,NOW,fixture.files().get(KIOSK_DEVICE),GROUP,KIOSK_DEVICE,
            PageReleaseProtocol.PROFILE,target.destination(),PageReleaseProtocol.SHIPPED_JS_SHA256,
            PageReleaseProtocol.SHIPPED_CSS_SHA256,0,Set.of())).code);

        Map<String,Object> substituted=assignment(fixture,KIOSK_DEVICE,signed);
        substituted.put("publisher",proof(fixture,approval,List.of("9".repeat(64))));
        assertEquals("page_release_proof_substitution",refused(()->PageReleaseProtocol.admit(signed,substituted,
            fixture.root().getPublic(),ORIGIN,NOW,fixture.files().get(KIOSK_DEVICE),GROUP,KIOSK_DEVICE,
            PageReleaseProtocol.PROFILE,target.destination(),PageReleaseProtocol.SHIPPED_JS_SHA256,
            PageReleaseProtocol.SHIPPED_CSS_SHA256,0,Set.of())).code);
    }

    @Test public void crossTargetPackageAndExecutableOrInconsistentManifestAreRefused()throws Exception{
        Map<String,Object> approval=PublisherReview.approvePage(new SoftwareKey(fixture.device()),fixture.document(),
            fixture.files(),NOW,Set.of(),PageReleaseProtocol.SHIPPED_JS_SHA256,PageReleaseProtocol.SHIPPED_CSS_SHA256);
        Map<String,Object> signed=proof(fixture,approval,a());
        assertEquals("page_release_inventory",refused(()->admit(fixture,KIOSK_DEVICE,signed,
            fixture.files().get(TV_DEVICE),Set.of())).code);

        TargetData kiosk=fixture.targets().get(KIOSK_DEVICE);
        byte[] evil=bytes("alert(1)");
        List<Object> executableRows=new ArrayList<>(kiosk.innerRows());executableRows.add(row("evil.js",evil));
        Map<String,byte[]> executableFiles=new TreeMap<>(kiosk.packageFiles());
        executableFiles.remove("manifest.json");executableFiles.put("evil.js",evil);
        PackageCase executable=rebuild(fixture,KIOSK_DEVICE,executableRows,executableFiles);
        assertEquals("page_release_data_only",refused(()->PageReleaseProtocol.review(executable.document(),
            NOW,Set.of(),executable.files())).code);

        List<Object> inconsistent=new ArrayList<>();
        for(Object item:kiosk.innerRows()){
            Map<String,Object> value=object(item);
            if(ENTRY.equals(str(value,"path")))
                inconsistent.add(m("path",ENTRY,"size",n(1),"sha256","9".repeat(64)));
            else inconsistent.add(value);
        }
        Map<String,byte[]> unchanged=new TreeMap<>(kiosk.packageFiles());unchanged.remove("manifest.json");
        PackageCase mismatch=rebuild(fixture,KIOSK_DEVICE,inconsistent,unchanged);
        assertEquals("page_release_package_inventory",refused(()->PageReleaseProtocol.review(mismatch.document(),
            NOW,Set.of(),mismatch.files())).code);
    }

    @Test public void activationRecheckRebindsExactTargetAndRefusesChangedBytesOrFacts()throws Exception{
        Map<String,Object> approval=PublisherReview.approvePage(new SoftwareKey(fixture.device()),fixture.document(),
            fixture.files(),NOW,Set.of(),PageReleaseProtocol.SHIPPED_JS_SHA256,PageReleaseProtocol.SHIPPED_CSS_SHA256);
        Map<String,Object> signed=proof(fixture,approval,a());
        PageReleaseProtocol.Files files=fixture.files().get(KIOSK_DEVICE);
        PageReleaseProtocol.PageAdmission admitted=admit(fixture,KIOSK_DEVICE,signed,files,Set.of());

        Map<String,Object> content=PageReleaseProtocol.recheck(admitted,files,
            PageReleaseProtocol.SHIPPED_JS_SHA256,PageReleaseProtocol.SHIPPED_CSS_SHA256);
        assertArrayEquals(PublisherAuthority.canonical(admitted.content()),PublisherAuthority.canonical(content));

        Map<String,byte[]> changed=new TreeMap<>(files.packageFiles());
        changed.put(IMAGE,bytes("tampered-image"));
        assertEquals("page_release_inventory",refused(()->PageReleaseProtocol.recheck(admitted,
            new PageReleaseProtocol.Files(changed,Map.of(),Map.of()),PageReleaseProtocol.SHIPPED_JS_SHA256,
            PageReleaseProtocol.SHIPPED_CSS_SHA256)).code);

        Map<String,Object> target=new LinkedHashMap<>(admitted.target());
        target.put("projection","tv-landscape");
        PageReleaseProtocol.PageAdmission changedTarget=new PageReleaseProtocol.PageAdmission(admitted.plan(),target,
            admitted.policy(),admitted.metadata(),admitted.publication(),admitted.content(),admitted.packageId(),
            admitted.revision(),admitted.destination(),admitted.projection(),admitted.renderer(),
            admitted.contentSha256(),admitted.metadataSha256());
        assertEquals("page_release_target_substitution",refused(()->PageReleaseProtocol.recheck(changedTarget,
            files,PageReleaseProtocol.SHIPPED_JS_SHA256,PageReleaseProtocol.SHIPPED_CSS_SHA256)).code);

        Map<String,Object> metadata=new LinkedHashMap<>(admitted.metadata());
        metadata.put("content_sha256","9".repeat(64));
        PageReleaseProtocol.PageAdmission changedMetadata=new PageReleaseProtocol.PageAdmission(admitted.plan(),
            admitted.target(),admitted.policy(),metadata,admitted.publication(),admitted.content(),
            admitted.packageId(),admitted.revision(),admitted.destination(),admitted.projection(),
            admitted.renderer(),admitted.contentSha256(),admitted.metadataSha256());
        assertEquals("page_release_metadata_substitution",refused(()->PageReleaseProtocol.recheck(changedMetadata,
            files,PageReleaseProtocol.SHIPPED_JS_SHA256,PageReleaseProtocol.SHIPPED_CSS_SHA256)).code);
    }

    @Test public void perTargetByteReviewHashesEveryExactPackageFile()throws Exception{
        Map<String,Object> reviewed=PageReleaseProtocol.reviewTarget(fixture.document(),KIOSK_DEVICE,NOW,
            Set.of(),fixture.files().get(KIOSK_DEVICE),PageReleaseProtocol.SHIPPED_JS_SHA256,
            PageReleaseProtocol.SHIPPED_CSS_SHA256);
        assertEquals(KIOSK_DEVICE,str(object(reviewed.get("target")),"device_id"));

        Map<String,byte[]> changed=new TreeMap<>(fixture.files().get(KIOSK_DEVICE).packageFiles());
        changed.put(IMAGE,bytes("synthetic-pnX"));
        assertEquals("page_release_inventory",refused(()->PageReleaseProtocol.reviewTarget(
            fixture.document(),KIOSK_DEVICE,NOW,Set.of(),new PageReleaseProtocol.Files(changed,Map.of(),Map.of()),
            PageReleaseProtocol.SHIPPED_JS_SHA256,PageReleaseProtocol.SHIPPED_CSS_SHA256)).code);
        assertEquals("page_release_content_substitution",refused(()->PageReleaseProtocol.reviewTarget(
            fixture.document(),KIOSK_DEVICE,NOW,Set.of(),fixture.files().get(TV_DEVICE),
            PageReleaseProtocol.SHIPPED_JS_SHA256,PageReleaseProtocol.SHIPPED_CSS_SHA256)).code);
    }

    @Test public void ancestryChainBindsExactV2ParentsAndRefusesGapsForeignOrLegacy()throws Exception{
        SoftwareKey key=new SoftwareKey(fixture.device());
        Map<String,Object> current=obj(fixture.document(),"plan");
        Map<String,Object> prior=new LinkedHashMap<>(current);
        assertArrayEquals(PublisherAuthority.canonical(prior),
            PublisherAuthority.canonical(PageReleaseProtocol.pageVerified(PublisherEnvelope.signPage(key,prior),
                fixture.device().getPublic())));

        Map<String,Object> parented=new LinkedHashMap<>(current);
        parented.remove("id");parented.put("parents",a(str(prior,"id")));parented.put("id",planId(parented));
        Map<String,Object> document=new LinkedHashMap<>(fixture.document());
        document.put("plan",parented);document.put("ancestry",a(prior));
        Map<String,Object> approval=PublisherReview.approvePage(key,document,fixture.files(),NOW,Set.of(),
            PageReleaseProtocol.SHIPPED_JS_SHA256,PageReleaseProtocol.SHIPPED_CSS_SHA256);
        PageReleaseProtocol.PageAdmission admitted=admit(fixture,KIOSK_DEVICE,proof(fixture,approval,a(prior)),
            fixture.files().get(KIOSK_DEVICE),Set.of());
        assertEquals(a(str(prior,"id")),array(admitted.plan().get("parents")));

        assertEquals("publisher_ancestry_refused",refused(()->admit(fixture,KIOSK_DEVICE,
            proof(fixture,approval,a(prior,prior)),fixture.files().get(KIOSK_DEVICE),Set.of())).code);
        assertEquals("publisher_known_conflict",refused(()->admit(fixture,KIOSK_DEVICE,
            proof(fixture,approval,a(prior)),fixture.files().get(KIOSK_DEVICE),Set.of("9".repeat(64)))).code);

        String unknown="8".repeat(64);
        Map<String,Object> middle=new LinkedHashMap<>(prior);middle.remove("id");
        middle.put("parents",a(unknown));middle.put("id",planId(middle));
        Map<String,Object> chained=new LinkedHashMap<>(current);chained.remove("id");
        chained.put("parents",a(str(middle,"id")));chained.put("id",planId(chained));
        assertEquals("publisher_ancestry_required",refused(()->admit(fixture,KIOSK_DEVICE,
            proof(fixture,PublisherEnvelope.signPage(key,chained),a()),
            fixture.files().get(KIOSK_DEVICE),Set.of(unknown))).code);

        Map<String,Object> foreign=new LinkedHashMap<>(prior);foreign.remove("id");
        foreign.put("group_id","other-group");foreign.put("id",planId(foreign));
        Map<String,Object> foreignPlan=new LinkedHashMap<>(current);foreignPlan.remove("id");
        foreignPlan.put("parents",a(str(foreign,"id")));foreignPlan.put("id",planId(foreignPlan));
        assertEquals("publisher_ancestry_refused",refused(()->admit(fixture,KIOSK_DEVICE,
            proof(fixture,PublisherEnvelope.signPage(key,foreignPlan),a(foreign)),
            fixture.files().get(KIOSK_DEVICE),Set.of())).code);

        Map<String,Object> legacy=new LinkedHashMap<>(prior);legacy.put("version",n(1));
        assertEquals("publisher_ancestry_version",refused(()->admit(fixture,KIOSK_DEVICE,
            proof(fixture,approval,a(legacy)),fixture.files().get(KIOSK_DEVICE),Set.of())).code);

        Map<String,Object> forged=new LinkedHashMap<>(prior);forged.put("revision_sha256","9".repeat(64));
        assertEquals("publisher_plan_identity",refused(()->admit(fixture,KIOSK_DEVICE,
            proof(fixture,approval,a(forged)),fixture.files().get(KIOSK_DEVICE),Set.of())).code);
    }

    private static PackageCase rebuild(Fixture fixture,String device,List<Object> innerRows,
            Map<String,byte[]> desired)throws Exception{
        TargetData target=fixture.targets().get(device);
        Map<String,Object> manifest=m("schema_version",n(2),"kind","pages","revision",fixture.revisionHash(),
            "renderer","pages-v1","resource_contract",n(1),"files",innerRows,"entrypoints",a(ENTRY));
        byte[] raw=PublisherAuthority.canonical(manifest);
        Map<String,byte[]> packageFiles=new TreeMap<>(desired);packageFiles.put("manifest.json",raw);
        List<Object> rows=a(row("manifest.json",raw));
        for(Map.Entry<String,byte[]> entry:new TreeMap<>(desired).entrySet())rows.add(row(entry.getKey(),entry.getValue()));
        Map<String,Object> publication=m("version",n(2),"package_id",sha(manifest),"revision",fixture.revisionHash(),
            "raw_manifest_sha256",LocalView.digest(raw),
            "renderer",m("build_id",target.renderer(),"js_sha256",PageReleaseProtocol.SHIPPED_JS_SHA256,
                "css_sha256",PageReleaseProtocol.SHIPPED_CSS_SHA256),
            "resource_profile",PageReleaseProtocol.PROFILE,"limits",limits(),"windows_images",m(),
            "package",m("files",rows),"kiosk",m("files",a()),"tv",m("files",a()));
        Map<String,Object> metadata=m("version",n(2),"destination",target.destination(),
            "revision_sha256",fixture.revisionHash(),"content_sha256",LocalView.digest(target.content()),
            "publication",publication);
        String metadataSha=sha(metadata);
        Map<String,Object> document=new LinkedHashMap<>(fixture.document());
        Map<String,Object> plan=new LinkedHashMap<>(obj(fixture.document(),"plan"));
        List<Object> planTargets=new ArrayList<>();
        for(Object item:array(plan.get("targets"))){
            Map<String,Object> value=new LinkedHashMap<>(object(item));
            if(device.equals(str(value,"device_id")))value.put("metadata_sha256",metadataSha);
            planTargets.add(value);
        }
        plan.put("targets",planTargets);plan.remove("id");plan.put("id",planId(plan));
        List<Object> targets=new ArrayList<>();
        for(Object item:array(fixture.document().get("targets"))){
            Map<String,Object> value=new LinkedHashMap<>(object(item));
            if(device.equals(str(value,"device_id")))value.put("metadata",metadata);
            targets.add(value);
        }
        document.put("plan",plan);document.put("targets",targets);
        Map<String,PageReleaseProtocol.Files> files=new TreeMap<>(fixture.files());
        files.put(device,new PageReleaseProtocol.Files(packageFiles,Map.of(),Map.of()));
        return new PackageCase(document,files);
    }
}
