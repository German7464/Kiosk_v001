package org.kiosk.harness.admin;

import android.test.InstrumentationTestCase;
import android.webkit.SslErrorHandler;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import javax.net.ssl.KeyManagerFactory;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLServerSocket;

/**
 * Platform proof that the sandbox WebView uses the app network-security-config
 * trust anchors (a fixture CA absent from the user/system store) and still
 * rejects a different self-signed server without an SSL override.
 *
 * Test-only CA/keys live in androidTest assets; the sandbox certificate resource
 * is never part of the production configuration.
 */
@SuppressWarnings("deprecation")
public final class AdminTlsSandboxTest extends InstrumentationTestCase {
    private static final char[] PASSWORD = "changeit".toCharArray();

    public void testTrustedFixtureAnchorLoadsAndUntrustedCertificateIsRejected() throws Exception {
        try (SSLServerSocket trusted = server("admin-tls/trusted.p12")) {
            String trustedBody = "trusted fixture anchor";
            Thread trustedThread = serve(trusted, trustedBody);
            int trustedPort = trusted.getLocalPort();
            Result loaded = load("https://127.0.0.1:" + trustedPort + "/");
            assertTrue("trusted fixture page did not finish", loaded.finished.await(20, TimeUnit.SECONDS));
            assertEquals("trusted fixture produced an SSL error", 0, loaded.sslErrors.get());
            assertTrue("trusted fixture body missing: " + loaded.text.get(),
                loaded.text.get() != null && loaded.text.get().contains(trustedBody));
            trustedThread.join(5000);
        }

        try (SSLServerSocket untrusted = server("admin-tls/untrusted.p12")) {
            Thread untrustedThread = serve(untrusted, "untrusted fixture");
            int untrustedPort = untrusted.getLocalPort();
            Result rejected = load("https://127.0.0.1:" + untrustedPort + "/");
            assertTrue("untrusted certificate was not rejected",
                rejected.sslError.await(20, TimeUnit.SECONDS));
            assertTrue("untrusted certificate produced no SSL error", rejected.sslErrors.get() > 0);
            untrustedThread.join(5000);
        }
    }

    private SSLServerSocket server(String asset) throws Exception {
        KeyStore store = KeyStore.getInstance("PKCS12");
        try (InputStream in = getInstrumentation().getContext().getAssets().open(asset)) {
            store.load(in, PASSWORD);
        }
        KeyManagerFactory keys = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());
        keys.init(store, PASSWORD);
        SSLContext context = SSLContext.getInstance("TLS");
        context.init(keys.getKeyManagers(), null, null);
        SSLServerSocket socket = (SSLServerSocket) context.getServerSocketFactory()
            .createServerSocket(0, 1, InetAddress.getByName("127.0.0.1"));
        socket.setSoTimeout(20000);
        return socket;
    }

    private Thread serve(SSLServerSocket server, String body) {
        Thread thread = new Thread(() -> {
            try (Socket socket = server.accept()) {
                socket.setSoTimeout(10000);
                InputStream in = socket.getInputStream();
                ByteArrayOutputStream request = new ByteArrayOutputStream();
                int value;
                while ((value = in.read()) >= 0) {
                    request.write(value);
                    byte[] bytes = request.toByteArray();
                    int length = bytes.length;
                    if (length >= 4 && bytes[length - 4] == '\r' && bytes[length - 3] == '\n'
                        && bytes[length - 2] == '\r' && bytes[length - 1] == '\n') {
                        break;
                    }
                }
                byte[] payload = body.getBytes(StandardCharsets.UTF_8);
                String headers = "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                    + "Content-Length: " + payload.length + "\r\nConnection: close\r\n\r\n";
                OutputStream out = socket.getOutputStream();
                out.write(headers.getBytes(StandardCharsets.US_ASCII));
                out.write(payload);
                out.flush();
            } catch (Exception ignored) {
                // The untrusted fixture may be aborted by WebView before a request is read.
            }
        }, "admin-tls-fixture");
        thread.setDaemon(true);
        thread.start();
        return thread;
    }

    private Result load(String url) throws Exception {
        Result result = new Result();
        getInstrumentation().runOnMainSync(() -> {
            WebView view = new WebView(getInstrumentation().getTargetContext());
            result.view.set(view);
            view.getSettings().setJavaScriptEnabled(true);
            view.setWebViewClient(new WebViewClient() {
                @Override public void onPageFinished(WebView web, String page) {
                    web.evaluateJavascript("document.body.textContent", value -> {
                        result.text.set(value);
                        result.finished.countDown();
                    });
                }
                @Override public void onReceivedSslError(WebView web, SslErrorHandler handler, android.net.http.SslError error) {
                    handler.cancel();
                    result.sslErrors.incrementAndGet();
                    result.sslError.countDown();
                    result.finished.countDown();
                }
            });
            view.loadUrl(url);
        });
        return result;
    }

    private static final class Result {
        final AtomicReference<WebView> view = new AtomicReference<>();
        final AtomicReference<String> text = new AtomicReference<>();
        final AtomicInteger sslErrors = new AtomicInteger();
        final CountDownLatch finished = new CountDownLatch(1);
        final CountDownLatch sslError = new CountDownLatch(1);
    }
}
