package org.kiosk.harness.storage;

import android.content.res.AssetManager;
import java.io.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.kiosk.harness.core.LocalView;

/** Explicit native A/B install only. Startup/recovery does not construct this source. */
public final class FixtureAssetSource implements LocalView.Source {
    private final AssetManager assets;private final String prefix;
    private final Set<String> allowed;private final AtomicInteger reads;
    public FixtureAssetSource(AssetManager assets,PublicationFixtures.Fixture fixture,boolean view,AtomicInteger reads){
        this.assets=assets;this.reads=reads;
        prefix="publications/"+fixture.key()+"/"+(view?"view":"package");
        allowed=(view?fixture.viewFiles():fixture.packageFiles()).keySet();
    }
    public FixtureAssetSource(AssetManager assets,PublicationFixtures.Fixture fixture,String mode,AtomicInteger reads){
        this.assets=assets;this.reads=reads;
        prefix="publications/"+fixture.key()+"/"+(PublicationFixtures.mode(mode).equals("tv")?"view":"view-kiosk");
        allowed=PublicationFixtures.viewFiles(fixture,mode).keySet();
    }
    @Override public InputStream open(String name) throws IOException {
        if(!allowed.contains(name))throw new IOException("unknown_fixture_resource");
        reads.incrementAndGet();return assets.open(prefix+"/"+name,AssetManager.ACCESS_STREAMING);
    }
    @Override public Set<String> files() throws IOException {
        Set<String> result=new HashSet<>();Deque<String> directories=new ArrayDeque<>();directories.add("");int entries=0;
        while(!directories.isEmpty()){
            String dir=directories.remove();String[] children=assets.list(prefix+(dir.isEmpty()?"":"/"+dir));
            if(children==null)throw new IOException("fixture_inventory");
            for(String child:children){
                if(++entries>allowed.size()*4+16)throw new IOException("fixture_inventory");
                String name=dir.isEmpty()?child:dir+"/"+child;
                if(allowed.contains(name))result.add(name);
                else if(allowed.stream().anyMatch(p->p.startsWith(name+"/")))directories.add(name);
                else throw new IOException("fixture_inventory");
            }
        }
        return result;
    }
}
