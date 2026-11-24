package org.kiosk.harness.storage;
import android.test.InstrumentationTestCase;
import android.system.Os;
import java.io.*;
import java.nio.file.*;
import java.util.*;
/** Bounded descriptor ownership checks, not resource-pressure testing. */
@SuppressWarnings("deprecation")
public class PrivateFilesOwnershipTest extends InstrumentationTestCase {
    private Path file;
    @Override protected void setUp()throws Exception{super.setUp();file=Files.createTempFile(getInstrumentation().getTargetContext().getFilesDir().getCanonicalFile().toPath(),"native-fd-",".tmp");}
    @Override protected void tearDown()throws Exception{Files.deleteIfExists(file);super.tearDown();}
    public void testOutputOwnsNativeDescriptor()throws Exception{
        FileDescriptor fd=null;try{try(var output=PrivateFiles.output(file)){fd=output.getFD();assertTrue((Os.fcntlInt(fd,android.system.OsConstants.F_GETFD,0)&android.system.OsConstants.FD_CLOEXEC)!=0);output.write(1);output.getFD().sync();}assertFalse("native output descriptor remains open",fd.valid());}
        finally{if(fd!=null&&fd.valid())Os.close(fd);}
    }
    public void testInputOwnsNativeDescriptor()throws Exception{
        Files.write(file,new byte[]{1});FileDescriptor fd=null;
        try{try(var input=(FileInputStream)PrivateFiles.open(file)){fd=input.getFD();assertTrue((Os.fcntlInt(fd,android.system.OsConstants.F_GETFD,0)&android.system.OsConstants.FD_CLOEXEC)!=0);assertEquals(1,input.read());}assertFalse("native input descriptor remains open",fd.valid());}
        finally{if(fd!=null&&fd.valid())Os.close(fd);}
    }
    private int descriptors(){return new File("/proc/self/fd").list().length;}
    public void testRepeatedPrivateIOHasBoundedDescriptors()throws Exception{
        int before=descriptors();List<FileDescriptor> cleanup=new ArrayList<>();
        try{
            for(int i=0;i<32;i++){
                try(var output=PrivateFiles.output(file)){cleanup.add(output.getFD());output.write(1);}
                try(var input=(FileInputStream)PrivateFiles.open(file)){cleanup.add(input.getFD());assertEquals(1,input.read());}
            }
            int after=descriptors();android.util.Log.i("PrivateFilesOwnership","before="+before+" after="+after+" loops=32");assertTrue("descriptor growth",after<=before+4);
        }finally{for(FileDescriptor fd:cleanup)if(fd.valid())Os.close(fd);}
    }
}
