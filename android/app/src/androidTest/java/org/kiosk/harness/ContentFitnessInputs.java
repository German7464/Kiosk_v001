package org.kiosk.harness;
import android.content.Context;
import java.util.*;
import org.kiosk.harness.binding.FitnessInputs;
import org.kiosk.harness.core.LocalView;
final class ContentFitnessInputs {
    static Map<String,byte[]> load(Context context,String name)throws Exception{if(!FitnessInputs.NAMES.contains(name))throw new IllegalArgumentException();Map<String,byte[]> out=new HashMap<>();collect(context,"content-fitness/"+name,"",out);return out;}
    private static void collect(Context c,String root,String rel,Map<String,byte[]> out)throws Exception{String[] children=c.getAssets().list(root);if(children.length==0){out.put(rel,LocalView.readBounded(c.getAssets().open(root),2L*1024*1024));return;}for(String child:children)collect(c,root+"/"+child,rel.isEmpty()?child:rel+"/"+child,out);}
}
