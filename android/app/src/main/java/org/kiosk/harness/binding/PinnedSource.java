package org.kiosk.harness.binding;

import java.io.InputStream;
import java.io.IOException;
import java.security.MessageDigest;
import java.util.Map;
import java.util.Set;
import org.kiosk.harness.core.LocalView;
import static org.kiosk.harness.binding.BindingFailure.Code.*;

/** Checks each observed read independently; never freezes or takes ownership of the source. */
final class PinnedSource implements LocalView.Source {
    private final LocalView.Source source;
    private final Map<String,DevelopmentWitness.Pin> pins;
    PinnedSource(LocalView.Source source, Map<String,DevelopmentWitness.Pin> pins,
                 String descriptor, long descriptorLimit, long fileLimit, long payloadLimit) throws BindingFailure {
        this.source=source; this.pins=pins;
        if(source==null || pins.isEmpty() || pins.size()>10001 || !pins.containsKey(descriptor))
            throw new BindingFailure(INVALID_WITNESS);
        long total=0;
        for(var e:pins.entrySet()) {
            var pin=e.getValue();
            if(!LocalView.safePath(e.getKey()) || !hash(pin.sha256()) || pin.size()<0
                || pin.size()>(e.getKey().equals(descriptor)?descriptorLimit:fileLimit))
                throw new BindingFailure(INVALID_WITNESS);
            if(!e.getKey().equals(descriptor)) {
                if(pin.size()>payloadLimit-total) throw new BindingFailure(INVALID_WITNESS);
                total+=pin.size();
            }
        }
    }
    static boolean hash(String value) { return value!=null && value.matches("[0-9a-f]{64}"); }
    void inventory() throws BindingFailure {
        try { if(!pins.keySet().equals(source.files())) throw new BindingFailure(INVENTORY_MISMATCH); }
        catch(BindingFailure e){throw e;}
        catch(Exception e){throw new BindingFailure(SOURCE_IO);}
    }
    void verifyAll() throws IOException {
        inventory();
        for(String path:pins.keySet()) verifyFile(path);
    }
    void verifyFile(String path) throws IOException {
        try(InputStream input=open(path)) {
            byte[] block=new byte[16384];
            while(input.read(block)!=-1) { /* streaming witness check */ }
        }
    }
    @Override public Set<String> files() throws IOException { inventory(); return pins.keySet(); }
    @Override public InputStream open(String path) throws IOException {
        var pin=pins.get(path);
        if(pin==null)throw new BindingFailure(INVENTORY_MISMATCH);
        final InputStream input;
        try { input=source.open(path); if(input==null)throw new IOException(); }
        catch(Exception e){throw new BindingFailure(SOURCE_IO);}
        return new InputStream() {
            private final MessageDigest digest=newDigest();
            private long count;
            private boolean closed, eof;
            @Override public int read() throws IOException {
                byte[] one=new byte[1];int n=read(one,0,1);return n<0?-1:one[0]&255;
            }
            @Override public int read(byte[] block,int offset,int length) throws IOException {
                if(closed)throw new BindingFailure(SOURCE_IO);
                if(length==0)return 0;
                if(eof)return -1;
                int ask=(int)Math.min(length,pin.size()-count+1),n;
                try { n=input.read(block,offset,ask); }
                catch(Exception e){throw new BindingFailure(SOURCE_IO);}
                if(n==-1) {
                    if(count!=pin.size() || !hex(digest.digest()).equals(pin.sha256()))
                        throw new BindingFailure(STREAM_INTEGRITY);
                    eof=true;return -1;
                }
                if(n<=0 || n>ask || n>pin.size()-count)throw new BindingFailure(STREAM_INTEGRITY);
                count+=n;digest.update(block,offset,n);return n;
            }
            @Override public void close() throws IOException {
                if(closed)return;
                closed=true;
                try { input.close(); }catch(Exception e){throw new BindingFailure(SOURCE_IO);}
            }
        };
    }
    private static MessageDigest newDigest() {
        try{return MessageDigest.getInstance("SHA-256");}catch(Exception e){throw new IllegalStateException();}
    }
    private static String hex(byte[] bytes) {
        StringBuilder s=new StringBuilder();for(byte b:bytes)s.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return s.toString();
    }
}
