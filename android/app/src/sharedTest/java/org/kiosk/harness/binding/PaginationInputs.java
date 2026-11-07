package org.kiosk.harness.binding;
import android.content.Context;
import java.io.*;
import java.util.*;
public final class PaginationInputs {
    public static final List<String> NAMES=List.of("empty","control","long-text-tags","image-shapes","two-events","description-only");
    public static LocalPreparation.Confirmation confirmation(String name){if(!NAMES.contains(name))throw new IllegalArgumentException();return LocalPreparation.Confirmation.valueOf("TV_"+name.toUpperCase(Locale.ROOT).replace('-','_'));}
    public static LocalPreparation.Evidence evidence(Map<String,byte[]> all,String name)throws Exception{var c=confirmation(name);return LocalPreparation.confirm(new ByteArrayInputStream(all.get("preparation.json")),c,c.sha256);}
    public static PlaybackInputs.Owned capture(Context c,Map<String,byte[]> all,String name)throws Exception{return LocalPreparation.capture(c,all,evidence(all,name));}
}
