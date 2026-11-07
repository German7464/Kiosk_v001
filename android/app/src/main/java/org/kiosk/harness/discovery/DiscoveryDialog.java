package org.kiosk.harness.discovery;

import android.app.*;
import android.os.*;
import android.widget.*;
import java.util.concurrent.*;
import java.util.function.Consumer;

/** Ephemeral native hints. Explicit Use address is the only transition to independent authority. */
public final class DiscoveryDialog implements AutoCloseable {
    record Outcome(String network,DiscoverySearch.Result result) {}
    interface Backend { Outcome run(DiscoverySearch search)throws Exception; }
    private final Activity activity;
    private final Handler ui=new Handler(Looper.getMainLooper());
    private final ExecutorService worker=Executors.newSingleThreadExecutor();
    private final Consumer<String> selected;
    private final Backend backend;
    private AlertDialog dialog;
    private DiscoverySearch search;
    private long generation;
    private boolean closed;
    private EditText address;
    private TextView status;
    private LinearLayout results;
    private Button find;
    public DiscoveryDialog(Activity activity,Consumer<String> selected){this(activity,selected,search->{var lan=AndroidLanDiscovery.active(activity);return new Outcome(lan.description(),search.run(lan::open));});}
    DiscoveryDialog(Activity activity,Consumer<String> selected,Backend backend){this.activity=activity;this.selected=selected;this.backend=backend;}
    public void show(String savedOrigin){
        LinearLayout root=new LinearLayout(activity);root.setOrientation(LinearLayout.VERTICAL);
        address=new EditText(activity);address.setSingleLine(true);address.setHint("https://server:port");address.setText(savedOrigin);root.addView(address);
        status=new TextView(activity);status.setText("LAN results are untrusted hints. Enter an address manually or search.");root.addView(status);
        find=new Button(activity);find.setText("Search LAN");root.addView(find);find.setOnClickListener(v->start());
        Button cancel=new Button(activity);cancel.setText("Cancel search");root.addView(cancel);cancel.setOnClickListener(v->{cancelSearch();results.removeAllViews();status.setText("Search cancelled. Enter address manually or search again.");});
        results=new LinearLayout(activity);results.setOrientation(LinearLayout.VERTICAL);ScrollView scroll=new ScrollView(activity);scroll.addView(results);root.addView(scroll,new LinearLayout.LayoutParams(-1,300));
        dialog=new AlertDialog.Builder(activity).setTitle("Server address / LAN search").setView(root).setNegativeButton("Close",null).setPositiveButton("Use address",null).create();
        dialog.setOnDismissListener(d->close());dialog.show();
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{try{String exact=DiscoveryProtocol.origin(address.getText().toString());close();selected.accept(exact);}catch(Exception refused){status.setText("Enter an exact HTTPS origin with explicit port.");}});
    }
    private void cancelSearch(){generation++;if(search!=null){search.close();search=null;}if(find!=null)find.setEnabled(true);}
    private void start(){
        if(closed||search!=null)return;results.removeAllViews();long current=++generation;search=new DiscoverySearch();DiscoverySearch owned=search;find.setEnabled(false);status.setText("Searching active LAN…");
        worker.execute(()->{try{
            var outcome=backend.run(owned);var found=outcome.result();
            ui.post(()->{if(closed||generation!=current)return;search=null;find.setEnabled(true);
                status.setText(outcome.network()+"\n"+found.hints().size()+" untrusted results; queries="+found.sent()+" inputs="+found.inputs()+" duration="+found.millis()+"ms. Select explicitly or enter address manually.");
                android.util.Log.i("KioskDiscovery","network="+outcome.network()+" queries="+found.sent()+" inputs="+found.inputs()+" results="+found.hints().size()+" millis="+found.millis());
                android.util.Log.i("KioskDiscovery","query_base64="+found.queryBase64());
                for(var packet:found.received())android.util.Log.i("KioskDiscovery","reply_source="+packet.source()+":"+packet.port()+" reply_base64="+packet.base64());
                for(var hint:found.hints()){Button row=new Button(activity);row.setAllCaps(false);row.setText(hint.label()+"\n"+hint.origin());results.addView(row);row.setOnClickListener(v->{cancelSearch();address.setText(hint.origin());status.setText("Untrusted address selected. Use address to check independent authority; saved registration is retained.");});}
            });
        }catch(Exception failure){ui.post(()->{if(closed||generation!=current)return;search=null;find.setEnabled(true);status.setText("LAN unavailable: "+(failure instanceof SecurityException?"network permission denied":"check active Wi-Fi/Ethernet IPv4 and broadcast policy")+". Enter address manually.");});}});
    }
    public void close(){if(closed)return;closed=true;cancelSearch();worker.shutdownNow();if(dialog!=null)dialog.dismiss();}
}
