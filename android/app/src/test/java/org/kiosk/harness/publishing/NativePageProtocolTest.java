package org.kiosk.harness.publishing;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.junit.Test;
import org.kiosk.harness.core.LocalView;
import static org.junit.Assert.*;

public class NativePageProtocolTest {
    private static final String TOKEN = "0123456789abcdef".repeat(4);
    private static final String CONTENT = "https://content.example:443";
    private static final String MAINTENANCE = "https://maintenance.example:443";

    private static Map<String,Object> approval() {
        Map<String,Object> value = new LinkedHashMap<>();
        value.put("payload", "payload");
        value.put("signature", "signature");
        return value;
    }

    private static List<Object> chain() {
        return new ArrayList<>(List.of(Map.of("payload", "grant")));
    }

    private static Map<String,String> handoff(String version, String expires) {
        Map<String,String> fragment = new LinkedHashMap<>();
        fragment.put("version", version);
        fragment.put("token", TOKEN);
        fragment.put("expires", expires);
        fragment.put("content_origin", CONTENT);
        fragment.put("maintenance_origin", MAINTENANCE);
        return fragment;
    }

    @Test public void tokenIsOnlyHashedIntoOpenAndSentAsBearer() throws Exception {
        Map<String,Object> value = NativePageProtocol.openValue(TOKEN, CONTENT, MAINTENANCE);
        assertEquals(LocalView.digest(TOKEN.getBytes(StandardCharsets.US_ASCII)), value.get("token_sha256"));
        assertNotEquals(TOKEN, value.get("token_sha256"));
        assertEquals(CONTENT, value.get("content_origin"));
        assertEquals(MAINTENANCE, value.get("maintenance_origin"));
        String tokenHash = LocalView.digest(TOKEN.getBytes(StandardCharsets.US_ASCII));
        assertEquals("{\"content_origin\":\"https://content.example:443\","
                + "\"maintenance_origin\":\"https://maintenance.example:443\","
                + "\"token_sha256\":\"" + tokenHash + "\"}",
                new String(PublisherAuthority.canonical(value), StandardCharsets.US_ASCII));
        assertEquals("Bearer " + TOKEN, NativePageProtocol.authorization(TOKEN));
        assertFalse(NativePageProtocol.authorization(TOKEN).contains("/"));
    }

    @Test public void packageRoutesAreDistinctPerTargetAndExactFile() throws Exception {
        String first = NativePageProtocol.packageRoute("screen-a", "data/page-release.json");
        String second = NativePageProtocol.packageRoute("screen-b", "data/page-release.json");
        assertEquals("/api/page/native/package/screen-a/data/page-release.json", first);
        assertNotEquals(first, second);
        assertNotEquals(NativePageProtocol.packageRoute("screen-a", "static/uploads/a.png"),
                NativePageProtocol.packageRoute("screen-a", "static/uploads/b.png"));
        assertFalse(first.contains(TOKEN));
        assertThrows(IOException.class,
                () -> NativePageProtocol.packageRoute("screen-a", "../data/page-release.json"));
        assertThrows(IOException.class,
                () -> NativePageProtocol.packageRoute("screen-a", "data/page-release.json?raw=1"));
        assertThrows(IOException.class,
                () -> NativePageProtocol.packageRoute("screen a", "data/page-release.json"));
    }

    @Test public void packageRoutePercentEncodesExactTargetPath() throws Exception {
        assertEquals("/api/page/native/package/screen-a/static/uploads/card%20one.png",
                NativePageProtocol.packageRoute("screen-a", "static/uploads/card one.png"));
        assertEquals("/api/page/native/package/screen-a/static/uploads/caf%C3%A9.png",
                NativePageProtocol.packageRoute("screen-a", "static/uploads/café.png"));
    }

    @Test public void openValueRequiresStrictLowercaseTokenAndExactHttpsOrigins() {
        assertThrows(IOException.class, () -> NativePageProtocol.openValue("A".repeat(64), CONTENT, MAINTENANCE));
        assertThrows(IOException.class, () -> NativePageProtocol.openValue(TOKEN, "http://content.example:443", MAINTENANCE));
        assertThrows(IOException.class, () -> NativePageProtocol.openValue(TOKEN, CONTENT, "https://maintenance.example"));
        assertThrows(IOException.class, () -> NativePageProtocol.openValue(TOKEN, CONTENT + "/path", MAINTENANCE));
        assertThrows(IOException.class, () -> NativePageProtocol.openValue(TOKEN, CONTENT, MAINTENANCE + "?x=1"));
    }

    @Test public void handoffIsExactlyPageVersionOneUnexpiredAndKnownKeys() throws Exception {
        NativePageProtocol.Handoff valid = NativePageProtocol.handoff(handoff("1", "2000"), 1000);
        assertEquals(TOKEN, valid.token());
        assertEquals(CONTENT, valid.contentOrigin());
        assertEquals(MAINTENANCE, valid.maintenanceOrigin());
        assertEquals(2000, valid.expires());

        assertThrows(IOException.class, () -> NativePageProtocol.handoff(handoff("2", "2000"), 1000));
        Map<String,String> noVersion = handoff("1", "2000");
        noVersion.remove("version");
        assertThrows(IOException.class, () -> NativePageProtocol.handoff(noVersion, 1000));
        Map<String,String> unknown = handoff("1", "2000");
        unknown.put("extra", "1");
        assertThrows(IOException.class, () -> NativePageProtocol.handoff(unknown, 1000));
        assertThrows(IOException.class, () -> NativePageProtocol.handoff(handoff("1", "1000"), 1000));
        assertThrows(IOException.class, () -> NativePageProtocol.handoff(handoff("1", "soon"), 1000));
        Map<String,String> upper = handoff("1", "2000");
        upper.put("token", "A".repeat(64));
        assertThrows(IOException.class, () -> NativePageProtocol.handoff(upper, 1000));
    }

    @Test public void retryRequiresLiveInMemoryTicket() throws Exception {
        assertThrows(IOException.class, () -> NativePageProtocol.retryTicket(null));
        assertEquals(TOKEN, NativePageProtocol.retryTicket(TOKEN));
    }

    @Test public void packageRouteRejectsDotSegments() {
        assertThrows(IOException.class,
                () -> NativePageProtocol.packageRoute(".", "data/page-release.json"));
        assertThrows(IOException.class,
                () -> NativePageProtocol.packageRoute("..", "data/page-release.json"));
    }

    @Test public void publishBodyNeedsExplicitConsentAndExactPlan() throws Exception {
        String identity = "a".repeat(64);
        assertThrows(IOException.class,
                () -> NativePageProtocol.approveBody(identity, approval(), chain(), false));
        Map<String,Object> body = NativePageProtocol.approveBody(identity, approval(), chain(), true);
        assertEquals(identity, body.get("id"));
        assertEquals(approval(), body.get("approval"));
        assertEquals(chain(), body.get("chain"));
        assertThrows(IOException.class,
                () -> NativePageProtocol.approveBody("not-a-plan", approval(), chain(), true));
        assertThrows(IOException.class,
                () -> NativePageProtocol.approveBody(identity, approval(), List.of(), true));
    }
}
