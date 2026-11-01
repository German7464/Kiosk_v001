package org.kiosk.harness.binding;
import android.test.InstrumentationTestCase;
import android.content.res.AssetManager;
import java.util.*;
import org.kiosk.harness.core.LocalView;
/** Parser/core checks only: no Activity, WebView, store or publication operation. */
@SuppressWarnings("deprecation")
public class PublicationBindingAndroidTest extends InstrumentationTestCase {
    private void collect(AssetManager a,String path,String rel,Map<String,byte[]> all)throws Exception{
        String[] children=a.list(path);
        if(children.length==0){all.put(rel,LocalView.readBounded(a.open(path),2L*1024*1024));return;}
        for(String child:children)collect(a,path+"/"+child,rel.isEmpty()?child:rel+"/"+child,all);
    }
    private Map<String,byte[]> load()throws Exception{Map<String,byte[]> all=new HashMap<>();collect(getInstrumentation().getContext().getAssets(),"generic-binding","",all);return all;}
    public void testCanonicalCOutsideCatalog()throws Exception{BindingVectors.valid(this::load);}
    public void testIndependentWitnessMismatches()throws Exception{BindingVectors.witnesses(this::load);}
    public void testInventoryDescriptorAndPayloadTampering()throws Exception{BindingVectors.inventoryAndTampering(this::load);}
    public void testBoundedStreamsAndClosure()throws Exception{BindingVectors.streams(this::load);}
    public void testChangedRereads()throws Exception{BindingVectors.changedReread(this::load);}
    public void testLifetimeAndNoWrites()throws Exception{BindingVectors.lifetimeAndNoWrites(this::load);}
}
