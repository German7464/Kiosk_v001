package org.kiosk.harness.discovery;

import android.content.Context;
import android.net.*;
import java.net.*;

/** Bind both platform Network and one explicit IPv4 source; never change process routing. */
public final class AndroidLanDiscovery {
    public record Lan(Network network,InetAddress address,String description) {
        public DatagramSocket open()throws Exception {
            DatagramSocket s=new DatagramSocket(null);
            try{network.bindSocket(s);s.bind(new InetSocketAddress(address,0));return s;}catch(Exception failure){s.close();throw failure;}
        }
    }
    public static Lan active(Context context)throws Exception {
        ConnectivityManager cm=context.getSystemService(ConnectivityManager.class);Network network=cm.getActiveNetwork();
        NetworkCapabilities caps=cm.getNetworkCapabilities(network);LinkProperties link=cm.getLinkProperties(network);
        if(caps==null||link==null||caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)||(!caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)&&!caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)))throw new java.io.IOException("active_wifi_or_ethernet_required");
        InetAddress source=null;
        for(LinkAddress a:link.getLinkAddresses())if(a.getAddress() instanceof Inet4Address&&!a.getAddress().isLoopbackAddress()&&!a.getAddress().isLinkLocalAddress()){
            if(source!=null)throw new java.io.IOException("ambiguous_lan_ipv4");source=a.getAddress();
        }
        if(source==null)throw new java.io.IOException("lan_ipv4_required");
        return new Lan(network,source,(caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)?"Wi-Fi ":"Ethernet ")+link.getInterfaceName()+" / "+source.getHostAddress());
    }
}
