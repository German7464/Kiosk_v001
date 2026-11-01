package org.kiosk.harness.core;

import java.net.URI;

public final class OriginPolicy {
    public static final String ORIGIN = "https://kiosk.invalid";
    public static final String INDEX = ORIGIN + "/index.html";
    private final LocalView view;
    public OriginPolicy(LocalView view) { this.view = view; }
    public String resource(String url, String method) {
        try {
            URI uri = new URI(url);
            String raw = uri.getRawPath() == null ? "" : uri.getRawPath().toLowerCase(java.util.Locale.ROOT);
            if (raw.contains("%2f") || raw.contains("%5c") || raw.contains("%25")) return null;
            if (!"GET".equals(method) || !"https".equals(uri.getScheme()) || !"kiosk.invalid".equals(uri.getHost())
                || (uri.getPort() != -1 && uri.getPort() != 443) || uri.getRawUserInfo() != null
                || uri.getRawQuery() != null || uri.getRawFragment() != null) return null;
            String path = uri.getPath();
            if (path == null || !path.startsWith("/")) return null;
            path = path.substring(1);
            return LocalView.safePath(path) && view.contains(path) ? path : null;
        } catch (Exception e) { return null; }
    }
    public boolean navigate(String url, String method, boolean mainFrame) {
        return mainFrame && "index.html".equals(resource(url, method));
    }
}
