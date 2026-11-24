package org.kiosk.harness.pairing;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.view.View;
import android.test.InstrumentationTestCase;

/** On-device check that the displayed QR is drawn from the exact contract payload. */
@SuppressWarnings("deprecation")
public final class PairingPhoneTest extends InstrumentationTestCase {
    private static final String PAYLOAD="https://192.168.1.165:18543/admin/devices/pair#v=1&code=ABCD2345";
    public void testContractPayloadOnDevice(){
        assertEquals(PAYLOAD,PairingPayload.of("https://192.168.1.165:18543","ABCD2345"));
        try{PairingPayload.of("http://192.168.1.165:18543","ABCD2345");fail("plain http must be refused");}catch(IllegalArgumentException expected){}
    }
    public void testQrViewDrawsOpaqueModulesWithQuietZone()throws Exception{
        final QrCodeView[] holder=new QrCodeView[1];
        getInstrumentation().runOnMainSync(()->holder[0]=new QrCodeView(getInstrumentation().getTargetContext(),PAYLOAD));
        QrCodeView view=holder[0];
        assertNotNull(view.getContentDescription());
        getInstrumentation().runOnMainSync(()->{
            view.measure(View.MeasureSpec.makeMeasureSpec(370,View.MeasureSpec.EXACTLY),View.MeasureSpec.makeMeasureSpec(370,View.MeasureSpec.EXACTLY));
            view.layout(0,0,370,370);
        });
        Bitmap bitmap=Bitmap.createBitmap(370,370,Bitmap.Config.ARGB_8888);
        getInstrumentation().runOnMainSync(()->view.draw(new Canvas(bitmap)));
        assertEquals("quiet zone must stay light",Color.WHITE,bitmap.getPixel(1,1));
        int dark=0;
        for(int y=0;y<370;y+=2)for(int x=0;x<370;x+=2)if((bitmap.getPixel(x,y)&0x00ffffff)!=0x00ffffff)dark++;
        assertTrue("QR modules must be drawn",dark>200);
    }
}
