package org.kiosk.harness.discovery;

import android.app.AlertDialog;
import android.content.Intent;
import android.test.InstrumentationTestCase;
import android.widget.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.kiosk.harness.HarnessActivity;

/** Synthetic native UI boundary checks on hardware; not LAN or authenticated acceptance. */
@SuppressWarnings("deprecation")
public final class DiscoveryDialogTest extends InstrumentationTestCase {
    private Object field(Object value,String name){try{var f=value.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(value);}catch(Exception e){throw new AssertionError(e);}}
    private void ui(Runnable r){getInstrumentation().runOnMainSync(r);}
    private DiscoveryDialog.Outcome outcome(boolean empty){return new DiscoveryDialog.Outcome("synthetic network",new DiscoverySearch.Result(empty?List.of():List.of(new DiscoveryProtocol.Hint("https://untrusted:9443","<b>hint</b>")),0,0,0,false,"",List.of()));}
    public void testExplicitSelectionManualFallbackCancellationAndStaleCallbacks()throws Exception{
        Intent intent=new Intent(getInstrumentation().getTargetContext(),HarnessActivity.class);intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        var activity=(HarnessActivity)getInstrumentation().startActivitySync(intent);AtomicReference<DiscoveryDialog> ref=new AtomicReference<>();AtomicReference<String> selected=new AtomicReference<>();
        try{
            ui(()->{var d=new DiscoveryDialog(activity,selected::set,s->outcome(false));ref.set(d);d.show("https://saved:8443");((Button)field(d,"find")).performClick();});
            Thread.sleep(250);getInstrumentation().waitForIdleSync();
            ui(()->{var d=ref.get();var rows=(LinearLayout)field(d,"results");assertEquals(1,rows.getChildCount());assertEquals("<b>hint</b>\nhttps://untrusted:9443",((Button)rows.getChildAt(0)).getText().toString());assertNull(selected.get());rows.getChildAt(0).performClick();assertNull(selected.get());assertEquals("https://untrusted:9443",((EditText)field(d,"address")).getText().toString());((AlertDialog)field(d,"dialog")).getButton(-1).performClick();assertEquals("https://untrusted:9443",selected.get());});
            selected.set(null);AtomicInteger calls=new AtomicInteger();CountDownLatch started=new CountDownLatch(1),release=new CountDownLatch(1);
            ui(()->{var d=new DiscoveryDialog(activity,selected::set,s->{calls.incrementAndGet();started.countDown();release.await(3,TimeUnit.SECONDS);return outcome(false);});ref.set(d);d.show("https://saved:8443");((Button)field(d,"find")).performClick();((Button)field(d,"find")).performClick();});
            assertTrue(started.await(1,TimeUnit.SECONDS));assertEquals(1,calls.get());
            ui(()->{var d=ref.get();try{var m=d.getClass().getDeclaredMethod("cancelSearch");m.setAccessible(true);m.invoke(d);}catch(Exception e){throw new AssertionError(e);}});release.countDown();Thread.sleep(150);getInstrumentation().waitForIdleSync();
            ui(()->{var d=ref.get();assertEquals(0,((LinearLayout)field(d,"results")).getChildCount());assertEquals("https://saved:8443",((EditText)field(d,"address")).getText().toString());d.close();});assertNull(selected.get());
            ui(()->{var d=new DiscoveryDialog(activity,selected::set,s->outcome(true));ref.set(d);d.show("");((Button)field(d,"find")).performClick();});Thread.sleep(150);getInstrumentation().waitForIdleSync();
            ui(()->{var d=ref.get();assertTrue(((TextView)field(d,"status")).getText().toString().contains("0 untrusted results"));var input=(EditText)field(d,"address");input.setText("http://bad:80");((AlertDialog)field(d,"dialog")).getButton(-1).performClick();assertNull(selected.get());input.setText("https://manual:9443");((AlertDialog)field(d,"dialog")).getButton(-1).performClick();assertEquals("https://manual:9443",selected.get());});
            selected.set(null);CountDownLatch entered=new CountDownLatch(1),late=new CountDownLatch(1);
            ui(()->{var d=new DiscoveryDialog(activity,selected::set,s->{entered.countDown();try{late.await(2,TimeUnit.SECONDS);}catch(InterruptedException ignored){}return outcome(false);});ref.set(d);d.show("https://saved:8443");((Button)field(d,"find")).performClick();});assertTrue(entered.await(1,TimeUnit.SECONDS));ui(()->ref.get().close());late.countDown();Thread.sleep(150);getInstrumentation().waitForIdleSync();
            ui(()->{assertEquals(0,((LinearLayout)field(ref.get(),"results")).getChildCount());assertTrue((boolean)field(ref.get(),"closed"));assertTrue(((ExecutorService)field(ref.get(),"worker")).isShutdown());});assertNull(selected.get());
        }finally{ui(()->{if(ref.get()!=null)ref.get().close();activity.finish();});}
    }
}
