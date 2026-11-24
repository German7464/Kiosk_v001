package org.kiosk.harness.core;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/** Combined Windows LocalView/cache preflight for an immutable, build-delivered source. */
public final class LocalView {
    public interface Source {
        InputStream open(String path) throws IOException;
        Set<String> files() throws IOException;
    }
    public static final int DESCRIPTOR_LIMIT = 2 * 1024 * 1024;
    public static final long FILE_LIMIT = 64L * 1024 * 1024;
    public static final long TOTAL_LIMIT = 128L * 1024 * 1024;
    private final Source source;
    private final Map<String, Entry> inventory;
    public final String mode, packageIdentity;
    private static final class Entry {
        final long size;
        final String hash;
        Entry(long size, String hash) { this.size = size; this.hash = hash; }
    }
    private LocalView(Source source, Map<String, Entry> entries, String mode, String identity) {
        this.source = source;
        inventory = Collections.unmodifiableMap(entries);
        this.mode = mode;
        packageIdentity = identity;
    }
    public static LocalView verify(Source source, String expectedIdentity, String expectedMode,
                                   String trustedJs, String trustedCss) throws IOException {
        try {
            byte[] bytes = readBounded(source.open("view.json"), DESCRIPTOR_LIMIT);
            String json = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
            JsonSyntax.validate(json);
            JSONObject descriptor = new JSONObject(json);
            if (!integer(descriptor.get("schema_version")) || descriptor.getLong("schema_version") != 1
                || !"events-v1".equals(descriptor.get("renderer"))
                || !(descriptor.get("revision") instanceof String) || descriptor.getString("revision").isEmpty()
                || !("kiosk".equals(expectedMode) || "tv".equals(expectedMode))
                || !expectedMode.equals(descriptor.get("mode"))
                || !expectedIdentity.matches("[0-9a-f]{64}")
                || !expectedIdentity.equals(descriptor.get("package_sha256"))) throw failure();
            JSONArray files = descriptor.getJSONArray("files");
            if (files.length() < 3 || files.length() > 10000) throw failure();
            Map<String, Entry> entries = new HashMap<>();
            Set<String> portable = new HashSet<>();
            long total = 0;
            for (int i = 0; i < files.length(); i++) {
                JSONObject item = files.getJSONObject(i);
                if (item.length() != 3 || !(item.get("path") instanceof String)
                    || !integer(item.get("size")) || !(item.get("sha256") instanceof String)) throw failure();
                String path = item.getString("path"), hash = item.getString("sha256");
                long size = item.getLong("size");
                if (!safePath(path) || mime(path) == null || !portable.add(path.toLowerCase(Locale.ROOT))
                    || size < 0 || size > FILE_LIMIT || total > TOTAL_LIMIT - size
                    || !hash.matches("[0-9a-f]{64}")) throw failure();
                total += size;
                entries.put(path, new Entry(size, hash));
            }
            if (!entries.keySet().containsAll(Set.of("index.html", "events.js", "events.css"))
                || !entries.get("events.js").hash.equals(trustedJs)
                || !entries.get("events.css").hash.equals(trustedCss)) throw failure();
            Set<String> exact = new HashSet<>(entries.keySet());
            exact.add("view.json");
            if (!exact.equals(source.files())) throw failure();
            LocalView view = new LocalView(source, entries, expectedMode, expectedIdentity);
            for (String path : entries.keySet()) view.read(path);
            return view;
        } catch (IOException e) { throw failure(); }
        catch (Exception e) { throw failure(); }
    }
    private static boolean integer(Object value) { return value instanceof Integer || value instanceof Long; }
    public boolean contains(String path) { return inventory.containsKey(path); }
    public byte[] read(String path) throws IOException {
        Entry entry = inventory.get(path);
        if (entry == null) throw failure();
        byte[] bytes = readBounded(source.open(path), entry.size);
        if (bytes.length != entry.size || !digest(bytes).equals(entry.hash)) throw failure();
        return bytes;
    }
    public static byte[] readBounded(InputStream stream, long limit) throws IOException {
        try (InputStream input = stream; ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] block = new byte[16384];
            long total = 0;
            int count;
            while ((count = input.read(block)) != -1) {
                if (count == 0) throw failure();
                total += count;
                if (total > limit) throw failure();
                out.write(block, 0, count);
            }
            return out.toByteArray();
        }
    }
    public static String digest(byte[] bytes) {
        try {
            StringBuilder result = new StringBuilder();
            for (byte b : MessageDigest.getInstance("SHA-256").digest(bytes))
                result.append(String.format(Locale.ROOT, "%02x", b & 255));
            return result.toString();
        } catch (Exception e) { throw new IllegalStateException(e); }
    }
    public static boolean safePath(String value) {
        if (value == null || value.isEmpty() || value.contains("\\") || value.contains(":")) return false;
        for (String part : value.split("/", -1))
            if (part.isEmpty() || part.equals(".") || part.equals("..") || part.endsWith(".") || part.endsWith(" ")) return false;
        return true;
    }
    public static String mime(String path) {
        if (path.equals("index.html")) return "text/html";
        if (path.equals("events.js")) return "text/javascript";
        if (path.equals("events.css")) return "text/css";
        if (!path.startsWith("static/uploads/")) return null;
        int dot = path.lastIndexOf('.');
        if (dot < 0) return null;
        switch (path.substring(dot).toLowerCase(Locale.ROOT)) {
            case ".jpg": case ".jpeg": return "image/jpeg";
            case ".png": return "image/png";
            case ".webp": return "image/webp";
            case ".gif": return "image/gif";
            case ".bmp": return "image/bmp";
            case ".ico": return "image/x-icon";
            default: return null;
        }
    }
    private static IOException failure() { return new IOException("invalid_local_view"); }
}
