package org.kiosk.harness.publishing;

import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import java.security.KeyPairGenerator;
import java.security.KeyStore;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.Signature;

/**
 * Android Keystore RSA3072 publisher key. Generated non-exportable inside the
 * hardware/software-backed AndroidKeyStore; there is no portable recovery copy.
 * A lost device requires revocation plus a fresh independently authorized key.
 */
public final class KeystorePublisherKey implements PublisherKey {
    private static final String ALIAS = "kiosk-publisher-v1";
    private final PrivateKey privateKey;
    private final PublicKey publicKey;

    private KeystorePublisherKey(PrivateKey privateKey, PublicKey publicKey) {
        this.privateKey = privateKey;
        this.publicKey = publicKey;
    }

    public static KeystorePublisherKey open() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(ALIAS)) {
            KeyPairGenerator generator = KeyPairGenerator.getInstance(
                    KeyProperties.KEY_ALGORITHM_RSA, "AndroidKeyStore");
            generator.initialize(new KeyGenParameterSpec.Builder(ALIAS,
                    KeyProperties.PURPOSE_SIGN | KeyProperties.PURPOSE_VERIFY)
                    .setKeySize(3072)
                    .setDigests(KeyProperties.DIGEST_SHA256)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setSignaturePaddings(KeyProperties.SIGNATURE_PADDING_RSA_PKCS1)
                    .build());
            generator.generateKeyPair();
        }
        KeyStore.Entry entry = store.getEntry(ALIAS, null);
        if (!(entry instanceof KeyStore.PrivateKeyEntry)) {
            throw new IllegalStateException("publisher_keystore_entry_refused");
        }
        KeyStore.PrivateKeyEntry stored = (KeyStore.PrivateKeyEntry) entry;
        return new KeystorePublisherKey(stored.getPrivateKey(),
                stored.getCertificate().getPublicKey());
    }

    @Override public PublicKey publicKey() { return publicKey; }

    @Override public byte[] sign(byte[] domain, byte[] payload) throws Exception {
        Signature signature = Signature.getInstance("SHA256withRSA");
        signature.initSign(privateKey);
        signature.update(domain);
        signature.update(payload);
        return signature.sign();
    }

    @Override public String label() { return "android-keystore:" + ALIAS; }
}
