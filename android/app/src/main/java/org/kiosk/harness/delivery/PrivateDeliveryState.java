package org.kiosk.harness.delivery;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.AtomicFile;
import java.io.*;
import java.security.KeyStore;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;
import org.json.JSONObject;

/** Authenticated, atomic app-private state. Loss/corruption never creates new authority. */
public final class PrivateDeliveryState implements DeliveryIO.Store {
    private final AtomicFile file;
    private final SecretKey key;
    public PrivateDeliveryState(Context context)throws Exception {
        file=new AtomicFile(new File(context.getNoBackupFilesDir(),"delivery-v1.enc"));
        KeyStore ks=KeyStore.getInstance("AndroidKeyStore");ks.load(null);
        String alias="kiosk.delivery.v1";
        if(!ks.containsAlias(alias)){
            if(hasState())throw new IOException("delivery_key_lost");
            KeyGenerator gen=KeyGenerator.getInstance("AES","AndroidKeyStore");
            gen.init(new KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            gen.generateKey();
        }
        key=(SecretKey)ks.getKey(alias,null);
    }
    public synchronized JSONObject read()throws Exception {
        if(!hasState())return new JSONObject();
        byte[] bytes;
        try(InputStream in=file.openRead()){bytes=in.readNBytes(4*1024*1024+1);}
        if(bytes.length<29||bytes.length>4*1024*1024)throw new IOException("delivery_state_invalid");
        Cipher c=Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.DECRYPT_MODE,key,new GCMParameterSpec(128,bytes,0,12));
        c.updateAAD("Kiosk/PrivateDelivery/v1".getBytes(java.nio.charset.StandardCharsets.US_ASCII));
        return new JSONObject(new String(c.doFinal(bytes,12,bytes.length-12),java.nio.charset.StandardCharsets.UTF_8));
    }
    private boolean hasState(){return file.getBaseFile().exists()||new File(file.getBaseFile().getPath()+".bak").exists();}
    public synchronized void write(JSONObject state)throws Exception {
        byte[] plain=state.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);
        if(plain.length>3*1024*1024)throw new IOException("delivery_state_full");
        Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.ENCRYPT_MODE,key);
        c.updateAAD("Kiosk/PrivateDelivery/v1".getBytes(java.nio.charset.StandardCharsets.US_ASCII));
        FileOutputStream out=null;
        try {out=file.startWrite();out.write(c.getIV());out.write(c.doFinal(plain));file.finishWrite(out);}
        catch(Exception e){if(out!=null)file.failWrite(out);throw e;}
    }
}
