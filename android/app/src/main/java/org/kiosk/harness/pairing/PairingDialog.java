package org.kiosk.harness.pairing;

import android.app.Activity;
import android.app.AlertDialog;
import android.graphics.Typeface;
import android.util.TypedValue;
import android.view.ViewGroup;
import android.widget.*;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;

/**
 * Pending-enrollment UI for one exact request. Scanning, opening or looking up the code never
 * approves; this dialog only displays the request and lets the operator discard local waiting.
 * Closing it never sends an approval or denial, so the server request stays pending until the
 * administrator decides or the code expires.
 */
public final class PairingDialog implements AutoCloseable {
    public interface Actions {void cancelRequest();void refresh();}
    private static final DateTimeFormatter TIME=DateTimeFormatter.ofPattern("HH:mm:ss").withZone(ZoneId.systemDefault());
    private final Actions actions;
    private AlertDialog dialog;
    private final TextView status;
    private final TextView code;
    private final TextView facts;
    private final FrameLayout qrHost;
    private String payload="";
    private long expiresAt;
    private boolean closed;
    public PairingDialog(Activity activity,Actions actions){
        this.actions=actions;
        int pad=Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP,16,activity.getResources().getDisplayMetrics()));
        int qrSize=Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP,240,activity.getResources().getDisplayMetrics()));
        LinearLayout root=new LinearLayout(activity);root.setOrientation(LinearLayout.VERTICAL);root.setPadding(pad,pad,pad,pad);
        facts=new TextView(activity);root.addView(facts);
        code=new TextView(activity);code.setTextSize(TypedValue.COMPLEX_UNIT_SP,34);
        code.setTypeface(Typeface.MONOSPACE);code.setTextIsSelectable(true);root.addView(code);
        qrHost=new FrameLayout(activity);root.addView(qrHost,new LinearLayout.LayoutParams(qrSize,qrSize));
        status=new TextView(activity);status.setAccessibilityLiveRegion(ViewGroup.ACCESSIBILITY_LIVE_REGION_POLITE);root.addView(status);
        TextView hint=new TextView(activity);
        hint.setText("Scan with the phone camera, or open the server's /admin/devices/pair page and enter the code. Reviewing, signing in or looking up the code does not approve this device.");
        root.addView(hint);
        ScrollView scroll=new ScrollView(activity);scroll.addView(root);
        dialog=new AlertDialog.Builder(activity).setTitle("Pair this device").setView(scroll)
            .setNegativeButton("Close",null).setNeutralButton("Cancel request",null).setPositiveButton("Refresh",null).create();
    }
    public void show(){
        dialog.setOnDismissListener(d->closed=true);
        dialog.show();
        dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(v->actions.cancelRequest());
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->actions.refresh());
    }
    /** Updates display; returns false once the payload is empty (completed/denied/expired/cancelled). */
    public boolean update(String next,long expiresAt,long now){
        if(closed)return false;
        if(next==null||next.isEmpty()||now>=expiresAt)return false;
        boolean changed=!next.equals(payload);
        if(changed||expiresAt!=this.expiresAt){
            payload=next;this.expiresAt=expiresAt;
            String origin=payload.substring(0,payload.indexOf(PairingPayload.PATH));
            String visible=payload.substring(payload.indexOf("code=")+5);
            code.setText(visible);
            code.setContentDescription("Manual pairing code "+visible);
            facts.setText("Server: "+origin+"\nCode expires: "+TIME.format(Instant.ofEpochSecond(expiresAt)));
            if(changed){
                qrHost.removeAllViews();
                try{qrHost.addView(new QrCodeView(dialog.getContext(),payload),new FrameLayout.LayoutParams(-1,-1));}
                catch(Exception refused){TextView fallback=new TextView(dialog.getContext());fallback.setText("QR unavailable; use the manual code.");qrHost.addView(fallback,new FrameLayout.LayoutParams(-1,-1));}
            }
        }
        return true;
    }
    public void setStatus(String text){if(!closed)status.setText(text);}
    public boolean closed(){return closed;}
    @Override public void close(){if(!closed){closed=true;dialog.dismiss();}}
}
