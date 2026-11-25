package org.kiosk.harness.publishing;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import org.junit.Test;
import org.kiosk.harness.core.LocalView;
import static org.junit.Assert.*;

public class MaintenanceTrustTest {
    private static String pem(String name) throws Exception {
        try (InputStream stream = MaintenanceTrustTest.class.getResourceAsStream("/stage6/" + name)) {
            if (stream == null) throw new IOException("stage6_fixture_missing");
            return new String(stream.readAllBytes(), StandardCharsets.US_ASCII);
        }
    }

    @Test public void acceptsExactlyOnePublicCaAndPinsIt() throws Exception {
        String ca = pem("maintenance-ca.pem");
        assertEquals(LocalView.digest(MaintenanceTrust.certificate(ca).getEncoded()),
                MaintenanceTrust.fingerprint(ca));
        assertNotNull(MaintenanceTrust.sockets(ca));
    }

    @Test public void refusesLeafMalformedAndMultipleCertificates() throws Exception {
        assertEquals("native_page_ca",
                refused(() -> MaintenanceTrust.certificate(pem("maintenance-leaf.pem"))));
        assertEquals("native_page_ca",
                refused(() -> MaintenanceTrust.certificate("not a certificate")));
        String ca = pem("maintenance-ca.pem");
        assertEquals("native_page_ca",
                refused(() -> MaintenanceTrust.certificate(ca + "\n" + ca)));
    }

    private static String refused(Throwing action) throws Exception {
        try {
            action.run();
            fail("accepted an untrusted Maintenance CA");
            return "";
        } catch (IOException failure) {
            return failure.getMessage();
        }
    }

    private interface Throwing {
        void run() throws Exception;
    }
}
