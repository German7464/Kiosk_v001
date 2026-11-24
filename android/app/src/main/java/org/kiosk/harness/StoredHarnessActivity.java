package org.kiosk.harness;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.*;
import android.util.Log;
import android.view.*;
import android.widget.*;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.JSONObject;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.storage.*;
import org.kiosk.harness.binding.CapturedCandidate;

/** Separate explicit, closed-fixture private-publication experiment; not a delivery client. */
public final class StoredHarnessActivity extends Activity {
    private static final int PICK_PUBLISHER_ROOT = 8417;
    private final Handler ui=new Handler(Looper.getMainLooper());
    private final ExecutorService worker=Executors.newSingleThreadExecutor();
    private final AtomicInteger assetReads=new AtomicInteger();
    private final AtomicInteger packageAssetReads=new AtomicInteger();
    private final String session=UUID.randomUUID().toString();
    private volatile long token;
    private volatile boolean closed;
    private volatile boolean closing;
    volatile boolean busy;
    volatile String state="loading",visible=null;
    volatile String selectedMode="tv",visibleMode=null;
    FixturePublicationStore store;
    PreparedWebView active,candidate;
    private FrameLayout frame;private TextView status,message;private Button installA,installB,kiosk,tv;
    private List<FixturePublicationStore.Selection> choices=List.of();
    private int choiceIndex;
    private boolean hadReady;
    private Runnable watchdog;
    private FixturePublicationStore.Checkpoint faults=FixturePublicationStore.NONE;
    private PreparedWebView.Factory factory=PreparedWebView.PLATFORM;
    private boolean created;
    private java.nio.file.Path configuredRoot;
    private PreparedAdmission.VerifierProvider admissionVerifiers=PreparedAdmission.UNAVAILABLE;
    private org.kiosk.harness.delivery.DeliveryClient delivery;
    private TextView deliveryStatus;
    private org.kiosk.harness.pairing.PairingDialog pairing;
    private final Runnable pairingTick=new Runnable(){public void run(){updatePairing();if(pairing!=null)ui.postDelayed(this,5000);}};
    private org.kiosk.harness.discovery.DiscoveryDialog discovery;
    private final ExecutorService network=Executors.newSingleThreadExecutor();
    private Runnable deliveryRetry;
    private final org.kiosk.harness.delivery.DeliverySchedule deliverySchedule=new org.kiosk.harness.delivery.DeliverySchedule();

    void configure(FixturePublicationStore.Checkpoint faults,PreparedWebView.Factory factory){
        if(created)throw new IllegalStateException("activity_already_created");this.faults=faults;this.factory=factory;
    }
    void configureRoot(java.nio.file.Path root){if(created)throw new IllegalStateException("activity_already_created");configuredRoot=root;}
    void configureAdmission(PreparedAdmission.VerifierProvider verifiers){if(created)throw new IllegalStateException("activity_already_created");admissionVerifiers=verifiers;}
    @Override public void onCreate(Bundle saved){
        super.onCreate(saved);created=true;
        if(admissionVerifiers==PreparedAdmission.UNAVAILABLE)try{
            delivery=new org.kiosk.harness.delivery.DeliveryClient(this);
            delivery.setProgressListener(this::nativeStatus);
            admissionVerifiers=()->delivery.confirmed()?delivery:null;
        }catch(Exception refused){Log.w("StoredHarness","delivery_state_unavailable");}
        LinearLayout root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);
        status=new TextView(this);root.addView(status);
        if(delivery!=null){
            deliveryStatus=new TextView(this);root.addView(deliveryStatus);
            LinearLayout nativeControls=new LinearLayout(this);Button connect=new Button(this),sync=new Button(this),reenroll=new Button(this);
            connect.setText("Connect server");sync.setText("Sync Events");reenroll.setText("Re-enroll");nativeControls.addView(connect);nativeControls.addView(sync);nativeControls.addView(reenroll);root.addView(nativeControls);
            LinearLayout nativeMore=new LinearLayout(this);root.addView(nativeMore);
            connect.setOnClickListener(v->connectServer());sync.setOnClickListener(v->syncServer());
            Button renew=new Button(this);renew.setText("Renew bootstrap");nativeMore.addView(renew);
            renew.setOnClickListener(v->renewBootstrap());
            Button showPairing=new Button(this);showPairing.setText("Show pairing code");nativeMore.addView(showPairing);
            showPairing.setOnClickListener(v->showPairing());
            Button publisherRoot=new Button(this);publisherRoot.setText("Publisher root");nativeMore.addView(publisherRoot);
            publisherRoot.setOnClickListener(v->choosePublisherRoot());
            LinearLayout adminRow=new LinearLayout(this);root.addView(adminRow);
            Button administration=new Button(this);administration.setText("Administration");adminRow.addView(administration);
            administration.setOnClickListener(v->startActivity(new android.content.Intent(this,org.kiosk.harness.admin.AdminActivity.class)));
            Button resync=new Button(this);resync.setText("Full resync");root.addView(resync);
            resync.setOnClickListener(v->{if(!busy)network.execute(()->{try{delivery.fullResync();nativeStatus("Incomplete capture discarded; checking Events.");ui.post(()->scheduleDelivery(0));}catch(Exception unavailable){nativeStatus("Capture is busy; retry full resync later.");}});});
            Button confirmTime=new Button(this);confirmTime.setText("Confirm device time");root.addView(confirmTime);
            confirmTime.setOnClickListener(v->new android.app.AlertDialog.Builder(this).setTitle("Confirm device date and time")
                .setMessage("Check the device date and time against an independent trusted clock. Resume updates with the existing enrollment only if they are correct.")
                .setNegativeButton("Cancel",null).setPositiveButton("Confirm",(d,w)->network.execute(()->{try{delivery.confirmClock();nativeStatus("Time confirmed; checking Events.");ui.post(()->scheduleDelivery(0));}catch(Exception e){nativeStatus("Time refused; saved Events retained.");}})).show());
            reenroll.setOnClickListener(v->{if(delivery.confirmed())new android.app.AlertDialog.Builder(this).setTitle("Explicit re-enrollment")
                .setMessage("Confirm current automatic device time is correct. Replace this device credential through external PC1 approval; retain saved offline Events and the same trust anchor.")
                .setNegativeButton("Cancel",null).setPositiveButton("Confirm",(d,w)->network.execute(()->{try{delivery.reenroll();delivery.authorize();nativeStatus("Waiting for administrator approval. Code "+delivery.humanCode()+".");ui.post(()->{showPairing();scheduleDelivery(0);});}catch(Exception e){nativeStatus("Re-enrollment refused; check trusted time and bootstrap expiry.");}})).show();});
        }
        LinearLayout controls=new LinearLayout(this);installA=new Button(this);installB=new Button(this);
        installA.setText("Install / resume A");installB.setText("Install / resume B");controls.addView(installA);controls.addView(installB);root.addView(controls);
        LinearLayout modes=new LinearLayout(this);kiosk=new Button(this);tv=new Button(this);kiosk.setText("Kiosk mode");tv.setText("TV mode");modes.addView(kiosk);modes.addView(tv);root.addView(modes);
        frame=new FrameLayout(this);message=new TextView(this);message.setGravity(Gravity.CENTER);frame.addView(message,new FrameLayout.LayoutParams(-1,-1));root.addView(frame,new LinearLayout.LayoutParams(-1,0,1));
        setContentView(root);
        try{store=new FixturePublicationStore(configuredRoot==null?getFilesDir().getCanonicalFile().toPath().resolve("fixture-publications"):configuredRoot,faults,admissionVerifiers);}
        catch(IOException unavailable){state="failed";message.setText("Private offline storage unavailable.");controls(false);update();return;}
        root.setOnApplyWindowInsetsListener((v,insets)->{var b=insets.getInsets(WindowInsets.Type.systemBars());v.setPadding(b.left,b.top,b.right,b.bottom);return insets;});
        installA.setOnClickListener(v->install("A"));installB.setOnClickListener(v->install("B"));
        kiosk.setOnClickListener(v->chooseMode("kiosk"));tv.setOnClickListener(v->chooseMode("tv"));
        startup();
        if(delivery!=null){deliveryRetry=this::syncServer;scheduleDelivery(0);}
    }
    private void choosePublisherRoot(){
        if(delivery==null||!delivery.confirmed()){nativeStatus("Connect and confirm the server before setting the publisher root.");return;}
        Intent pick=new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/json");
        startActivityForResult(pick,PICK_PUBLISHER_ROOT);
    }
    @Override protected void onActivityResult(int request,int result,Intent data){
        super.onActivityResult(request,result,data);
        if(request!=PICK_PUBLISHER_ROOT||result!=RESULT_OK||data==null||data.getData()==null)return;
        try(InputStream in=getContentResolver().openInputStream(data.getData())){
            if(in==null)throw new IOException("publisher_public_missing");
            JSONObject value=new JSONObject(new String(LocalView.readBounded(in,65536),StandardCharsets.UTF_8));
            String spki=value.getString("root_spki"),fingerprint=value.getString("root_sha256");
            android.widget.EditText typed=new android.widget.EditText(this);typed.setSingleLine(true);
            typed.setHint("64 hex publisher root SHA-256");
            new android.app.AlertDialog.Builder(this).setTitle("Set display publisher root")
                .setMessage("Type the publisher root SHA-256 received through an independent trusted channel. A file alone authenticates nothing. This is the one-time local setup that lets this display verify signed publications.")
                .setView(typed).setNegativeButton("Cancel",null)
                .setPositiveButton("Confirm",(d,w)->network.execute(()->{
                    try{
                        String supplied=typed.getText().toString().replace(":","").replace(" ","").trim().toLowerCase(Locale.ROOT);
                        delivery.confirmPublisherRoot(spki,supplied);
                        nativeStatus("Display publisher root confirmed; signed publications can be verified.");
                    }catch(Exception e){nativeStatus("Publisher root refused: "+e.getMessage());}
                })).show();
        }catch(Exception e){nativeStatus("Publisher root file refused.");}
    }
    private void nativeStatus(String text){ui.post(()->{if(!closed&&deliveryStatus!=null)deliveryStatus.setText(text);});}
    private void connectServer(){
        if(discovery!=null)discovery.close();
        discovery=new org.kiosk.harness.discovery.DiscoveryDialog(this,this::confirmServer);
        discovery.show(delivery.trustedOrigin());
    }
    private void confirmServer(String origin){
        if(delivery.confirmed()&&!delivery.trustedOrigin().equals(origin)){nativeStatus("Origin mismatch refused before connection. Saved registration and Events retained.");return;}
        if(delivery.confirmed()){network.execute(()->{try{if(!delivery.enrolled()){delivery.authorize();nativeStatus("Waiting for administrator approval. Code "+delivery.humanCode()+".");ui.post(()->{showPairing();scheduleDelivery(0);});}else nativeStatus("Enrolled; Sync Events is available.");}catch(Exception e){nativeStatus("Enrollment refused or server unavailable.");}});return;}
        try {
            byte[] bytes=org.kiosk.harness.core.LocalView.readBounded(getAssets().open(getString(R.string.delivery_bootstrap_asset)),16384);
            var b=org.kiosk.harness.delivery.DeliveryProtocol.bootstrap(bytes,System.currentTimeMillis()/1000);
            if(!b.origin().equals(origin)){nativeStatus("Origin differs from independent bootstrap; refused before connection.");return;}
            String caFp=b.caFingerprint(),inputDigest=org.kiosk.harness.delivery.DeliveryProtocol.bootstrapDigest(bytes);
            new android.app.AlertDialog.Builder(this).setTitle("Confirm independent bootstrap")
                .setMessage("Server: "+b.origin()+"\nGroup: "+b.group()+"\nServer ID: "+b.server()
                    +"\nGroup key SHA256:\n"+b.keyId()+"\nTLS root CA SHA256:\n"+caFp
                    +"\nBootstrap file SHA256:\n"+inputDigest
                    +"\n\nCompare the bootstrap file SHA256 (or at least both fingerprints) with the value supplied through a separate trusted channel. A value shown only on this screen authenticates nothing."
                    +"\n\nThis pilot trust is a one-time local enrollment, not a general trust-installation mechanism.")
                .setNegativeButton("Cancel",null).setPositiveButton("Confirm",(dialog,which)->network.execute(()->{try{delivery.confirm(bytes);delivery.authorize();nativeStatus("Waiting for administrator approval. Code "+delivery.humanCode()+".");ui.post(()->{showPairing();scheduleDelivery(0);});}catch(Exception e){nativeStatus("Bootstrap/enrollment refused.");}})).show();
        }catch(Exception e){nativeStatus("Independent bootstrap unavailable or expired.");}
    }
    /** Manual same-anchor renewal of locally delivered public configuration; never a trust or time shortcut. */
    private void renewBootstrap(){
        if(delivery==null||closed||closing)return;
        network.execute(()->{
            try{
                byte[] bytes=org.kiosk.harness.core.LocalView.readBounded(getAssets().open("delivery-bootstrap-renewal.json"),16384);
                var facts=delivery.inspectRenewal(bytes);
                ui.post(()->{
                    if(closed||closing)return;
                    String message="Unsigned public configuration, not new signed authority.\n\n"
                        +"Bootstrap ID: "+facts.bootstrapId()+"\nOrigin: "+facts.origin()+"\nGroup: "+facts.group()
                        +"\nServer ID: "+facts.server()+"\nGroup key SHA256:\n"+facts.keyId()
                        +"\nRenewal input SHA256:\n"+org.kiosk.harness.delivery.DeliveryProtocol.bootstrapDigest(bytes)
                        +"\n\nIssued: "+java.time.Instant.ofEpochSecond(facts.issued())+"\nExpires: "+java.time.Instant.ofEpochSecond(facts.expires())
                        +"\nDevice time: "+java.time.Instant.ofEpochSecond(facts.deviceTime())
                        +(facts.unchanged()?"\n\nThis exact input is already accepted; confirming makes no change.":"")
                        +"\n\nConfirm the device date and time against an independent trusted clock before renewing. This does not confirm uncertain-boot time; use Confirm device time separately before network use.";
                    new android.app.AlertDialog.Builder(this).setTitle("Renew saved server bootstrap")
                        .setMessage(message).setNegativeButton("Cancel",null)
                        .setPositiveButton("Renew",(dialog,which)->network.execute(()->{
                            try{var saved=delivery.renew(bytes,true);
                                nativeStatus(saved.unchanged()?"Renewal input already accepted; registration retained.":"Bootstrap renewed; registration and Events retained. Confirm device time if the device rebooted.");
                                ui.post(()->scheduleDelivery(0));
                            }catch(Exception refused){nativeStatus("Renewal refused; saved registration and Events retained.");}
                        })).show();
                });
            }catch(Exception refused){nativeStatus("Renewal input unavailable, expired, or not the saved anchor; registration retained.");}
        });
    }
    private String pollEnrollment()throws Exception {
        String result=delivery.poll();
        if("approved".equals(result)){
            nativeStatus("Approved. Checking Events automatically.");
            ui.post(()->{updatePairing();scheduleDelivery(0);});
        }else if("pending".equals(result)){
            nativeStatus("Waiting for administrator approval. Code "+delivery.humanCode()+".");
            ui.post(this::showPairing);
        }else{
            nativeStatus("denied".equals(result)?"Pairing denied. Use Re-enroll to start a new request.":"Pairing request expired. Use Re-enroll to request a new code.");
            ui.post(this::updatePairing);
        }
        return result;
    }
    /** Displays the exact locally generated QR/manual code for the current pending request. */
    private void showPairing(){
        if(delivery==null||closed||closing)return;
        if(pairing!=null&&!pairing.closed()){updatePairing();return;}
        closePairing();
        String payload;long expires;
        try{payload=delivery.pairingPayload();expires=delivery.pendingExpiresAt();}catch(Exception unavailable){return;}
        if(payload.isEmpty())return;
        pairing=new org.kiosk.harness.pairing.PairingDialog(this,new org.kiosk.harness.pairing.PairingDialog.Actions(){
            @Override public void cancelRequest(){
                network.execute(()->{
                    try{delivery.cancelPending();}
                    catch(Exception refused){nativeStatus("Pairing cancellation refused; saved state retained.");}
                    ui.post(()->{updatePairing();if(!closed&&!closing&&!delivery.enrolled())scheduleDelivery(60000);});
                });
            }
            @Override public void refresh(){scheduleDelivery(0);}
        });
        pairing.show();
        updatePairing();
        ui.removeCallbacks(pairingTick);ui.postDelayed(pairingTick,5000);
    }
    private void updatePairing(){
        if(pairing==null)return;
        if(closed||closing||delivery==null||pairing.closed()){closePairing();return;}
        try{
            if(delivery.enrolled()){pairing.setStatus("Approved; credential saved.");closePairing();return;}
            String payload=delivery.pairingPayload();
            if(payload.isEmpty()){
                String reason=delivery.pairingState();
                if("denied".equals(reason))nativeStatus("Pairing denied. Use Re-enroll to start a new request.");
                else if("expired".equals(reason))nativeStatus("Pairing code expired. Use Re-enroll to request a new code.");
                else if("cancelled".equals(reason))nativeStatus("Local pairing wait cancelled; the server request stays pending until its code expires.");
                else nativeStatus("No displayable pending pairing request. Use Re-enroll for a new code.");
                closePairing();return;
            }
            if(!pairing.update(payload,delivery.pendingExpiresAt(),System.currentTimeMillis()/1000)){
                nativeStatus("Pairing code expired. Use Re-enroll to request a new code.");
                closePairing();return;
            }
            pairing.setStatus("Pending review. This screen does not approve the device.");
        }catch(Exception unavailable){closePairing();}
    }
    private void closePairing(){ui.removeCallbacks(pairingTick);if(pairing!=null){pairing.close();pairing=null;}}
    private void scheduleDelivery(long delay){if(!closed&&!closing&&deliveryRetry!=null){ui.removeCallbacks(deliveryRetry);ui.postDelayed(deliveryRetry,delay);}}
    private void finishDelivery(boolean success){scheduleDelivery(Math.max(deliverySchedule.finish(success),delivery==null?0:delivery.transferRetryMillis()));}
    private void syncServer(){
        if(delivery==null||closed||closing)return;
        if(busy){scheduleDelivery(1000);return;}if(!deliverySchedule.begin())return;
        String locallyComplete=active!=null?visible:null;
        network.execute(()->{try{
            if(!delivery.confirmed()){ui.post(()->finishDelivery(true));return;}
            if(!delivery.enrolled()){
                // The same persisted enrollment request recovers an authorize response lost before saving its code.
                // A denied, expired or cancelled request waits for the explicit Re-enroll action instead of repeating.
                if(delivery.humanCode().isEmpty()&&!delivery.pairingBlocked())delivery.authorize();
                if(delivery.humanCode().isEmpty()){ui.post(()->{updatePairing();deliverySchedule.finish(false);scheduleDelivery(delivery.pairingBlocked()?60000:10000);});return;}
                String result=pollEnrollment();
                if(!delivery.enrolled()){boolean waiting="pending".equals(result);
                    ui.post(()->{deliverySchedule.finish(waiting);scheduleDelivery(waiting?10000:60000);});return;}
            }
            try{delivery.flush();}catch(Exception pending){nativeStatus("Ready receipts retained for retry.");}
            var downloaded=delivery.download(locallyComplete);
            if(downloaded==null){String mode=delivery.assignedMode(locallyComplete,visibleMode==null?"tv":visibleMode);
                ui.post(()->{if(!mode.equals(visibleMode))chooseMode(mode);
                    else if(hadReady&&active!=null)network.execute(()->{try{delivery.queueReady(locallyComplete,mode,session);delivery.flush();}catch(Exception pending){nativeStatus("Ready receipt retained for retry.");}});
                    finishDelivery(true);});nativeStatus("Events are current; published display profile accepted.");return;}
            ui.post(()->{if(closed||closing||!installPrepared(downloaded.capture(),downloaded.request())){try{downloaded.capture().close();}catch(Exception ignored){}finishDelivery(false);}});
            nativeStatus("Candidate captured; native admission pending.");
        }catch(Exception e){
            String reason=String.valueOf(e.getMessage());
            Log.w("StoredHarness","sync:"+reason);
            String recovery=delivery.credentialRecovery();
            if("authority_expired".equals(recovery)||"authority_expired".equals(reason)||"authority_window_refused".equals(reason))
                nativeStatus("Signed group authority for this server has expired. An administrator must renew the group trust; saved Events stay available offline.");
            else if("credential_revoked".equals(recovery)||"invalid_credential".equals(reason))
                nativeStatus("Access was revoked or replaced by the server. Use Re-enroll for administrator re-approval; saved Events stay available offline.");
            else if("credential_expired".equals(recovery)||"credential_expired".equals(reason))
                nativeStatus("Device access expired. Use Re-enroll for administrator re-approval; saved Events stay available offline.");
            else if(Set.of("unsupported_display_profile","display_assignment_refused").contains(reason))nativeStatus("Display assignment refused. Check profile compatibility, update client if needed, and publish again. Saved display retained.");
            else if("display_profile_conflict".equals(reason))nativeStatus("Published configuration conflict. Publish a new generation; saved display retained.");
            else nativeStatus("Update pending: check connection, credential and device time. Saved display retained.");
            ui.post(()->finishDelivery(false));}});
    }
    private long begin(){
        busy=true;long current=++token;state="loading";controls(false);
        message.setText("Verifying saved offline publication…");if(active==null)message.setVisibility(View.VISIBLE);
        arm(current);update();return current;
    }
    private void arm(long current){
        if(watchdog!=null)ui.removeCallbacks(watchdog);
        watchdog=()->{if(alive(current)){++token;failed("startup_timeout",true);}};
        ui.postDelayed(watchdog,HarnessActivity.STARTUP_MS);
    }
    private boolean alive(long current){return !closed&&!closing&&token==current;}
    private void startup(){
        long current=begin();
        worker.execute(()->{
            try {
                long deadline=SystemClock.elapsedRealtime()+HarnessActivity.STARTUP_MS;
                while(alive(current)){
                    try{
                        var initial=store.startup();
                        if(delivery!=null&&!initial.choices().isEmpty()){
                            String configured=delivery.startupMode(initial.choices().get(0).id(),initial.mode());
                            if(!configured.equals(initial.mode()))store.selectMode(configured,FixturePublicationStore.NONE);
                        }
                        var startup=store.startup();String mode=startup.mode();List<FixturePublicationStore.Selection> saved=startup.choices();
                        ui.post(()->{
                            if(!alive(current))return;selectedMode=mode;choices=saved;choiceIndex=0;
                            if(saved.isEmpty())failed("no_saved_publication",false);else prepare(saved.get(choiceIndex++),current);
                        });return;
                    }catch(IOException busy){
                        if(!"store_busy".equals(busy.getMessage())||SystemClock.elapsedRealtime()>=deadline)throw busy;
                        // Activity recreation can overlap the previous worker closing its lease.
                        // Bounded by the existing startup watchdog; never restarts a renderer/process.
                        Thread.sleep(25);
                    }
                }
            }catch(Exception e){postFailure(current,"saved_publication_refused");}
        });
    }
    /** Only native fixed buttons/tests invoke this; no Intent/path/URI selection or fault extras. */
    void install(String key){
        if(busy||closed||closing)return;
        var fixture=PublicationFixtures.key(key);long current=begin();choices=List.of();
        worker.execute(()->{
            try {
                String mode=store.selectedMode();
                var result=store.install(key,new FixtureAssetSource(getAssets(),fixture,false,packageAssetReads),new FixtureAssetSource(getAssets(),fixture,true,assetReads),new FixtureAssetSource(getAssets(),fixture,"kiosk",assetReads),mode,point->{if(!alive(current))throw new IOException("cancelled");});
                ui.post(()->{if(alive(current)){selectedMode=mode;prepare(result,current);}});
            }catch(Exception e){postFailure(current,"candidate_storage_refused");}
        });
    }
    void chooseMode(String mode){
        PublicationFixtures.mode(mode);if(busy||closed||closing)return;
        long current=begin();choices=List.of();
        worker.execute(()->{
            try{
                if(delivery!=null&&visible!=null&&!delivery.modeAllowed(visible,mode))throw new IOException("assigned_mode_required");
                var selection=store.selectMode(mode,point->{if(!alive(current))throw new IOException("cancelled");});
                ui.post(()->{if(alive(current)){selectedMode=mode;if(selection==null)failed("no_saved_publication",false);else prepare(selection,current);}});
            }catch(Exception e){postFailure(current,"mode_preparation_refused");}
        });
    }
    /** Native development caller only. true transfers capture ownership; false leaves it with caller. */
    boolean installDevelopment(CapturedCandidate capture,DevelopmentPlaybackAuthority.Permit permit,CapturedCandidate.Budget budget){
        if(busy||closed||closing)return false;
        long current=begin();choices=List.of();
        try{worker.execute(new DevelopmentJob(capture,permit,budget,current));return true;}
        catch(RejectedExecutionException rejected){failed("development_worker_unavailable",false);return false;}
    }
    private final class DevelopmentJob implements Runnable {
        final CapturedCandidate capture;final DevelopmentPlaybackAuthority.Permit permit;final CapturedCandidate.Budget budget;final long current;
        final java.util.concurrent.atomic.AtomicBoolean claimed=new java.util.concurrent.atomic.AtomicBoolean();
        DevelopmentJob(CapturedCandidate c,DevelopmentPlaybackAuthority.Permit p,CapturedCandidate.Budget b,long token){capture=c;permit=p;budget=b;current=token;}
        void abandon(){if(claimed.compareAndSet(false,true))try{capture.close();}catch(Exception e){Log.w("StoredHarness","capture_cleanup_failed");}}
        public void run(){
            if(!claimed.compareAndSet(false,true))return;
            try(capture){
                var result=store.installDevelopment(capture,permit,budget,point->{if(!alive(current))throw new IOException("cancelled");});
                ui.post(()->{if(alive(current)){selectedMode=store.modeOrInvalid();prepare(result,current);}});
            }catch(Exception failure){postFailure(current,"development_candidate_refused");}
        }
    }
    /** Native typed caller only; no path/Intent/page importer or authority parameter. */
    boolean installPrepared(CapturedCandidate capture,PreparedAdmission.Request request){
        if(busy||closed||closing)return false;long current=begin();choices=List.of();
        try{worker.execute(new PreparedJob(capture,request,current));return true;}
        catch(RejectedExecutionException rejected){failed("admission_worker_unavailable",false);return false;}
    }
    private final class PreparedJob implements Runnable {
        final CapturedCandidate capture;final PreparedAdmission.Request request;final long current;
        final java.util.concurrent.atomic.AtomicBoolean claimed=new java.util.concurrent.atomic.AtomicBoolean();
        PreparedJob(CapturedCandidate c,PreparedAdmission.Request r,long token){capture=c;request=r;current=token;}
        void abandon(){if(claimed.compareAndSet(false,true))try{capture.close();}catch(Exception e){Log.w("StoredHarness","capture_cleanup_failed");}}
        public void run(){
            if(!claimed.compareAndSet(false,true))return;
            boolean admitted=false;
            try(capture){var result=store.installPrepared(capture,request,point->{if(!alive(current))throw new IOException("cancelled");});
                admitted=true;
                if(delivery!=null){String mode=delivery.assignedMode(result.id(),result.view().mode);if(!mode.equals(result.view().mode))result=store.selectMode(mode,point->{if(!alive(current))throw new IOException("cancelled");});}
                final var preparedResult=result;
                if(delivery!=null)delivery.admissionResult(request,true);
                ui.post(()->{if(alive(current)){selectedMode=store.modeOrInvalid();prepare(preparedResult,current);}});
            }catch(Exception failure){if(delivery!=null)delivery.admissionFailure(request,failure);postFailure(current,"local_admission_refused");}
            finally{boolean success=admitted;if(delivery!=null)ui.post(()->finishDelivery(success));}
        }
    }
    private void shutdownWorker(){if(delivery!=null)delivery.closeProgress();if(discovery!=null)discovery.close();network.shutdownNow();if(deliveryRetry!=null)ui.removeCallbacks(deliveryRetry);for(Runnable pending:worker.shutdownNow()){
        if(pending instanceof DevelopmentJob)((DevelopmentJob)pending).abandon();
        if(pending instanceof PreparedJob)((PreparedJob)pending).abandon();
    }}
    private void postFailure(long current,String code){
        String actual=store.modeOrInvalid();ui.post(()->{if(alive(current)){selectedMode=actual;failed(code,false);}});
    }
    private void prepare(FixturePublicationStore.Selection selection,long current){
        if(!alive(current))return;
        PreparedWebView[] owned=new PreparedWebView[1];
        try {
            owned[0]=new PreparedWebView(this,selection.view(),current,new PreparedWebView.Completion(){
                @Override public void ready(){
                    if(!alive(current)||candidate!=owned[0])return;
                    PreparedWebView old=active;active=candidate;candidate=null;visible=selection.id();visibleMode=selection.view().mode;hadReady=true;
                    if(old!=null)old.dispose();
        state="ready_receipt_pending";message.setVisibility(View.GONE);
                    if(watchdog!=null)ui.removeCallbacks(watchdog);
                    update();
                    worker.execute(()->{
                        boolean saved=false;
                        if(delivery!=null&&delivery.confirmed())try{delivery.queueReady(selection.id(),selection.view().mode,session);network.execute(()->{try{delivery.flush();nativeStatus("Ready receipt delivered.");}catch(Exception pending){nativeStatus("Ready receipt queued for reconnect.");}});}catch(Exception queueFailure){nativeStatus("Ready receipt queue unavailable.");}
                        try{if(alive(current)){store.saveReady(selection.id(),selection.view().mode,point->{if(!alive(current))throw new IOException("cancelled");});saved=true;}}catch(Exception e){Log.w("StoredHarness","receipt_pending");}
                        boolean confirmed=saved;
                        ui.post(()->{if(alive(current)){state=confirmed?"ready":"ready_receipt_pending";done();}});
                    });
                }
                @Override public void failed(){
                    if(closed||closing)return;
                    if(active==owned[0]){
                        // Shared renderer/GPU cannot promise the old screen. No pointer rollback/restart.
                        active=null;visible=null;visibleMode=null;++token;StoredHarnessActivity.this.failed("active_renderer_failed",false);
                    }else if(candidate==owned[0]){candidate=null;StoredHarnessActivity.this.failed("candidate_renderer_failed",true);}
                }
            },factory);
            candidate=owned[0];frame.addView(candidate.browser,0,new FrameLayout.LayoutParams(-1,-1));candidate.start();
        }catch(Exception e){if(owned[0]!=null)owned[0].dispose();candidate=null;failed("engine_unavailable",true);}
    }
    private void failed(String code,boolean allowConfirmed){
        if(closed||closing)return;
        if(candidate!=null){candidate.dispose();candidate=null;}
        if(allowConfirmed&&active==null&&!hadReady&&choiceIndex<choices.size()){
            long next=++token;arm(next);prepare(choices.get(choiceIndex++),next);return;
        }
        if(watchdog!=null)ui.removeCallbacks(watchdog);
        state=active==null?"failed":"ready_previous_retained";
        if(active==null){visible=null;visibleMode=null;message.setText("No usable saved offline publication. Use a fixed fixture button or close and explicitly relaunch.");message.setVisibility(View.VISIBLE);}
        Log.w("StoredHarness",code);done();
    }
    private void controls(boolean enabled){installA.setEnabled(enabled);installB.setEnabled(enabled);kiosk.setEnabled(enabled);tv.setEnabled(enabled);}
    private void done(){busy=false;controls(true);update();snapshot();}
    private void update(){status.setText("DEVELOPMENT playback; admission unverified\nstate="+state+" selected="+selectedMode+"\nvisible="+(visible==null?"none":visible)+" mode="+visibleMode);}
    private void snapshot(){
        String actualVisible=visible,actualState=state,actualMode=visibleMode;
        worker.execute(()->{
            try{
                JSONObject record=new JSONObject().put("schema",1).put("session",session).put("pid",android.os.Process.myPid())
                    .put("state",actualState).put("pointer",store.pointer()).put("visible",actualVisible==null?JSONObject.NULL:actualVisible)
                    .put("selected_mode",store.modeOrInvalid()).put("visible_mode",actualMode==null?JSONObject.NULL:actualMode)
                    .put("receipt",store.receipt(store.modeOrInvalid())).put("receipt_tv",store.receipt("tv")).put("receipt_kiosk",store.receipt("kiosk"))
                    .put("private_reads",store.privateReads.get()).put("asset_reads",assetReads.get()+packageAssetReads.get()).put("package_asset_reads",packageAssetReads.get()).put("source","private_storage")
                    .put("development_authorized",store.developmentAuthorized(store.pointer())).put("admission_gates_unchecked",5)
                    .put("admission_record_issuer",store.admissionIssuer(store.pointer()))
                    .put("transfer",delivery==null?JSONObject.NULL:new JSONObject(delivery.transferSummary()))
                    .put("elapsed_realtime_ms",SystemClock.elapsedRealtime());
                store.diagnostic(record.toString());Log.i("StoredHarness",record.toString());
            }catch(Exception e){Log.w("StoredHarness","diagnostic_write_failed");}
        });
    }
    @Override protected void onPause(){if(active!=null)active.pause();super.onPause();}
    @Override protected void onStop(){if(discovery!=null)discovery.close();super.onStop();}
    @Override protected void onResume(){super.onResume();if(active!=null)active.resume();}
    @Override public void finish(){
        closing=true;++token;closePairing();ui.removeCallbacksAndMessages(null);shutdownWorker();
        if(candidate!=null){candidate.dispose();candidate=null;}
        super.finish();
    }
    @Override protected void onDestroy(){
        closed=true;++token;closePairing();ui.removeCallbacksAndMessages(null);shutdownWorker();
        if(candidate!=null)candidate.dispose();if(active!=null)active.dispose();candidate=null;active=null;visible=null;visibleMode=null;
        super.onDestroy();
    }
}
