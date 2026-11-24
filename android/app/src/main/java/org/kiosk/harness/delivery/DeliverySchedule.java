package org.kiosk.harness.delivery;

/** One complete network/admission operation at a time, with bounded reconnect backoff. */
public final class DeliverySchedule {
    private boolean running;
    private int failures;
    public synchronized boolean begin(){if(running)return false;running=true;return true;}
    public synchronized long finish(boolean success){
        running=false;if(success){failures=0;return 30000;}
        failures=Math.min(failures+1,5);return Math.min(120000,10000L<<(failures-1));
    }
}
