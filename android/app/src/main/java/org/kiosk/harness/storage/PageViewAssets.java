package org.kiosk.harness.storage;

import android.content.res.AssetManager;
import java.io.*;
import java.util.*;
import org.kiosk.harness.core.LocalView;

/** Fixed shipped page renderer/bootstrap assets; never package supplied. */
final class PageViewAssets implements LocalView.Source {
    static final String PREFIX="views/pages-v1";
    static final Set<String> FILES=Set.of("bootstrap.html","bootstrap.js","page_display.js","page_display.css");
    private final AssetManager assets;
    PageViewAssets(AssetManager assets){this.assets=assets;}
    @Override public InputStream open(String name)throws IOException{
        if(!FILES.contains(name))throw new IOException("unknown_page_renderer_asset");
        return assets.open(PREFIX+"/"+name,AssetManager.ACCESS_STREAMING);
    }
    @Override public Set<String> files()throws IOException{
        Set<String> result=new HashSet<>();
        String[] children=assets.list(PREFIX);
        if(children==null)throw new IOException("page_renderer_inventory");
        for(String child:children)if(FILES.contains(child))result.add(child);
        if(!result.equals(FILES))throw new IOException("page_renderer_inventory");
        return result;
    }
}
