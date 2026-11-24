package org.kiosk.harness;
import android.test.InstrumentationTestCase;
import org.kiosk.harness.binding.*;
import java.nio.file.*;
@SuppressWarnings("deprecation")
public class LocalPreparationAndroidTest extends InstrumentationTestCase {
    private PreparationVectors.Loader loader(){return name->LocalAdmissionInputs.load(getInstrumentation().getContext(),name);}
    public void testValid()throws Exception{PreparationVectors.valid(loader());}
    public void testConfirmations()throws Exception{PreparationVectors.confirmations(loader());}
    public void testTampering()throws Exception{PreparationVectors.contentTampering(loader());}
    public void testCaptureFailures()throws Exception{Path root=getInstrumentation().getTargetContext().getNoBackupFilesDir().getCanonicalFile().toPath().resolve("preparation-fault-"+java.util.UUID.randomUUID());Files.createDirectory(root);try{PreparationVectors.captureFailures(root,loader());}finally{Files.delete(root);}}
    public void testConfirmedImageCapabilitySeparateFromWindowsEvidence()throws Exception{
        for(String name:java.util.List.of("C","B")){
            var all=LocalAdmissionInputs.load(getInstrumentation().getContext(),name);var confirmation=LocalPreparation.Confirmation.valueOf(name);
            var evidence=LocalPreparation.confirm(new java.io.ByteArrayInputStream(all.get("preparation.json")),confirmation,confirmation.sha256);
            var owned=LocalPreparation.capture(getInstrumentation().getTargetContext(),all,evidence);
            try(var candidate=owned.capture()){
                for(String file:evidence.pkg().files().keySet())if(file.startsWith("static/uploads/")){
                    var options=new android.graphics.BitmapFactory.Options();options.inJustDecodeBounds=true;
                    try(var input=candidate.source(CapturedCandidate.Part.PACKAGE).open(file)){assertNull(android.graphics.BitmapFactory.decodeStream(input,null,options));}
                    assertTrue(options.outWidth>0&&options.outHeight>0);
                    android.graphics.Bitmap decoded;
                    try(var input=candidate.source(CapturedCandidate.Part.PACKAGE).open(file)){decoded=android.graphics.BitmapFactory.decodeStream(input);}
                    assertNotNull(decoded);
                    try{
                        assertEquals(options.outWidth,decoded.getWidth());assertEquals(options.outHeight,decoded.getHeight());
                        var observation=new org.json.JSONObject().put("fixture",name).put("preparation_sha256",confirmation.sha256).put("sha256",evidence.pkg().files().get(file).sha256()).put("windows_evidence_environment",evidence.windowsEnvironment()).put("android_bounds_width",options.outWidth).put("android_bounds_height",options.outHeight).put("android_full_width",decoded.getWidth()).put("android_full_height",decoded.getHeight()).put("decoder_equivalence_claimed",false);
                        try(var out=getInstrumentation().getTargetContext().openFileOutput("local-admission-decode.jsonl",android.content.Context.MODE_APPEND)){out.write((observation+"\n").getBytes(java.nio.charset.StandardCharsets.UTF_8));}
                    }finally{decoded.recycle();}
                }
            }
        }
    }
}
