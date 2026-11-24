package org.kiosk.harness;

import android.content.Intent;
import android.test.InstrumentationTestCase;
import java.nio.file.*;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import org.kiosk.harness.discovery.*;
import org.kiosk.harness.storage.FixturePublicationStore;

/** Real Activity recreation with a disposable empty store; no saved registration or delivery owner. */
@SuppressWarnings("deprecation")
public final class DiscoveryLifecycleTest extends InstrumentationTestCase {
    private Object field(Object o,String name)throws Exception{var f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);}
    private void configure(Path root){HarnessTestRunner.nextStoreAdapters.set(new HarnessTestRunner.StoreAdapters(FixturePublicationStore.NONE,PreparedWebView.PLATFORM,root));HarnessTestRunner.nextAdmissionVerifier.set(()->null);}
    public void testRecreationCancelsOwnedSearchAndClosesDialog()throws Exception{
        Path root=getInstrumentation().getTargetContext().getFilesDir().toPath().resolve("discovery-lifecycle-"+UUID.randomUUID());Files.createDirectory(root);configure(root);
        var activity=(StoredHarnessActivity)getInstrumentation().startActivitySync(new Intent(getInstrumentation().getTargetContext(),StoredHarnessActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_MULTIPLE_TASK));
        var monitor=getInstrumentation().addMonitor(StoredHarnessActivity.class.getName(),null,false);AtomicReference<DiscoveryDialog> dialog=new AtomicReference<>();AtomicReference<DiscoverySearch> search=new AtomicReference<>();StoredHarnessActivity replacement=null;
        try{
            getInstrumentation().runOnMainSync(()->{try{
                var d=new DiscoveryDialog(activity,origin->{throw new AssertionError("recreation must not select");});dialog.set(d);var f=activity.getClass().getDeclaredField("discovery");f.setAccessible(true);f.set(activity,d);d.show("https://saved:8443");((android.widget.Button)field(d,"find")).performClick();search.set((DiscoverySearch)field(d,"search"));configure(root);activity.recreate();
            }catch(Exception failure){throw new AssertionError(failure);}});
            replacement=(StoredHarnessActivity)monitor.waitForActivityWithTimeout(5000);assertNotNull("recreated Activity observed",replacement);getInstrumentation().waitForIdleSync();
            assertTrue((boolean)field(dialog.get(),"closed"));assertTrue((boolean)field(search.get(),"cancelled"));assertNull(field(dialog.get(),"search"));assertTrue(((java.util.concurrent.ExecutorService)field(dialog.get(),"worker")).isShutdown());
        }finally{
            var last=replacement;getInstrumentation().runOnMainSync(()->{if(dialog.get()!=null)dialog.get().close();activity.finish();if(last!=null)last.finish();});getInstrumentation().removeMonitor(monitor);getInstrumentation().waitForIdleSync();
        }
    }
}
