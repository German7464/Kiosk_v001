package org.kiosk.harness.delivery;

/** Fail-closed admission clock policy; historical offline display/receipts do not mint authority. */
final class DeliveryClock {
    static void check(long now,long highest,long processWall,long elapsedMillis,long startedElapsed,
                      long issued,long expires,long credentialExpires,int boot,int confirmedBoot,boolean automatic)throws java.io.IOException {
        DeliveryProtocol.need(elapsedMillis>=startedElapsed&&now>=highest&&now>=issued&&now<expires&&now<credentialExpires
            &&now+2>=processWall+(elapsedMillis-startedElapsed)/1000&&boot>=0&&boot==confirmedBoot&&automatic);
    }
}
