package org.kiosk.harness.admin;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.provider.Settings;
import android.widget.EditText;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;

/** Supported Android 11+ Settings flow, with no install privilege or TLS bypass. */
final class CaSetup {
    static final int SAVE_CA = 7314;
    private final Activity activity;
    private byte[] pending;

    CaSetup(Activity activity) { this.activity=activity; }

    void begin(String publicPem, String origin) {
        try {
            if(publicPem.length()>16384)throw new IllegalArgumentException();
            X509Certificate cert=(X509Certificate)CertificateFactory.getInstance("X.509")
                .generateCertificate(new ByteArrayInputStream(publicPem.getBytes(StandardCharsets.US_ASCII)));
            if(cert.getBasicConstraints()<0)throw new IllegalArgumentException();
            cert.checkValidity();
            byte[] der=cert.getEncoded();
            StringBuilder hex=new StringBuilder();
            for(byte b:MessageDigest.getInstance("SHA-256").digest(der))hex.append(String.format(java.util.Locale.ROOT,"%02x",b&255));
            String fingerprint=hex.toString();
            EditText expected=new EditText(activity);
            expected.setSingleLine(true);
            expected.setHint("SHA256 from the administrator, 64 hex characters");
            new AlertDialog.Builder(activity).setTitle("Authenticate this installation CA")
                .setMessage(origin+"\n\nCA SHA256:\n"+fingerprint+"\n\nCompare with the administrator through an independent trusted channel. "
                    +"Enter that independently obtained fingerprint below. A server download alone is not authentication. "
                    +"Android will trust this CA at user scope; apps opting into user CAs may also trust it.")
                .setView(expected).setNegativeButton("Cancel",null)
                .setPositiveButton("Install with Android",(d,w)->{
                    String value=expected.getText().toString().replace(":","").replace(" ","").trim().toLowerCase(java.util.Locale.ROOT);
                    if(!value.equals(fingerprint)){error("Fingerprint does not match. Nothing was installed.");return;}
                    try {
                        Intent install=android.security.KeyChain.createInstallIntent();
                        install.putExtra(android.security.KeyChain.EXTRA_CERTIFICATE,der);
                        install.putExtra(android.security.KeyChain.EXTRA_NAME,"Kiosk campaign CA");
                        activity.startActivity(install);
                    } catch(Exception failure) {
                        error("Android certificate installer is unavailable. Existing trust was not changed.");
                    }
                }).show();
        } catch(Exception failure) { error("Confirmed public CA is unavailable or invalid. Existing trust was not changed."); }
    }

    boolean result(int request, int result, Intent data) {
        if(request!=SAVE_CA)return false;
        byte[] certificate=pending;pending=null;
        if(result!=Activity.RESULT_OK||data==null||data.getData()==null||certificate==null)return true;
        try(java.io.OutputStream out=activity.getContentResolver().openOutputStream(data.getData(),"wt")){
            if(out==null)throw new java.io.IOException();
            out.write(certificate);out.flush();
        }catch(Exception failure){error("Could not save the public certificate. Nothing was installed.");return true;}
        new AlertDialog.Builder(activity).setTitle("Install through Android Settings")
            .setMessage("Only a public certificate was saved. In Settings choose Security → More security settings → "
                +"Encryption & credentials → Install a certificate → CA certificate. Menu names may vary. "
                +"Select Kiosk-installation-ca.crt and confirm the system warning yourself. "
                +"Return here and retry. Credentials remain protected by a real WebView HTTPS connection; an error is never bypassed.")
            .setNegativeButton("Later",null).setPositiveButton("Open Settings",(d,w)->
                activity.startActivity(new Intent(Settings.ACTION_SECURITY_SETTINGS))).show();
        return true;
    }

    private void error(String text){new AlertDialog.Builder(activity).setMessage(text).setPositiveButton("OK",null).show();}
}
