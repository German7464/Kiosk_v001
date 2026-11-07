package org.kiosk.harness.storage;

import android.graphics.*;
import android.os.*;
import java.io.*;
import java.util.*;
import org.kiosk.harness.core.LocalView;

/** Sequential candidate PNG/JPEG readability checks, not Pillow equivalence or a hard native timeout. */
final class AndroidImageValidation {
    static void verify(LocalView.Source source,PreparedAdmission.Request r,Set<String> names,FixturePublicationStore.Checkpoint cancel)throws Exception {
        try{verifyImages(source,r,names,cancel);}catch(OutOfMemoryError|ArithmeticException exhausted){throw new IOException("image_resource_refused");}
    }
    private static void verifyImages(LocalView.Source source,PreparedAdmission.Request r,Set<String> names,FixturePublicationStore.Checkpoint cancel)throws Exception {
        if(Looper.myLooper()==Looper.getMainLooper())throw new IOException("image_check_on_ui_thread");
        long start=SystemClock.elapsedRealtime();
        for(String name:names){
            long imageStart=SystemClock.elapsedRealtime();check(start,imageStart,r.images(),cancel);
            long size=r.pkg().files().get(name).size();if(size<0||size>=r.images().maxLiveBytes()||size>Integer.MAX_VALUE)throw new IOException("image_budget_exceeded");
            // Exact preallocated buffer avoids an unaccounted grow/copy of ByteArrayOutputStream.
            byte[] bytes=new byte[(int)size];int at=0;
            try(InputStream in=source.open(name)){while(at<bytes.length){check(start,imageStart,r.images(),cancel);int n=in.read(bytes,at,Math.min(16384,bytes.length-at));if(n<=0)throw new IOException("image_bytes_changed");at+=n;}if(in.read()!=-1)throw new IOException("image_bytes_changed");}
            if(!LocalView.digest(bytes).equals(r.windowsImages().get(name).sha256()))throw new IOException("windows_bytes_mismatch");
            boolean png=bytes.length>=8&&Arrays.equals(Arrays.copyOf(bytes,8),new byte[]{(byte)137,80,78,71,13,10,26,10});
            boolean jpeg=bytes.length>=3&&(bytes[0]&255)==255&&(bytes[1]&255)==216&&(bytes[2]&255)==255;
            if(!png&&!jpeg)throw new IOException("image_profile_unsupported");
            BitmapFactory.Options bounds=new BitmapFactory.Options();bounds.inJustDecodeBounds=true;bounds.inScaled=false;BitmapFactory.decodeByteArray(bytes,0,bytes.length,bounds);
            if(!(png?"image/png":"image/jpeg").equals(bounds.outMimeType))throw new IOException("image_bounds_failed");
            r.images().estimatedLive(bounds.outWidth,bounds.outHeight,size);check(start,imageStart,r.images(),cancel);
            Bitmap bitmap=null;
            try{
                BitmapFactory.Options options=new BitmapFactory.Options();options.inScaled=false;options.inPreferredConfig=Bitmap.Config.ARGB_8888;
                bitmap=BitmapFactory.decodeByteArray(bytes,0,bytes.length,options);
                if(bitmap==null||bitmap.getWidth()!=bounds.outWidth||bitmap.getHeight()!=bounds.outHeight)throw new IOException("image_decode_failed");
                if(Math.addExact(size,(long)bitmap.getAllocationByteCount())>r.images().maxLiveBytes())throw new IOException("image_budget_exceeded");
                check(start,imageStart,r.images(),cancel);
            }finally{if(bitmap!=null)bitmap.recycle();}
        }
    }
    private static void check(long start,long image,PreparedAdmission.ImageBudget budget,FixturePublicationStore.Checkpoint cancel)throws IOException {
        cancel.hit("admission.image_chunk");if(Thread.currentThread().isInterrupted())throw new IOException("operation_cancelled");
        long now=SystemClock.elapsedRealtime();if(now-start>budget.totalMillis()||now-image>budget.perImageMillis())throw new IOException("image_deadline_exceeded");
    }
}
