package org.kiosk.harness.binding;

import java.io.*;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.*;
import org.kiosk.harness.core.LocalView;

/** Exclusive app-owned trees only, not hostile-filesystem/parent-race protection. */
final class CaptureFiles {
    private CaptureFiles(){}
    static Path resolve(Path root,String name)throws IOException{
        if(!LocalView.safePath(name))throw new IOException();
        Path p=root.resolve(name).normalize();if(!p.startsWith(root))throw new IOException();return p;
    }
    static LocalView.Source source(Path root,Map<String,DevelopmentWitness.Pin> pins,Runnable check){
        return new LocalView.Source(){
            @Override public Set<String> files()throws IOException{
                check.run();Set<String> actual=new HashSet<>(),dirs=new HashSet<>(Set.of(""));
                for(String name:pins.keySet())for(Path p=Path.of(name).getParent();p!=null;p=p.getParent())dirs.add(p.toString().replace('\\','/'));
                try(var walk=Files.walk(root)){
                    var it=walk.iterator();int count=0;
                    while(it.hasNext()){
                        Path p=it.next();if(++count>pins.size()+dirs.size()||Files.isSymbolicLink(p))throw new IOException();
                        String name=root.relativize(p).toString().replace('\\','/');
                        if(Files.isDirectory(p,LinkOption.NOFOLLOW_LINKS)){if(!dirs.contains(name))throw new IOException();}
                        else if(Files.isRegularFile(p,LinkOption.NOFOLLOW_LINKS)&&pins.containsKey(name))actual.add(name);
                        else throw new IOException();
                    }
                }
                return actual;
            }
            @Override public InputStream open(String name)throws IOException{
                check.run();if(!pins.containsKey(name))throw new IOException();Path p=resolve(root,name);
                if(!Files.isRegularFile(p,LinkOption.NOFOLLOW_LINKS))throw new IOException();
                InputStream raw=Files.newInputStream(p,LinkOption.NOFOLLOW_LINKS);
                return new FilterInputStream(raw){
                    @Override public int read(byte[] b,int off,int len)throws IOException{check.run();return super.read(b,off,len);}
                    @Override public int read()throws IOException{check.run();return super.read();}
                };
            }
        };
    }
    static void deleteOwned(Path owned)throws IOException{
        if(!Files.exists(owned,LinkOption.NOFOLLOW_LINKS))return;
        Files.walkFileTree(owned,new SimpleFileVisitor<Path>(){
            @Override public FileVisitResult visitFile(Path file,BasicFileAttributes attrs)throws IOException{Files.delete(file);return FileVisitResult.CONTINUE;}
            @Override public FileVisitResult postVisitDirectory(Path dir,IOException error)throws IOException{if(error!=null)throw error;Files.delete(dir);return FileVisitResult.CONTINUE;}
        });
    }
}
