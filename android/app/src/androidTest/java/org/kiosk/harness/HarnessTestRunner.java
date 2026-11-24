package org.kiosk.harness;

import android.app.Activity;
import android.os.Bundle;
import android.test.InstrumentationTestRunner;
import java.util.concurrent.atomic.AtomicReference;

/** Test APK only: injection is never selected by Intent, page or production statics. */
@SuppressWarnings("deprecation")
public final class HarnessTestRunner extends InstrumentationTestRunner {
    static final class StoreAdapters {
        final org.kiosk.harness.storage.FixturePublicationStore.Checkpoint faults;
        final PreparedWebView.Factory factory;
        final java.nio.file.Path root;
        StoreAdapters(org.kiosk.harness.storage.FixturePublicationStore.Checkpoint faults,PreparedWebView.Factory factory){this(faults,factory,null);}
        StoreAdapters(org.kiosk.harness.storage.FixturePublicationStore.Checkpoint faults,PreparedWebView.Factory factory,java.nio.file.Path root){this.faults=faults;this.factory=factory;this.root=root;}
    }
    static final AtomicReference<StoreAdapters> nextStoreAdapters=new AtomicReference<>();
    static final AtomicReference<org.kiosk.harness.storage.PreparedAdmission.VerifierProvider> nextAdmissionVerifier=new AtomicReference<>();
    static final class Adapters {
        final HarnessActivity.Preflight preflight;
        final PreparedWebView.Factory factory;
        Adapters(HarnessActivity.Preflight preflight, PreparedWebView.Factory factory) {
            this.preflight = preflight; this.factory = factory;
        }
    }
    static final AtomicReference<Adapters> nextAdapters = new AtomicReference<>();
    @Override public void callActivityOnCreate(Activity activity, Bundle saved) {
        if(activity instanceof StoredHarnessActivity){
            var admission=nextAdmissionVerifier.getAndSet(null);
            if(admission!=null)((StoredHarnessActivity)activity).configureAdmission(admission);
            StoreAdapters injected=nextStoreAdapters.getAndSet(null);
            if(injected!=null){((StoredHarnessActivity)activity).configure(injected.faults,injected.factory);((StoredHarnessActivity)activity).configureRoot(injected.root);}
        }
        if (activity instanceof HarnessActivity) {
            Adapters injected = nextAdapters.getAndSet(null);
            if (injected != null) ((HarnessActivity)activity).configureAdapters(injected.preflight, injected.factory);
        }
        super.callActivityOnCreate(activity, saved);
    }
}
