package org.kiosk.harness.publishing;

import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.delivery.PageReleaseProtocol;
import static org.kiosk.harness.delivery.DeliveryProtocol.need;
import static org.kiosk.harness.delivery.DeliveryProtocol.refuse;

/**
 * Native Stage 6 handoff rules: exact ticket token, per-target package routes and
 * an explicit review gate. The token is only ever placed in an Authorization
 * header; no route, body or diagnostic contains it.
 */
final class NativePageProtocol {
    static final String OPEN_PATH = "/api/page/native/open";
    static final String APPROVE_PATH = "/api/page/native/approve";
    static final String PACKAGE_PREFIX = "/api/page/native/package/";
    private static final int MAX_ORIGIN = 255;
    private static final Set<String> HANDOFF_KEYS = Set.of(
            "version", "token", "expires", "content_origin", "maintenance_origin");

    /** Exact reviewed handoff fragment; the ticket token is never part of a URL. */
    record Handoff(String token, String contentOrigin, String maintenanceOrigin, long expires) {}

    private NativePageProtocol() {}

    static String token(String value) throws IOException {
        if (value == null || !value.matches("[a-f0-9]{64}")) refuse("native_page_token");
        return value;
    }

    /**
     * Strict native handoff: only /page, version=1, the five known keys and a
     * currently unexpired ticket. Unknown keys, duplicates and stale tickets
     * are refused before any signature or network request.
     */
    static Handoff handoff(Map<String,String> fragment, long now) throws IOException {
        if (fragment == null || !fragment.keySet().equals(HANDOFF_KEYS)) refuse("native_page_handoff");
        if (!"1".equals(fragment.get("version"))) refuse("native_page_version");
        String expires = fragment.get("expires");
        if (expires == null || !expires.matches("[0-9]{1,12}")) refuse("native_page_expires");
        long at = Long.parseLong(expires);
        if (at <= now) refuse("native_page_expired");
        String token = token(fragment.get("token"));
        String contentOrigin = fragment.get("content_origin");
        String maintenanceOrigin = fragment.get("maintenance_origin");
        origin(contentOrigin);
        origin(maintenanceOrigin);
        return new Handoff(token, contentOrigin, maintenanceOrigin, at);
    }

    static void origin(String value) throws IOException {
        if (value == null || value.isEmpty() || value.length() > MAX_ORIGIN
                || !value.chars().allMatch(character -> character < 128)) {
            refuse("native_page_origin");
        }
        try {
            URI uri = new URI(value);
            need("https".equals(uri.getScheme()) && uri.getHost() != null && uri.getPort() > 0
                    && uri.getRawUserInfo() == null && uri.getRawQuery() == null
                    && uri.getRawFragment() == null && "".equals(uri.getRawPath())
                    && value.equals("https://" + uri.getHost() + ":" + uri.getPort()));
        } catch (IOException refused) {
            throw refused;
        } catch (Exception malformed) {
            refuse("native_page_origin");
        }
    }

    /** Exact v1 page-review-open value; the server revalidates both origins. */
    static Map<String,Object> openValue(String token, String contentOrigin, String maintenanceOrigin)
            throws IOException {
        token(token);
        origin(contentOrigin);
        origin(maintenanceOrigin);
        Map<String,Object> value = new LinkedHashMap<>();
        value.put("content_origin", contentOrigin);
        value.put("maintenance_origin", maintenanceOrigin);
        value.put("token_sha256", LocalView.digest(token.getBytes(StandardCharsets.US_ASCII)));
        return value;
    }

    /** Distinct signed-package route per target device and exact reviewed file. */
    static String packageRoute(String deviceId, String path) throws IOException {
        if (deviceId == null || !deviceId.matches("[A-Za-z0-9_.-]{1,128}")
                || deviceId.equals(".") || deviceId.equals(".."))
            refuse("native_page_device");
        try {
            need(PageReleaseProtocol.safePath(path));
            return PACKAGE_PREFIX + CandidateClient.encodePath(deviceId) + "/"
                    + CandidateClient.encodePath(path);
        } catch (IOException refused) {
            throw refused;
        } catch (Exception malformed) {
            refuse("native_page_path");
            return "";
        }
    }

    static String authorization(String token) throws IOException {
        return "Bearer " + token(token);
    }

    /** Live-session retry: an exact stored approval needs the in-memory ticket. */
    static String retryTicket(String token) throws IOException {
        if (token == null) refuse("native_page_ticket_required");
        return token(token);
    }

    static Map<String,Object> openBody(Map<String,Object> approval, List<Object> chain)
            throws IOException {
        if (approval == null || chain == null || chain.isEmpty()) refuse("native_page_open");
        Map<String,Object> body = new LinkedHashMap<>();
        body.put("approval", approval);
        body.put("chain", chain);
        return body;
    }

    /** A release body exists only after explicit native consent. */
    static Map<String,Object> approveBody(String id, Map<String,Object> approval,
            List<Object> chain, boolean consent) throws IOException {
        if (!consent) refuse("native_page_consent");
        if (id == null || !id.matches("[a-f0-9]{64}") || approval == null
                || chain == null || chain.isEmpty()) {
            refuse("native_page_approve");
        }
        Map<String,Object> body = new LinkedHashMap<>();
        body.put("id", id);
        body.put("approval", approval);
        body.put("chain", chain);
        return body;
    }
}
