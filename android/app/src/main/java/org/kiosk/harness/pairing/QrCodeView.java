package org.kiosk.harness.pairing;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.view.View;
import io.nayuki.qrcodegen.QrCode;

/**
 * Locally generated QR for one exact pairing payload. Uses the vendored Nayuki MIT generator;
 * no network encoder, scanner SDK or custom QR algorithm. Drawing is a plain module grid so the
 * bitmap always matches the payload that produced it.
 */
public final class QrCodeView extends View {
    private static final int QUIET_MODULES=4;
    private final QrCode qr;
    private final Paint paint=new Paint();
    public QrCodeView(Context context,String payload){
        super(context);
        qr=QrCode.encodeText(payload,QrCode.Ecc.MEDIUM);
        paint.setColor(Color.BLACK);
        paint.setAntiAlias(false);
        setBackgroundColor(Color.WHITE);
        setContentDescription("Pairing QR code for this request. The same eight-character code is shown as text.");
    }
    @Override protected void onMeasure(int widthSpec,int heightSpec){
        int size=Math.min(MeasureSpec.getSize(widthSpec),MeasureSpec.getSize(heightSpec));
        setMeasuredDimension(resolveSize(size,widthSpec),resolveSize(size,heightSpec));
    }
    @Override protected void onDraw(Canvas canvas){
        int side=Math.min(getWidth(),getHeight());if(side<=0)return;
        float module=side/(float)(qr.size+2*QUIET_MODULES);
        float offset=(side-qr.size*module)/2f;
        for(int y=0;y<qr.size;y++)for(int x=0;x<qr.size;x++)
            if(qr.getModule(x,y))canvas.drawRect(offset+x*module,offset+y*module,offset+(x+1)*module,offset+(y+1)*module,paint);
    }
}
