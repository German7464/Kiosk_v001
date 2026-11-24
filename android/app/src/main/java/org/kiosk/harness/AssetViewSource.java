package org.kiosk.harness;

import android.content.res.AssetManager;
import java.io.IOException;
import java.io.InputStream;
import java.util.HashSet;
import java.util.Set;
import org.kiosk.harness.core.LocalView;

/** APK assets are immutable ZIP entries: no filesystem links or mutable extraction tree. */
final class AssetViewSource implements LocalView.Source {
    private final AssetManager assets;
    private final String root;
    AssetViewSource(AssetManager assets, String fixture) {
        FixtureCatalog.mode(fixture);
        this.assets = assets;
        root = "views/" + fixture;
    }
    public InputStream open(String path) throws IOException {
        if (!LocalView.safePath(path)) throw new IOException("unsafe_asset");
        return assets.open(root + "/" + path, AssetManager.ACCESS_STREAMING);
    }
    public Set<String> files() throws IOException {
        Set<String> result = new HashSet<>();
        walk("", result, new int[]{0}, 0);
        return result;
    }
    private void walk(String path, Set<String> result, int[] count, int depth) throws IOException {
        if (++count[0] > 20001 || depth > 240) throw new IOException("asset_tree_limit");
        String[] children = assets.list(root + (path.isEmpty() ? "" : "/" + path));
        if (children == null) throw new IOException("invalid_asset_tree");
        if (children.length == 0) {
            try (InputStream ignored = open(path)) { result.add(path); }
        } else for (String name : children) {
            String child = path.isEmpty() ? name : path + "/" + name;
            if (!LocalView.safePath(child)) throw new IOException("unsafe_asset");
            walk(child, result, count, depth + 1);
        }
    }
}
