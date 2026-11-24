package org.kiosk.harness.admin;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/** Exact-origin refusals for the administration WebView; no Android dependency. */
public final class AdminNavigationPolicyTest {
    private static final String ORIGIN = "https://192.168.1.165:18543";
    private final AdminNavigationPolicy policy = new AdminNavigationPolicy(ORIGIN);

    @Test public void acceptsOnlyTheExactTrustedOrigin() {
        assertTrue(policy.navigation(ORIGIN + "/admin/devices/pair"));
        assertTrue(policy.navigation(ORIGIN + "/admin/login?next=pair"));
        assertTrue(policy.navigation(ORIGIN + "/admin/devices/pair#v=1&code=XEJUX8GN"));
        assertTrue(policy.resource(ORIGIN + "/static/admin.css"));
    }

    @Test public void refusesForeignHostsPortsAndSchemes() {
        assertFalse(policy.navigation("https://192.168.1.166:18543/admin"));
        assertFalse(policy.navigation("https://192.168.1.165:8443/admin"));
        assertFalse(policy.navigation("https://192.168.1.165/admin"));
        assertFalse(policy.navigation("https://sub.192.168.1.165:18543/admin"));
        assertFalse(policy.navigation("http://192.168.1.165:18543/admin"));
        assertFalse(policy.navigation("https://user@192.168.1.165:18543/admin"));
        assertFalse(policy.navigation("javascript:alert(1)"));
        assertFalse(policy.navigation("intent://192.168.1.165:18543/admin#Intent;end"));
        assertFalse(policy.navigation("file:///sdcard/admin.html"));
        assertFalse(policy.navigation("data:text/html,hello"));
        assertFalse(policy.navigation("about:blank"));
        assertFalse(policy.resource("https://example.com/app.js"));
    }

    @Test public void rejectsUnsafeConfiguredOrigins() {
        for (String unsafe : new String[]{
            "http://192.168.1.165:18543",
            "https://192.168.1.165",
            "https://192.168.1.165:0",
            "https://192.168.1.165:18543/admin",
            "https://192.168.1.165:18543?x=1",
            "https://user@192.168.1.165:18543",
            "https://192.168.1.165:18543#fragment",
            "https://",
            ""
        }) {
            try {
                new AdminNavigationPolicy(unsafe);
                throw new AssertionError("accepted unsafe origin: " + unsafe);
            } catch (IllegalArgumentException expected) {
                // expected refusal
            }
        }
    }

    @Test public void recognisesServerLoginRedirect() {
        assertTrue(policy.isLogin(ORIGIN + "/admin/login"));
        assertTrue(policy.isLogin(ORIGIN + "/admin/login?next=pair"));
        assertFalse(policy.isLogin(ORIGIN + "/admin/devices/pair"));
        assertEquals("/admin/devices/pair", policy.path(ORIGIN + "/admin/devices/pair"));
    }
}
