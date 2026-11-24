package org.kiosk.harness.delivery;

import org.junit.Test;
import static org.junit.Assert.*;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.kiosk.harness.core.LocalView;
import org.kiosk.harness.delivery.DeliveryClientRecoveryTest.Lab;
import org.kiosk.harness.storage.PreparedAdmission;

/**
 * lan-trust-lifecycle-v2 client behaviour behind the bounded I/O seams: the intermediate issuer pin
 * replaces the leaf pin (so a legitimate leaf rotation needs no re-enrollment), and credential
 * renewal advances only expires_at while device_id, credential_id and the local secret stay stable.
 */
public class DeliveryCredentialRenewalTest {
    static final DeliveryClientRecoveryTest OWNER=new DeliveryClientRecoveryTest();
    static byte[] bytes(String s){return s.getBytes(StandardCharsets.UTF_8);}
    static void refused(Checked work)throws Exception{try{work.run();fail("must refuse");}catch(AssertionError failure){throw failure;}catch(Exception expected){}}
    interface Checked{void run()throws Exception;}

    @Test public void v2TrustPinsIssuerAndToleratesLegitimateLeafRotation()throws Exception{
        try(Lab lab=OWNER.new Lab(true)){
            DeliveryClient c=lab.enrolled();PreparedAdmission.Request request=lab.accept(c);
            assertEquals(2,lab.store.saved.getInt("trust_version"));
            assertEquals(lab.issuer,lab.store.saved.getString("trust_issuer"));
            assertFalse(lab.store.saved.has("peer"));
            // Same issuer, new serving leaf: the stored issuer pin still admits the assignment.
            lab.peer=LocalView.digest(bytes("rotated-serving-leaf"));
            assertNull(lab.client().download(lab.pid));
            // A different issuer is a different authority and must be refused.
            lab.issuer="0".repeat(64);
            refused(()->lab.client().download(lab.pid));
            assertEquals(DeliveryTrustV2Test.ISSUER,lab.store.saved.getString("trust_issuer"));
            lab.issuer=DeliveryTrustV2Test.ISSUER;
            lab.client().verify(request,PreparedAdmission.Phase.PRIVATE_REOPEN);
        }
    }

    @Test public void v2UpgradeDoesNotFallBackToV1LeafTrust()throws Exception{
        try(Lab lab=OWNER.new Lab(true)){
            lab.accept(lab.enrolled());
            assertEquals(2,lab.store.saved.getInt("trust_version"));
            lab.fault="trust-v1";
            refused(()->lab.client().download(lab.pid));
            assertEquals(2,lab.store.saved.getInt("trust_version"));
            assertEquals(DeliveryTrustV2Test.ISSUER,lab.store.saved.getString("trust_issuer"));
        }
    }

    @Test public void automaticRenewalAdvancesOnlyExpiryAndKeepsIdentity()throws Exception{
        try(Lab lab=OWNER.new Lab(true)){
            DeliveryClient c=lab.enrolled();
            String secret=lab.store.saved.getString("secret"),device=lab.store.saved.getString("device"),credential=lab.store.saved.getString("credential");
            // Below one day remaining: the next sync renews without any operator action.
            lab.credentialExpires=lab.clock.now+3600;lab.store.saved.put("credential_expires",lab.clock.now+3600);
            DeliveryClient next=lab.client();
            assertTrue(next.credentialRenewalDue());
            lab.accept(next);
            assertEquals(1,lab.renewCalls);
            long first=lab.store.saved.getLong("credential_expires");
            assertTrue(first>lab.clock.now+3600&&first<=lab.clock.now+7*86400);
            assertEquals(lab.clock.now,lab.store.saved.getLong("credential_renewed_at"));
            assertEquals(secret,lab.store.saved.getString("secret"));
            assertEquals(device,lab.store.saved.getString("device"));
            assertEquals(credential,lab.store.saved.getString("credential"));
            assertEquals("",lab.store.saved.optString("credential_recovery",""));
            // A second sync inside the window advances again, still with the same identity.
            lab.client().download(lab.pid);
            assertEquals(2,lab.renewCalls);
            assertTrue(lab.store.saved.getLong("credential_expires")>first);
            assertEquals(secret,lab.store.saved.getString("secret"));
            assertEquals(credential,lab.store.saved.getString("credential"));
        }
    }

    @Test public void renewalRefusesNonAdvancingOrForeignIdentityWithoutLosingState()throws Exception{
        for(int mode:List.of(1,2)){
            try(Lab lab=OWNER.new Lab(true)){
                lab.accept(lab.enrolled());
                String secret=lab.store.saved.getString("secret"),credential=lab.store.saved.getString("credential");
                long window=lab.clock.now+3600;
                lab.credentialExpires=window;lab.store.saved.put("credential_expires",window);
                lab.renewMode=mode;
                DeliveryClient client=lab.client();
                // The offered expiry never advances (mode 1) or belongs to another credential (mode 2).
                client.download(lab.pid);
                assertEquals(1,lab.renewCalls);
                assertEquals(window,lab.store.saved.getLong("credential_expires"));
                assertEquals(secret,lab.store.saved.getString("secret"));
                assertEquals(credential,lab.store.saved.getString("credential"));
                // Bounded retry in the same process: no immediate hammering of the endpoint.
                client.download(lab.pid);
                assertEquals(1,lab.renewCalls);
            }
        }
    }

    @Test public void expiredCredentialIsFlaggedNotSilentlyCleared()throws Exception{
        try(Lab lab=OWNER.new Lab(true)){
            DeliveryClient c=lab.enrolled();PreparedAdmission.Request request=lab.accept(c);
            String secret=lab.store.saved.getString("secret"),credential=lab.store.saved.getString("credential");
            String accepted=lab.store.saved.getJSONObject("accepted").toString();
            lab.credentialExpires=lab.clock.now+3600;lab.store.saved.put("credential_expires",lab.clock.now+3600);
            lab.renewMode=3;
            refused(()->lab.client().download(lab.pid));
            assertEquals("credential_expired",lab.store.saved.getString("credential_recovery"));
            assertEquals(secret,lab.store.saved.getString("secret"));
            assertEquals(credential,lab.store.saved.getString("credential"));
            assertEquals(accepted,lab.store.saved.getJSONObject("accepted").toString());
            // Accepted offline content still reopens without network; no authority is re-minted.
            lab.client().verify(request,PreparedAdmission.Phase.PRIVATE_REOPEN);
        }
    }

    @Test public void revocationAndAuthorityRefusalsAreDistinguished()throws Exception{
        // The server's fixed label, not "any 401", decides the recovery meaning.
        try(Lab lab=OWNER.new Lab(true)){
            lab.accept(lab.enrolled());
            lab.credentialExpires=lab.clock.now+3600;lab.store.saved.put("credential_expires",lab.clock.now+3600);
            lab.renewMode=4;
            refused(()->lab.client().download(lab.pid));
            assertEquals("credential_revoked",lab.store.saved.getString("credential_recovery"));
            assertEquals("invalid_credential",lab.store.saved.getString("credential_error"));
            assertTrue(lab.store.saved.has("credential"));
            assertTrue(lab.store.saved.has("accepted"));
        }
        try(Lab lab=OWNER.new Lab(true)){
            lab.accept(lab.enrolled());
            lab.credentialExpires=lab.clock.now+3600;lab.store.saved.put("credential_expires",lab.clock.now+3600);
            lab.renewMode=5;
            // Expired signed authority is recoverable: the still-valid credential is kept
            // and the ordinary sync continues on a bounded retry schedule.
            assertNull(lab.client().download(lab.pid));
            assertEquals("authority_expired",lab.store.saved.getString("credential_recovery"));
            assertEquals("admission_authority_expired",lab.store.saved.getString("credential_error"));
            assertTrue(lab.store.saved.has("credential"));
        }
    }

    @Test public void bootstrapWindowOnlyGatesInitialConfirmation()throws Exception{
        try(Lab lab=OWNER.new Lab(true)){
            long issued=lab.clock.now-10,expires=lab.clock.now+1;
            DeliveryClient c=lab.enrolledAt(issued,expires,"short-window");
            lab.accept(c);
            // Well past the short initial-enrollment bootstrap window: an already
            // confirmed anchor must keep synchronizing under the signed group trust.
            lab.clock.now=expires+500;
            assertNull(lab.client().download(lab.pid));
            lab.client().confirmClock();
            assertNull(lab.client().download(lab.pid));
        }
    }

    @Test public void expiredSignedTrustBlocksNewAdmissionAndKeepsOfflineContent()throws Exception{
        try(Lab lab=OWNER.new Lab(true)){
            DeliveryClient c=lab.enrolled();PreparedAdmission.Request request=lab.accept(c);
            String device=lab.store.saved.getString("device"),credential=lab.store.saved.getString("credential");
            lab.clock.now=lab.trustExpires+10;
            lab.store.saved.put("highest_time",lab.trustExpires);
            lab.credentialExpires=lab.clock.now+3600;lab.store.saved.put("credential_expires",lab.clock.now+3600);
            try{lab.client().download(lab.pid);fail("expired signed trust must refuse admission");}
            catch(Exception expected){assertEquals("authority_window_refused",String.valueOf(expected.getMessage()));}
            // No new generation is credited and the accepted offline content still opens.
            lab.client().verify(request,PreparedAdmission.Phase.PRIVATE_REOPEN);
            assertEquals(device,lab.store.saved.getString("device"));
            assertEquals(credential,lab.store.saved.getString("credential"));
            assertTrue(lab.store.saved.has("accepted"));
        }
    }

    @Test public void renewalIsNotAttemptedOutsideTheWindow()throws Exception{
        try(Lab lab=OWNER.new Lab(true)){
            lab.accept(lab.enrolled());
            assertFalse(lab.client().credentialRenewalDue());
            lab.client().download(lab.pid);
            assertEquals(0,lab.renewCalls);
        }
    }
}
