package org.kiosk.harness.admin;

import java.net.URI;
import java.util.Locale;

/**
 * Exact-origin policy for the administrative WebView. Only the configured HTTPS
 * origin (explicit host and port) may be navigated or loaded as a resource; all
 * other schemes, hosts, ports, user info and cleartext destinations are refused.
 */
public final class AdminNavigationPolicy {
    private final String origin;
    private final String host;
    private final int port;

    public AdminNavigationPolicy(String value) {
        URI uri = parse(value);
        if (uri == null || !"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null
                || uri.getPort() <= 0 || uri.getPort() > 65535
                || uri.getRawUserInfo() != null || uri.getRawQuery() != null || uri.getRawFragment() != null
                || (uri.getRawPath() != null && !uri.getRawPath().isEmpty())) {
            throw new IllegalArgumentException("unsafe_admin_origin");
        }
        host = uri.getHost().toLowerCase(Locale.ROOT);
        port = uri.getPort();
        origin = "https://" + host + ":" + port;
    }

    public String origin() {
        return origin;
    }

    /** True when a main-frame navigation may proceed. Query and fragment are allowed on the exact origin. */
    public boolean navigation(String url) {
        return sameOrigin(url);
    }

    /** True when a page subresource (script, style, image, fetch) may be loaded. */
    public boolean resource(String url) {
        return sameOrigin(url);
    }

    private boolean sameOrigin(String url) {
        URI uri = parse(url);
        return uri != null && "https".equalsIgnoreCase(uri.getScheme()) && uri.getHost() != null
                && uri.getRawUserInfo() == null && uri.getPort() == port
                && host.equals(uri.getHost().toLowerCase(Locale.ROOT));
    }

    /** Path of an already accepted same-origin URL, or empty. Never used to bypass validation. */
    public String path(String url) {
        if (!sameOrigin(url)) {
            return "";
        }
        String path = parse(url).getRawPath();
        return path == null ? "" : path;
    }

    public boolean isLogin(String url) {
        return sameOrigin(url) && path(url).startsWith("/admin/login");
    }

    private static URI parse(String value) {
        if (value == null || value.isEmpty() || value.indexOf('\r') >= 0 || value.indexOf('\n') >= 0) {
            return null;
        }
        try {
            return new URI(value);
        } catch (Exception invalid) {
            return null;
        }
    }
}
