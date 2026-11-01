package org.kiosk.harness;
import android.content.Context;
import android.content.res.AssetManager;
import java.util.*;
import java.io.*;
import org.kiosk.harness.binding.*;
import org.kiosk.harness.core.LocalView;
final class GenericInputs {
    static final CapturedCandidate.Budget BUDGET=new CapturedCandidate.Budget(8L*1024*1024,100,1024);
    static PlaybackInputs.Owned capture(Context target,Context tests,String name)throws Exception{
        return PlaybackInputs.capture(target,()->load(tests.getAssets(),name));
    }
    static Map<String,byte[]> load(AssetManager a,String name)throws Exception{
        Map<String,byte[]> all=new HashMap<>();collect(a,name.equals("C")?"generic-binding":"generic-playback/B","",all);return all;
    }
    private static void collect(AssetManager a,String folder,String rel,Map<String,byte[]> all)throws Exception{
        String[] children=a.list(folder);if(children.length==0){all.put(rel,LocalView.readBounded(a.open(folder),2L*1024*1024));return;}
        for(String c:children)collect(a,folder+"/"+c,rel.isEmpty()?c:rel+"/"+c,all);
    }
}
