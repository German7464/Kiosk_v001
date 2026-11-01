package org.kiosk.harness.packagecore;

import android.test.InstrumentationTestCase;
import android.content.res.AssetManager;
import java.util.LinkedHashMap;
import java.util.Map;

/** Core-only target checks: no Activity, WebView, injection or package activation. */
@SuppressWarnings("deprecation")
public class PackageParserTest extends InstrumentationTestCase {
    private void collect(AssetManager assets,String folder,String relative,Map<String,byte[]> result) throws Exception {
        String[] children=assets.list(folder);
        if(children.length==0){result.put(relative,org.kiosk.harness.core.LocalView.readBounded(assets.open(folder),64L*1024*1024));return;}
        for(String name:children)collect(assets,folder+"/"+name,relative.isEmpty()?name:relative+"/"+name,result);
    }
    private Map<String,byte[]> load(String name) throws Exception {
        Map<String,byte[]> result=new LinkedHashMap<>();collect(getInstrumentation().getContext().getAssets(),"package-cases/"+name,"",result);return result;
    }
    private void log(String text){android.util.Log.i("EventsPackageCoreTest",text);}
    public void testNineCasesStructuralIntegrityOnly() throws Exception {PackageCoreVectors.oracle(this::load,this::log);}
    public void testJsonNumbersUnicodeAndManifestTypes() throws Exception {
        PackageCoreVectors.jsonAndUnicode(this::load,this::log);PackageCoreVectors.types(this::load,this::log);
        PackageCoreVectors.pathsAndLimits(this::load,this::log);
    }
    public void testResourceRegexAndPublicSchema() throws Exception {PackageCoreVectors.publicAndResources(this::load,this::log);}
}
