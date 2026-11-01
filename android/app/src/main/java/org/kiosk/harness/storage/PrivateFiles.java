package org.kiosk.harness.storage;

import android.system.Os;
import android.system.OsConstants;
import android.os.ParcelFileDescriptor;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import org.kiosk.harness.core.LocalView;

/** Only app-owned fixture storage. Not a hostile-directory/symlink-TOCTOU admission adapter. */
final class PrivateFiles {
    static IOException refusal(String code){return new IOException(code);}
    static void plain(Path path) throws IOException {
        for(Path p=path.toAbsolutePath();p!=null;p=p.getParent())
            if(Files.isSymbolicLink(p))throw refusal("unsafe_private_tree");
    }
    static void directory(Path path) throws IOException {
        plain(path);Files.createDirectories(path);
        if(!Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS))throw refusal("unsafe_private_tree");
    }
    static InputStream open(Path path) throws IOException {
        plain(path);
        try {
            FileDescriptor fd=Os.open(path.toString(),OsConstants.O_RDONLY|OsConstants.O_NOFOLLOW|OsConstants.O_CLOEXEC,0);
            try {
                if(!OsConstants.S_ISREG(Os.fstat(fd).st_mode))throw refusal("unsafe_private_file");
                var owner=ownedDescriptor(fd);
                try{return new ParcelFileDescriptor.AutoCloseInputStream(owner);}catch(Exception e){owner.close();throw e;}
            } catch(Exception e){if(fd.valid())Os.close(fd);throw e;}
        }catch(Exception e){throw refusal("private_read_failed");}
    }
    static FileOutputStream output(Path path) throws IOException {
        plain(path);
        try{
            var owner=ownedDescriptor(Os.open(path.toString(),OsConstants.O_WRONLY|OsConstants.O_CREAT|OsConstants.O_TRUNC|OsConstants.O_NOFOLLOW|OsConstants.O_CLOEXEC,0600));
            try{return new ParcelFileDescriptor.AutoCloseOutputStream(owner);}catch(Exception e){owner.close();throw e;}
        }
        catch(Exception e){throw refusal("private_write_failed");}
    }
    private static ParcelFileDescriptor ownedDescriptor(FileDescriptor original)throws Exception{
        ParcelFileDescriptor owner=null;
        try{
            // Android File*Stream(FileDescriptor) does not own/close that native descriptor.
            owner=ParcelFileDescriptor.dup(original);
            Os.fcntlInt(owner.getFileDescriptor(),OsConstants.F_SETFD,OsConstants.FD_CLOEXEC);
            Os.close(original);return owner;
        }catch(Exception e){if(owner!=null)try{owner.close();}catch(Exception ignored){}if(original.valid())try{Os.close(original);}catch(Exception ignored){}throw e;}
    }
    static void syncDirectory(Path directory) throws IOException {
        try {
            FileDescriptor fd=Os.open(directory.toString(),OsConstants.O_RDONLY|OsConstants.O_NOFOLLOW|OsConstants.O_CLOEXEC,0);
            try{if(!OsConstants.S_ISDIR(Os.fstat(fd).st_mode))throw refusal("unsafe_private_tree");Os.fsync(fd);}finally{Os.close(fd);}
        }catch(Exception e){throw refusal("directory_sync_failed");}
    }
    static void rename(Path source,Path destination) throws IOException {
        plain(source);plain(destination);
        try{Os.rename(source.toString(),destination.toString());}
        catch(Exception e){throw refusal("rename_failed");}
        syncDirectory(destination.getParent());
        if(!source.getParent().equals(destination.getParent()))syncDirectory(source.getParent());
    }
    static byte[] metadata(Path path) throws IOException {return LocalView.readBounded(open(path),4096);}

    static final class Source implements LocalView.Source {
        final Path root;final Map<String,PublicationFixtures.Pin> pins;final Runnable read;
        Source(Path root,Map<String,PublicationFixtures.Pin> pins,Runnable read){this.root=root;this.pins=pins;this.read=read;}
        @Override public InputStream open(String name) throws IOException {
            if(!pins.containsKey(name))throw refusal("unknown_private_resource");read.run();return PrivateFiles.open(root.resolve(name));
        }
        @Override public Set<String> files() throws IOException {
            plain(root);Set<String> directories=new HashSet<>();directories.add("");
            for(String name:pins.keySet())for(Path p=Path.of(name).getParent();p!=null;p=p.getParent())directories.add(p.toString().replace('\\','/'));
            Set<String> actual=new HashSet<>();int count=0,limit=pins.size()+directories.size();
            try(var paths=Files.walk(root)){
                var iterator=paths.iterator();
                while(iterator.hasNext()){
                    Path path=iterator.next();if(++count>limit)throw refusal("private_inventory_mismatch");
                    String relative=root.relativize(path).toString().replace('\\','/');
                    if(Files.isSymbolicLink(path))throw refusal("unsafe_private_tree");
                    if(Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS)){
                        if(!directories.contains(relative))throw refusal("private_inventory_mismatch");
                    }else if(Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)&&pins.containsKey(relative))actual.add(relative);
                    else throw refusal("private_inventory_mismatch");
                }
            }catch(RuntimeException e){throw refusal("private_inventory_mismatch");}
            return actual;
        }
        void verifyPins() throws IOException {
            if(!files().equals(pins.keySet()))throw refusal("private_inventory_mismatch");
            for(var entry:pins.entrySet()){
                byte[] bytes=LocalView.readBounded(open(entry.getKey()),entry.getValue().size());
                if(bytes.length!=entry.getValue().size()||!LocalView.digest(bytes).equals(entry.getValue().sha256()))throw refusal("private_integrity_failure");
            }
        }
    }
}
