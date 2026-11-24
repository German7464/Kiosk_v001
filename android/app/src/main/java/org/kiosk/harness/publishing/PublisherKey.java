package org.kiosk.harness.publishing;

import java.security.PublicKey;

/** Device-bound publisher signing key. Private bytes never leave the platform store. */
public interface PublisherKey {
    PublicKey publicKey() throws Exception;
    byte[] sign(byte[] domain, byte[] payload) throws Exception;
    String label();
}
