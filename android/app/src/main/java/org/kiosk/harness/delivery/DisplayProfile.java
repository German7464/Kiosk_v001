package org.kiosk.harness.delivery;

import java.util.*;
import static org.kiosk.harness.delivery.DeliveryProtocol.*;

/** display-profile-v1: bounded configuration, never enrollment or update authority. */
public record DisplayProfile(String id,long revision,String mode) {
    public static DisplayProfile legacy(){return new DisplayProfile("events-default",1,"local");}
    public static DisplayProfile parse(Map<String,Object> m)throws Exception {
        DeliveryJson.keys(m,"version","profile_id","revision","mode");
        need(num(m,"version")==1&&num(m,"revision")>0);
        String id=DeliveryProtocol.id(str(m,"profile_id"));need(id.length()<=64);
        String mode=str(m,"mode");if(!List.of("local","tv","kiosk").contains(mode))throw new java.io.IOException("unsupported_display_profile");
        return new DisplayProfile(id,num(m,"revision"),mode);
    }
    public String apply(String fallback){return mode.equals("local")?fallback:mode;}
}
