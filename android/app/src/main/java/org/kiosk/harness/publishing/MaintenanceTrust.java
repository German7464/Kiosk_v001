package org.kiosk.harness.publishing;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.util.Collection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManagerFactory;
import org.kiosk.harness.core.LocalView;

/**
 * Pinned trust anchor for the native Maintenance HTTPS origin. Exactly one public CA
 * certificate PEM is accepted; a user-installed or system CA is never used for
 * /api/page/native routes. Hostname validation stays with the platform verifier.
 */
final class MaintenanceTrust {
    private MaintenanceTrust() {}

    /** Structural check: one X.509 certificate that is itself a CA. Validity is checked on use. */
    static X509Certificate certificate(String pem) throws IOException {
        if (pem == null || pem.isEmpty() || pem.length() > 16384) throw new IOException("native_page_ca");
        Collection<? extends java.security.cert.Certificate> certificates;
        try {
            certificates = CertificateFactory.getInstance("X.509")
                    .generateCertificates(new ByteArrayInputStream(pem.getBytes(StandardCharsets.US_ASCII)));
        } catch (Exception malformed) {
            throw new IOException("native_page_ca");
        }
        if (certificates.size() != 1) throw new IOException("native_page_ca");
        java.security.cert.Certificate certificate = certificates.iterator().next();
        if (!(certificate instanceof X509Certificate)) throw new IOException("native_page_ca");
        X509Certificate x509 = (X509Certificate) certificate;
        if (x509.getBasicConstraints() < 0) throw new IOException("native_page_ca");
        return x509;
    }

    /** Current public CA with a checked validity window. */
    static X509Certificate valid(String pem) throws IOException {
        X509Certificate certificate = certificate(pem);
        try {
            certificate.checkValidity();
        } catch (Exception invalid) {
            throw new IOException("native_page_ca_expired");
        }
        return certificate;
    }

    static SSLSocketFactory sockets(String pem) throws IOException {
        try {
            X509Certificate certificate = valid(pem);
            KeyStore anchors = KeyStore.getInstance(KeyStore.getDefaultType());
            anchors.load(null);
            anchors.setCertificateEntry("maintenance", certificate);
            TrustManagerFactory managers =
                    TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
            managers.init(anchors);
            SSLContext context = SSLContext.getInstance("TLS");
            context.init(null, managers.getTrustManagers(), null);
            return context.getSocketFactory();
        } catch (IOException refused) {
            throw refused;
        } catch (Exception failure) {
            throw new IOException("native_page_ca");
        }
    }

    /** SHA-256 of the DER certificate, for independent operator comparison. */
    static String fingerprint(String pem) throws IOException {
        try {
            return LocalView.digest(valid(pem).getEncoded());
        } catch (IOException refused) {
            throw refused;
        } catch (Exception failure) {
            throw new IOException("native_page_ca");
        }
    }
}
