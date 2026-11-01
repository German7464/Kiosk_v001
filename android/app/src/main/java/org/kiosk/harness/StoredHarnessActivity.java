package org.kiosk.harness;

import android.app.Activity;
import android.os.*;
import android.util.Log;
import android.view.*;
import android.widget.*;
import java.io.IOException;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.JSONObject;
import org.kiosk.harness.storage.*;
import org.kiosk.harness.binding.CapturedCandidate;

/** Separate explicit, closed-fixture private-publication experiment; not a delivery client. */
public final class StoredHarnessActivity extends Activity {
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

    void configure(FixturePublicationStore.Checkpoint faults,PreparedWebView.Factory factory){
        if(created)throw new IllegalStateException("activity_already_created");this.faults=faults;this.factory=factory;
    }
    void configureRoot(java.nio.file.Path root){if(created)throw new IllegalStateException("activity_already_created");configuredRoot=root;}
    @Override public void onCreate(Bundle saved){
        super.onCreate(saved);created=true;
        LinearLayout root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);
        status=new TextView(this);root.addView(status);
        LinearLayout controls=new LinearLayout(this);installA=new Button(this);installB=new Button(this);
        installA.setText("Install / resume A");installB.setText("Install / resume B");controls.addView(installA);controls.addView(installB);root.addView(controls);
        LinearLayout modes=new LinearLayout(this);kiosk=new Button(this);tv=new Button(this);kiosk.setText("Kiosk mode");tv.setText("TV mode");modes.addView(kiosk);modes.addView(tv);root.addView(modes);
        frame=new FrameLayout(this);message=new TextView(this);message.setGravity(Gravity.CENTER);frame.addView(message,new FrameLayout.LayoutParams(-1,-1));root.addView(frame,new LinearLayout.LayoutParams(-1,0,1));
        setContentView(root);
        try{store=new FixturePublicationStore(configuredRoot==null?getFilesDir().getCanonicalFile().toPath().resolve("fixture-publications"):configuredRoot,faults);}
        catch(IOException unavailable){state="failed";message.setText("Private offline storage unavailable.");controls(false);update();return;}
        root.setOnApplyWindowInsetsListener((v,insets)->{var b=insets.getInsets(WindowInsets.Type.systemBars());v.setPadding(b.left,b.top,b.right,b.bottom);return insets;});
        installA.setOnClickListener(v->install("A"));installB.setOnClickListener(v->install("B"));
        kiosk.setOnClickListener(v->chooseMode("kiosk"));tv.setOnClickListener(v->chooseMode("tv"));
        startup();
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
    private void shutdownWorker(){for(Runnable pending:worker.shutdownNow())if(pending instanceof DevelopmentJob)((DevelopmentJob)pending).abandon();}
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
                    .put("elapsed_realtime_ms",SystemClock.elapsedRealtime());
                store.diagnostic(record.toString());Log.i("StoredHarness",record.toString());
            }catch(Exception e){Log.w("StoredHarness","diagnostic_write_failed");}
        });
    }
    @Override protected void onPause(){if(active!=null)active.pause();super.onPause();}
    @Override protected void onResume(){super.onResume();if(active!=null)active.resume();}
    @Override public void finish(){
        closing=true;++token;ui.removeCallbacksAndMessages(null);shutdownWorker();
        if(candidate!=null){candidate.dispose();candidate=null;}
        super.finish();
    }
    @Override protected void onDestroy(){
        closed=true;++token;ui.removeCallbacksAndMessages(null);shutdownWorker();
        if(candidate!=null)candidate.dispose();if(active!=null)active.dispose();candidate=null;active=null;visible=null;visibleMode=null;
        super.onDestroy();
    }
}
