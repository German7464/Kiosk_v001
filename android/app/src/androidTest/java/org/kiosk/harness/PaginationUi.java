package org.kiosk.harness;
import android.content.pm.ActivityInfo;
import android.content.res.Configuration;
import android.os.SystemClock;
import android.view.*;
import android.webkit.WebView;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.json.*;
import org.kiosk.harness.storage.FixturePublicationStore;
final class PaginationUi {
    static JSONObject object(GenericPlaybackTest t,String js)throws Exception{return new JSONObject(new JSONArray("["+t.eval(js)+"]").getString(0));}
    static String asset(GenericPlaybackTest t,String name)throws Exception{try(var in=t.getInstrumentation().getContext().getAssets().open(name)){return new String(org.kiosk.harness.core.LocalView.readBounded(in,128*1024),java.nio.charset.StandardCharsets.UTF_8);}}
    static void expand(GenericPlaybackTest t){t.ui(()->{ViewGroup frame=(ViewGroup)t.activity.active.browser.getParent(),root=(ViewGroup)frame.getParent();for(int i=0;i<root.getChildCount();i++)if(root.getChildAt(i)!=frame)root.getChildAt(i).setVisibility(View.GONE);t.activity.active.browser.requestFocus();});}
    static void drawn(GenericPlaybackTest t)throws Exception{
        WebView browser=t.activity.active.browser;CountDownLatch done=new CountDownLatch(1);AtomicReference<ViewTreeObserver.OnDrawListener> listener=new AtomicReference<>();
        t.ui(()->{if(!browser.isAttachedToWindow())throw new AssertionError("unattached browser");browser.postVisualStateCallback(SystemClock.elapsedRealtimeNanos(),new WebView.VisualStateCallback(){public void onComplete(long id){ViewTreeObserver.OnDrawListener draw=()->done.countDown();listener.set(draw);browser.getViewTreeObserver().addOnDrawListener(draw);browser.invalidate();}});});
        try{if(!done.await(5,TimeUnit.SECONDS))throw new AssertionError("bounded visual draw");t.getInstrumentation().waitForIdleSync();Thread.sleep(50);}finally{t.ui(()->{if(listener.get()!=null&&browser.getViewTreeObserver().isAlive())browser.getViewTreeObserver().removeOnDrawListener(listener.get());});}
    }
    static void orient(GenericPlaybackTest t,boolean landscape)throws Exception{
        int desired=landscape?Configuration.ORIENTATION_LANDSCAPE:Configuration.ORIENTATION_PORTRAIT;
        if(t.activity.getResources().getConfiguration().orientation!=desired){var monitor=t.getInstrumentation().addMonitor(StoredHarnessActivity.class.getName(),null,false);HarnessTestRunner.nextStoreAdapters.set(new HarnessTestRunner.StoreAdapters(FixturePublicationStore.NONE,PreparedWebView.PLATFORM,t.root));t.ui(()->t.activity.setRequestedOrientation(landscape?ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE:ActivityInfo.SCREEN_ORIENTATION_PORTRAIT));var next=t.getInstrumentation().waitForMonitorWithTimeout(monitor,12000);t.getInstrumentation().removeMonitor(monitor);if(next==null)throw new AssertionError("orientation recreation missing");t.activity=(StoredHarnessActivity)next;t.until(()->t.activity.active!=null&&!t.activity.busy&&t.activity.state.equals("ready"),24000,"orientation private-ready");}
        expand(t);Thread.sleep(300);drawn(t);JSONObject shape=object(t,"JSON.stringify({w:innerWidth,h:innerHeight})");if(landscape!=(shape.getInt("w")>shape.getInt("h")))throw new AssertionError("measured shape");
    }
}
