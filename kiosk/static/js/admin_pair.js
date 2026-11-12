/* Smartphone pairing entry and review. Local-only, no third-party assets.
 * Reads the coordinator QR contract fragment (#v=1&code=ABCDEFGH), keeps the
 * code in a narrowly scoped session entry, drives the authenticated/CSRF-protected
 * lookup and reuses the existing guarded approve/deny endpoint. Scanning, GET,
 * login and lookup never approve on their own.
 *
 * Every asynchronous result is tagged with a monotonic sequence. A newer lookup
 * or a cancellation makes older responses inert, so an out-of-order reply can
 * never replace the request currently shown or re-enable a stale decision.
 */
(function () {
    "use strict";

    var PAIR_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    var PAIR_STORAGE_KEY = "kiosk.pair";
    var PAIR_TIMEOUT_MS = 15000;

    var pairState = {
        code: null,
        review: null,
        lookupBusy: false,
        decisionBusy: false,
        lookupSeq: 0,
        decisionSeq: 0,
    };

    var pairText = pairReadMessages();

    function pairReadMessages() {
        try {
            var node = document.getElementById("pair-messages");
            if (node && node.textContent) return JSON.parse(node.textContent);
        } catch (e) { /* fall through to English defaults */ }
        return {};
    }

    function pairMessageFor(error) {
        if (Object.prototype.hasOwnProperty.call(pairText, error)) return pairText[error];
        return pairText["default"] || "Pairing could not be completed. Review the current facts and retry.";
    }

    function pairValidateCode(code) {
        if (typeof code !== "string" || code.length !== 8) return false;
        for (var i = 0; i < code.length; i++) {
            if (PAIR_ALPHABET.indexOf(code.charAt(i)) === -1) return false;
        }
        return true;
    }

    function pairParseFragment(hash) {
        if (typeof hash !== "string" || hash.charAt(0) !== "#") return null;
        var body = hash.slice(1);
        if (body.length === 0) return null;
        var params = {};
        var parts = body.split("&");
        for (var i = 0; i < parts.length; i++) {
            var eq = parts[i].indexOf("=");
            if (eq <= 0) return null;
            var key = parts[i].slice(0, eq);
            var value = parts[i].slice(eq + 1);
            if (params.hasOwnProperty(key)) return null; // duplicate key refused
            params[key] = value;
        }
        if (params.v !== "1") return null;
        if (!pairValidateCode(params.code)) return null;
        for (var k in params) {
            if (k !== "v" && k !== "code") return null; // only the two known fields
        }
        return { v: params.v, code: params.code };
    }

    function pairStoreCode(code) {
        try { sessionStorage.setItem(PAIR_STORAGE_KEY, JSON.stringify({ v: 1, code: code })); } catch (e) { /* storage unavailable */ }
    }

    function pairLoadCode() {
        try {
            var raw = sessionStorage.getItem(PAIR_STORAGE_KEY);
            if (!raw) return null;
            var parsed = JSON.parse(raw);
            if (parsed && parsed.v === 1 && pairValidateCode(parsed.code)) return parsed.code;
        } catch (e) { /* ignore */ }
        return null;
    }

    function pairClearCode() {
        try { sessionStorage.removeItem(PAIR_STORAGE_KEY); } catch (e) { /* ignore */ }
    }

    function pairEl(id) { return document.getElementById(id); }

    function pairCsrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.content : "";
    }

    function pairShowStatus(message, kind) {
        var node = pairEl("pair-status");
        if (!node) return;
        node.textContent = message;
        node.className = "pair-status " + (kind || "error");
        node.hidden = false;
    }

    function pairHideStatus() {
        var node = pairEl("pair-status");
        if (!node) return;
        node.hidden = true;
        node.textContent = "";
    }

    function pairShowEntry() {
        var entry = pairEl("pair-entry");
        var review = pairEl("pair-review");
        if (entry) entry.hidden = false;
        if (review) review.hidden = true;
    }

    function pairUpdateControls() {
        var busy = pairState.lookupBusy || pairState.decisionBusy;
        ["pair-form", "pair-approve", "pair-deny"].forEach(function (id) {
            var node = pairEl(id);
            if (node) {
                node.disabled = busy;
                node.setAttribute("aria-busy", busy ? "true" : "false");
            }
        });
        var input = pairEl("pair-code");
        if (input) input.disabled = pairState.lookupBusy;
        var cancel = pairEl("pair-cancel");
        if (cancel) {
            cancel.hidden = !(pairState.lookupBusy || pairState.review !== null);
            // Cancelling an in-flight explicit decision cannot undo a request the
            // server may already have processed, so cancellation is disabled then.
            cancel.disabled = pairState.decisionBusy;
        }
    }

    function pairStateLabel(state) {
        if (state === "pending") return pairText["state_pending"] || "Pending";
        if (state === "approved") return pairText["state_approved"] || "Approved";
        if (state === "denied") return pairText["state_denied"] || "Denied";
        return state || "";
    }

    function pairShowReview(review) {
        pairEl("pair-review-device").textContent = review.device_id || "";
        pairEl("pair-review-group").textContent = review.group_id || "";
        pairEl("pair-review-server").textContent = review.server_id || "";
        pairEl("pair-review-origin").textContent = review.origin || "";
        pairEl("pair-review-profile").textContent = review.profile || "";
        pairEl("pair-review-code").textContent = pairState.code || "";
        pairEl("pair-review-state").textContent = pairStateLabel(review.state);
        pairEl("pair-review-expires").textContent = review.expires_at
            ? new Date(review.expires_at * 1000).toISOString() : "";
        var decisions = pairEl("pair-decisions");
        var already = pairEl("pair-review-already");
        var pending = review.state === "pending";
        if (decisions) decisions.hidden = !pending;
        if (already) {
            already.hidden = pending;
            already.textContent = pending ? "" : (pairText["already_decided"] || "This request was already decided.");
        }
        pairEl("pair-entry").hidden = true;
        pairEl("pair-review").hidden = false;
    }

    async function pairRequest(path, options) {
        var controller = typeof AbortController !== "undefined" ? new AbortController() : null;
        var timer = null;
        if (controller) {
            options.signal = controller.signal;
            timer = setTimeout(function () { controller.abort(); }, PAIR_TIMEOUT_MS);
        }
        try {
            var response = await fetch(path, options);
            var contentType = response.headers.get("content-type") || "";
            if (contentType.indexOf("application/json") === -1) {
                // A followed login redirect or an authentication refusal sends the
                // administrator back to the fixed login target. Other HTML errors
                // (for example a 5xx proxy page) stay a visible retryable error.
                if (response.redirected || response.status === 401 || response.status === 403
                        || response.status === 302) {
                    return { redirect: true, status: response.status };
                }
                return { error: "invalid_response" };
            }
            var data;
            try {
                data = await response.json();
            } catch (e) {
                return { error: "invalid_response" };
            }
            if (!response.ok) return { error: (data && data.error) || "default", data: data };
            return { data: data };
        } catch (e) {
            return { error: "network_error" };
        } finally {
            if (timer !== null) clearTimeout(timer);
        }
    }

    async function pairLookup(code) {
        var result = await pairRequest("/admin/devices/pair/lookup", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-CSRF-Token": pairCsrfToken() },
            body: JSON.stringify({ code: code }),
            credentials: "same-origin",
            cache: "no-store",
        });
        if (result.redirect) return { redirect: true };
        if (result.error) return { error: result.error };
        if (!result.data || !result.data.review) return { error: "invalid_response" };
        return { review: result.data.review };
    }

    async function pairDecide(requestId, code, bindingSha256, decision) {
        var result = await pairRequest("/admin/devices/" + encodeURIComponent(requestId) + "/decision", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-CSRF-Token": pairCsrfToken() },
            body: JSON.stringify({ user_code: code, binding_sha256: bindingSha256, decision: decision }),
            credentials: "same-origin",
            cache: "no-store",
        });
        if (result.redirect) return { redirect: true };
        if (result.error) return { ok: false, error: result.error };
        return { ok: true, result: result.data };
    }

    function pairBeginLookup(code) {
        var seq = ++pairState.lookupSeq;
        pairState.decisionSeq++;
        pairState.code = code;
        pairState.review = null;
        pairState.lookupBusy = true;
        pairState.decisionBusy = false;
        pairShowEntry();
        pairShowStatus(pairText["checking"] || "Checking the code\u2026", "loading");
        pairUpdateControls();
        pairLookup(code).then(function (result) {
            if (seq !== pairState.lookupSeq) return; // obsolete response
            pairState.lookupBusy = false;
            pairUpdateControls();
            if (result.redirect) {
                window.location.assign("/admin/login?next=pair");
                return;
            }
            if (result.error) {
                if (result.error === "invalid_user_code" || result.error === "unknown_code"
                        || result.error === "enrollment_expired") {
                    pairClearCode();
                    pairState.code = null;
                    var staleInput = pairEl("pair-code");
                    if (staleInput) staleInput.value = "";
                }
                pairShowStatus(pairMessageFor(result.error), "error");
                pairShowEntry();
                pairUpdateControls();
                return;
            }
            pairState.review = result.review;
            pairShowReview(result.review);
            pairHideStatus();
            pairUpdateControls();
        });
    }

    function pairSubmitDecision(decision) {
        if (!pairState.review || pairState.review.state !== "pending"
                || !pairState.code || pairState.lookupBusy || pairState.decisionBusy) return;
        var seq = ++pairState.decisionSeq;
        // Snapshot the currently reviewed request; a newer lookup invalidates it.
        var requestId = pairState.review.request_id;
        var code = pairState.code;
        var bindingSha256 = pairState.review.binding_sha256;
        pairState.decisionBusy = true;
        pairShowStatus(pairText["sending"] || "Sending the decision\u2026", "loading");
        pairUpdateControls();
        pairDecide(requestId, code, bindingSha256, decision).then(function (result) {
            if (seq !== pairState.decisionSeq) return; // superseded/cancelled
            pairState.decisionBusy = false;
            pairUpdateControls();
            if (result.redirect) {
                window.location.assign("/admin/login?next=pair");
                return;
            }
            if (result.ok) {
                pairClearCode();
                pairState.code = null;
                pairState.review = null;
                pairEl("pair-entry").hidden = true;
                pairEl("pair-review").hidden = true;
                pairShowStatus(decision === "approve"
                    ? (pairText["approved"] || "Device approved. The client polling will now complete enrollment.")
                    : (pairText["denied"] || "Request denied. The client polling will now receive the denial."),
                    "success");
                pairUpdateControls();
                return;
            }
            if (result.error === "decision_conflict" || result.error === "approval_no_longer_active"
                    || result.error === "binding_refused" || result.error === "enrollment_expired") {
                // The reviewed request is no longer authoritative; require a fresh review.
                pairState.review = null;
                pairShowEntry();
            }
            pairShowStatus(pairMessageFor(result.error), "error");
            pairUpdateControls();
        });
    }

    function pairCancel() {
        if (pairState.decisionBusy) return; // never race an explicit decision
        pairState.lookupSeq++;
        pairState.decisionSeq++;
        pairState.lookupBusy = false;
        pairState.review = null;
        pairState.code = null;
        pairClearCode();
        var input = pairEl("pair-code");
        if (input) input.value = "";
        pairShowEntry();
        pairShowStatus(pairText["cancelled"] || "Pairing review cancelled. No decision was sent.", "info");
        pairUpdateControls();
    }

    function pairInit() {
        var form = pairEl("pair-form");
        var input = pairEl("pair-code");
        if (form && form.addEventListener) {
            form.addEventListener("submit", function (event) {
                if (event && event.preventDefault) event.preventDefault();
                if (pairState.lookupBusy) return;
                var code = (input.value || "").toUpperCase();
                input.value = code;
                if (!pairValidateCode(code)) {
                    pairShowStatus(pairMessageFor("invalid_user_code"), "error");
                    return;
                }
                pairStoreCode(code);
                pairBeginLookup(code);
            });
        }
        var approve = pairEl("pair-approve");
        var deny = pairEl("pair-deny");
        var cancel = pairEl("pair-cancel");
        if (approve) approve.addEventListener("click", function () { pairSubmitDecision("approve"); });
        if (deny) deny.addEventListener("click", function () { pairSubmitDecision("deny"); });
        if (cancel) cancel.addEventListener("click", pairCancel);

        var code = null;
        var parsed = pairParseFragment(window.location.hash || "");
        if (parsed) {
            code = parsed.code;
            pairStoreCode(code);
            try {
                history.replaceState(null, "", window.location.pathname + window.location.search);
            } catch (e) { /* ignore */ }
        } else {
            code = pairLoadCode();
        }
        if (code) {
            pairBeginLookup(code);
        } else {
            pairShowEntry();
            pairUpdateControls();
        }
    }

    // Exposed pure helpers and bounded actions for the offline test harness.
    var api = {
        validateCode: pairValidateCode,
        parseFragment: pairParseFragment,
        lookup: pairLookup,
        decide: pairDecide,
        messageFor: pairMessageFor,
        begin: pairBeginLookup,
        decideRequest: pairSubmitDecision,
        cancel: pairCancel,
        state: pairState,
    };
    if (typeof window !== "undefined") window.KioskPair = api;

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", pairInit);
    } else {
        pairInit();
    }
})();
