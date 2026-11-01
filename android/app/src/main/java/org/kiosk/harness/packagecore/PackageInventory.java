package org.kiosk.harness.packagecore;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.math.BigInteger;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import org.kiosk.harness.core.LocalView;
import static org.kiosk.harness.packagecore.PackageFailure.Code.*;
import static org.kiosk.harness.packagecore.PackageJson.*;

final class PackageInventory {
    static final long FILE_LIMIT=256L*1024*1024, TOTAL_LIMIT=64L*1024*1024;
    static final int MANIFEST_LIMIT=2*1024*1024, BLOCK=256*1024;
    static final class Entry {
        final long size; final String hash;
        Entry(long size,String hash){this.size=size;this.hash=hash;}
    }
    static Map<String,Entry> parse(Object value) throws PackageFailure {
        List<?> rows=array(value,invalid_package);
        if(rows.isEmpty()||rows.size()>10000)throw PackageFailure.fail(invalid_package);
        Map<String,Entry> entries=new LinkedHashMap<>();Set<String> folded=new HashSet<>();
        for(Object row:rows){
            Map<String,Object> entry=object(row,invalid_package);
            String path=string(entry.get("path"),invalid_package),hash=string(entry.get("sha256"),invalid_package);
            BigInteger size=integer(entry.get("size"),invalid_package);
            if(!safe(path)||!folded.add(PackageCaseFold.fold(path))||size.signum()<0||size.compareTo(BigInteger.valueOf(FILE_LIMIT))>0
                ||!hash.matches("[0-9a-f]{64}"))throw PackageFailure.fail(invalid_package);
            // Already bounded to256MiB, so conversion cannot truncate or overflow.
            entries.put(path,new Entry(size.longValue(),hash));
        }
        return entries;
    }
    static boolean safe(String path) {
        if(path.isEmpty()||path.codePointCount(0,path.length())>240)return false;
        if(path.codePoints().anyMatch(c->c<32||"\\:<>\"|?*%#".indexOf(c)>=0))return false;
        for(String part:path.split("/",-1)){
            if(part.isEmpty()||part.equals(".")||part.equals("..")||part.endsWith(".")||part.endsWith(" "))return false;
            String base=part.split("\\.",-1)[0].toUpperCase(Locale.ROOT);
            if(Set.of("CON","PRN","AUX","NUL").contains(base)||base.matches("COM[1-9]|LPT[1-9]"))return false;
        }
        return true;
    }
    static void treeAndTotal(LocalView.Source source,Map<String,Entry> entries) throws Exception {
        Set<String> exact=new HashSet<>(entries.keySet());exact.add("manifest.json");
        if(!exact.equals(source.files()))throw PackageFailure.fail(inventory_mismatch);
        long total=0;
        for(Entry entry:entries.values()){
            if(entry.size>TOTAL_LIMIT-total)throw PackageFailure.fail(package_too_large);
            total+=entry.size;
        }
    }
    static byte[] manifest(LocalView.Source source) throws Exception {
        return read(source,"manifest.json",MANIFEST_LIMIT,null,manifest_too_large,true);
    }
    static byte[] payload(LocalView.Source source,String name,Entry entry,boolean buffer,boolean reread) throws Exception {
        return read(source,name,entry.size,entry.hash,reread?source_changed:integrity_failure,buffer);
    }
    private static byte[] read(LocalView.Source source,String name,long limit,String expected,
                               PackageFailure.Code defect,boolean buffer) throws Exception {
        MessageDigest hash=MessageDigest.getInstance("SHA-256");
        try(InputStream input=source.open(name);ByteArrayOutputStream output=buffer?new ByteArrayOutputStream():null){
            byte[] block=new byte[BLOCK];long count=0;
            while(true){
                int n=input.read(block,0,(int)Math.min(block.length,limit-count+1));
                if(n<0)break;
                if(n==0||n>limit-count)throw PackageFailure.fail(defect);
                count+=n;hash.update(block,0,n);if(buffer)output.write(block,0,n);
            }
            if(expected!=null){
                StringBuilder digest=new StringBuilder();for(byte b:hash.digest())digest.append(String.format(Locale.ROOT,"%02x",b&255));
                if(count!=limit||!expected.equals(digest.toString()))throw PackageFailure.fail(defect);
            }
            return buffer?output.toByteArray():null;
        }
    }
}
