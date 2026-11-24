package org.kiosk.harness;

import android.content.Intent;
import android.test.InstrumentationTestCase;
import java.io.*;
import java.nio.file.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.kiosk.harness.storage.*;

/** Deliberate external ADB scenario entry points; not part of automatic regression class list. */
@SuppressWarnings("deprecation")
public class ProcessStoreDriverTest extends InstrumentationTestCase {
    public void testSeedA() throws Exception {
        StoredHarnessActivity activity=(StoredHarnessActivity)getInstrumentation().startActivitySync(new Intent(getInstrumentation().getTargetContext(),StoredHarnessActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        try{
            long end=android.os.SystemClock.elapsedRealtime()+23000;while(activity.busy&&android.os.SystemClock.elapsedRealtime()<end)Thread.sleep(25);assertFalse(activity.busy);
            getInstrumentation().runOnMainSync(()->activity.install("A"));end=android.os.SystemClock.elapsedRealtime()+23000;
            while(activity.busy&&android.os.SystemClock.elapsedRealtime()<end)Thread.sleep(25);assertEquals(PublicationFixtures.A.identity(),activity.visible);assertEquals("ready",activity.state);
            Thread.sleep(250);assertEquals(PublicationFixtures.A.identity(),activity.store.receipt());
        }finally{getInstrumentation().runOnMainSync(activity::finish);}
    }
    public void testHoldStagingForExternalKill() throws Exception {
        Path root=getInstrumentation().getTargetContext().getFilesDir().getCanonicalFile().toPath().resolve("fixture-publications");var store=new FixturePublicationStore(root);assertEquals(PublicationFixtures.A.identity(),store.pointer());
        var fixture=PublicationFixtures.B;AtomicInteger chunks=new AtomicInteger();
        store.install("B",new FixtureAssetSource(getInstrumentation().getTargetContext().getAssets(),fixture,false,new AtomicInteger()),new FixtureAssetSource(getInstrumentation().getTargetContext().getAssets(),fixture,true,new AtomicInteger()),point->{
            if(point.equals("copy_chunk")&&chunks.incrementAndGet()==1){
                try(FileOutputStream out=getInstrumentation().getTargetContext().openFileOutput("staging-barrier",0)){out.write(("B copy stream open pid="+android.os.Process.myPid()+"; external force-stop expected").getBytes(java.nio.charset.StandardCharsets.UTF_8));out.getFD().sync();}
                try{new CountDownLatch(1).await(60,TimeUnit.SECONDS);}catch(InterruptedException e){Thread.currentThread().interrupt();}
                throw new IOException("bounded_external_kill_gate_expired");
            }
        });
        fail("Expected external force-stop to end this instrumentation, not a success result");
    }
}
