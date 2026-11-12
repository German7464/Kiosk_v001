const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function deferred() {
    let resolve, reject;
    const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
    return { promise, resolve, reject };
}

function jsonResponse(status, body) {
    return {
        ok: status >= 200 && status < 300,
        status,
        redirected: false,
        headers: { get: () => "application/json; charset=utf-8" },
        json: async () => body,
    };
}

function htmlResponse(status, redirected) {
    return {
        ok: status >= 200 && status < 300,
        status,
        redirected: redirected === undefined ? status === 302 : redirected,
        headers: { get: () => "text/html; charset=utf-8" },
        json: async () => { throw new Error("not json"); },
    };
}

function review(overrides) {
    return Object.assign({
        request_id: "req-a", binding_sha256: "a".repeat(64), device_id: "device-a",
        group_id: "group-a", server_id: "server-a", origin: "https://127.0.0.1:18443",
        profile: "events-phone-lab-v1", nonce: "nonce", expires_at: 1800000600, state: "pending",
    }, overrides || {});
}

async function settle() {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
}

async function run() {
    const elements = {};
    const ids = ["pair-messages", "pair-status", "pair-entry", "pair-review", "pair-form", "pair-code",
        "pair-review-device", "pair-review-group", "pair-review-server", "pair-review-origin",
        "pair-review-profile", "pair-review-code", "pair-review-state", "pair-review-expires",
        "pair-review-already", "pair-decisions", "pair-approve", "pair-deny", "pair-cancel"];
    for (const id of ids) {
        elements[id] = {
            id, hidden: false, disabled: false, value: "", textContent: "", className: "",
            listeners: {}, setAttribute(name, value) { this[name] = value; },
            addEventListener(name, handler) { this.listeners[name] = handler; },
        };
    }
    elements["pair-entry"].hidden = false;
    elements["pair-review"].hidden = true;
    elements["pair-status"].hidden = true;
    elements["pair-cancel"].hidden = true;
    elements["pair-messages"].textContent = JSON.stringify({
        default: "DEFAULT", unknown_code: "UNKNOWN", network_error: "NETWORK",
        invalid_response: "BAD RESPONSE", checking: "CHECK", sending: "SEND",
        cancelled: "CANCELLED", approved: "APPROVED", denied: "DENIED",
        state_pending: "PENDING", state_approved: "APPROVED", state_denied: "DENIED",
        already_decided: "ALREADY", invalid_user_code: "INVALID",
        enrollment_expired: "EXPIRED",
    });

    let assigned = null;
    const windowObj = {
        location: {
            hash: "", pathname: "/admin/devices/pair", search: "",
            assign(url) { assigned = url; },
        },
    };
    const sessionStorage = {
        data: {},
        setItem(k, v) { this.data[k] = String(v); },
        getItem(k) { return Object.prototype.hasOwnProperty.call(this.data, k) ? this.data[k] : null; },
        removeItem(k) { delete this.data[k]; },
    };
    const history = { replaced: [], replaceState(state, title, url) { this.replaced.push(url); } };
    const meta = { content: "page-token" };
    const document = {
        readyState: "loading",
        addEventListener() {},
        querySelector(selector) { return selector === 'meta[name="csrf-token"]' ? meta : null; },
        getElementById(id) { return elements[id] || null; },
    };
    const requests = [];
    let queue = [];

    const context = vm.createContext({
        document, window: windowObj, sessionStorage, history, location: windowObj.location,
        AbortController, setTimeout, clearTimeout, console,
        fetch: async (url, options) => {
            requests.push({ url, options });
            if (!queue.length) throw new Error("no queued response");
            const next = queue.shift();
            if (next instanceof Error) throw next;
            if (typeof next === "function") return next();
            return next;
        },
    });

    vm.runInContext(fs.readFileSync(path.join(__dirname, "../kiosk/static/js/admin_pair.js"), "utf8"), context);
    const api = windowObj.KioskPair;
    assert.ok(api, "KioskPair exposed");

    // validateCode
    for (const code of ["ABCDEFGH", "23456789", "KQ7WMN4X", "ZYXWVUTS"]) assert.equal(api.validateCode(code), true, code);
    for (const code of ["", "ABCDEFG", "ABCDEFGHI", "abcdefgh", "0BCDEFGH", "1BCDEFGH", "ABCDIFGH", "ABCDOFGH", "ABC=EFGH", null, 123]) {
        assert.equal(api.validateCode(code), false, JSON.stringify(code));
    }

    // parseFragment
    assert.equal(JSON.stringify(api.parseFragment("#v=1&code=ABCDEFGH")), JSON.stringify({ v: "1", code: "ABCDEFGH" }));
    assert.equal(JSON.stringify(api.parseFragment("#v=1&code=23456789")), JSON.stringify({ v: "1", code: "23456789" }));
    for (const bad of ["", "#v=2&code=ABCDEFGH", "#v=1", "#v=1&code=SHORT", "#v=1&code=0BCDEFGH",
                       "#v=1&code=ABCDEFGH&extra=x", "#v=1&code=ABCDEFGH&code=23456789",
                       "#v=1&code=", "#v=1&code=ABCDEFGH&", "v=1&code=ABCDEFGH", "#v=1&code=abcdefgh"]) {
        assert.equal(api.parseFragment(bad), null, JSON.stringify(bad));
    }

    // Localized messages are taken from the page, not hard-coded English.
    assert.equal(api.messageFor("unknown_code"), "UNKNOWN");
    assert.equal(api.messageFor("network_error"), "NETWORK");
    assert.equal(api.messageFor("weird"), "DEFAULT");

    // lookup: exact request + JSON success
    queue = [jsonResponse(200, { review: review() })];
    let result = await api.lookup("ABCDEFGH");
    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, "/admin/devices/pair/lookup");
    assert.equal(requests[0].options.method, "POST");
    assert.equal(requests[0].options.headers["Content-Type"], "application/json");
    assert.equal(requests[0].options.headers["X-CSRF-Token"], "page-token");
    assert.equal(requests[0].options.body, JSON.stringify({ code: "ABCDEFGH" }));
    assert.equal(JSON.stringify(result), JSON.stringify({ review: review() }));

    // lookup: JSON error surfaces the server code
    queue = [jsonResponse(404, { error: "unknown_code" })];
    result = await api.lookup("ZZZZZZZZ");
    assert.equal(JSON.stringify(result), JSON.stringify({ error: "unknown_code" }));

    // lookup: followed login redirect is surfaced without parsing
    queue = [htmlResponse(200, true)];
    result = await api.lookup("ABCDEFGH");
    assert.equal(JSON.stringify(result), JSON.stringify({ redirect: true }));

    // lookup: an HTML 5xx page is a visible retryable error, not a login redirect.
    queue = [htmlResponse(503, false)];
    result = await api.lookup("ABCDEFGH");
    assert.equal(JSON.stringify(result), JSON.stringify({ error: "invalid_response" }));

    // lookup: invalid JSON is a bounded error, not an unhandled rejection
    queue = [{ headers: { get: () => "application/json" }, ok: true, status: 200, json: async () => { throw new Error("bad"); } }];
    result = await api.lookup("ABCDEFGH");
    assert.equal(JSON.stringify(result), JSON.stringify({ error: "invalid_response" }));

    // A terminal lookup error clears the stale code and input, not just the review.
    sessionStorage.setItem("kiosk.pair", JSON.stringify({ v: 1, code: "AAAAAAAA" }));
    elements["pair-code"].value = "AAAAAAAA";
    queue = [jsonResponse(404, { error: "unknown_code" })];
    api.begin("AAAAAAAA");
    await settle();
    assert.equal(api.state.code, null);
    assert.equal(elements["pair-code"].value, "");
    assert.equal(sessionStorage.getItem("kiosk.pair"), null);
    assert.equal(elements["pair-status"].textContent, "UNKNOWN");

    // Network failure: busy clears, the entry stays usable and the code is retained for retry.
    requests.length = 0;
    queue = [new Error("offline"), jsonResponse(200, { review: review() })];
    api.begin("ABCDEFGH");
    assert.equal(api.state.lookupBusy, true);
    await settle();
    assert.equal(api.state.lookupBusy, false);
    assert.equal(elements["pair-status"].textContent, "NETWORK");
    assert.equal(elements["pair-entry"].hidden, false);
    assert.equal(api.state.code, "ABCDEFGH");
    assert.equal(elements["pair-form"].disabled, false);
    assert.equal(elements["pair-cancel"].hidden, true);
    api.begin("ABCDEFGH");
    await settle();
    assert.equal(api.state.lookupBusy, false);
    assert.equal(elements["pair-review"].hidden, false);
    assert.equal(elements["pair-review-device"].textContent, "device-a");
    assert.equal(elements["pair-review-code"].textContent, "ABCDEFGH");
    assert.equal(elements["pair-decisions"].hidden, false);

    // Out-of-order lookups: a late older answer never replaces the newer review.
    const first = deferred();
    const second = deferred();
    requests.length = 0;
    queue = [() => first.promise, () => second.promise];
    api.begin("AAAAAAAA");
    api.begin("BBBBBBBB");
    second.resolve(jsonResponse(200, { review: review({ request_id: "req-b", device_id: "device-b" }) }));
    await settle();
    assert.equal(api.state.code, "BBBBBBBB");
    assert.equal(api.state.review.device_id, "device-b");
    assert.equal(elements["pair-review-device"].textContent, "device-b");
    first.resolve(jsonResponse(200, { review: review({ request_id: "req-a", device_id: "device-a" }) }));
    await settle();
    assert.equal(api.state.code, "BBBBBBBB");
    assert.equal(api.state.review.device_id, "device-b");
    assert.equal(elements["pair-review-device"].textContent, "device-b");

    // Decision rejection: the reviewed request stays visible and retry is possible.
    requests.length = 0;
    queue = [new Error("offline"), jsonResponse(200, { state: "approved" })];
    api.decideRequest("approve");
    assert.equal(api.state.decisionBusy, true);
    assert.equal(elements["pair-cancel"].disabled, true);
    await settle();
    assert.equal(api.state.decisionBusy, false);
    assert.equal(api.state.review.device_id, "device-b");
    assert.equal(elements["pair-review"].hidden, false);
    assert.equal(elements["pair-approve"].disabled, false);
    assert.equal(elements["pair-deny"].disabled, false);
    assert.equal(elements["pair-status"].textContent, "NETWORK");
    assert.equal(requests[0].url, "/admin/devices/req-b/decision");
    assert.deepEqual(JSON.parse(requests[0].options.body), {
        user_code: "BBBBBBBB", binding_sha256: "a".repeat(64), decision: "approve",
    });
    api.decideRequest("approve");
    await settle();
    assert.equal(api.state.review, null);
    assert.equal(api.state.code, null);
    assert.equal(elements["pair-status"].textContent, "APPROVED");
    assert.equal(elements["pair-cancel"].hidden, true);
    assert.equal(sessionStorage.getItem("kiosk.pair"), null);

    // Cancel/reset: no decision request is sent and the stored code is cleared.
    requests.length = 0;
    queue = [jsonResponse(200, { review: review() })];
    api.begin("CDEFGHJK");
    await settle();
    assert.equal(elements["pair-review"].hidden, false);
    requests.length = 0;
    api.cancel();
    await settle();
    assert.equal(requests.length, 0, "cancel must not call lookup or decision");
    assert.equal(api.state.review, null);
    assert.equal(api.state.code, null);
    assert.equal(elements["pair-review"].hidden, true);
    assert.equal(elements["pair-entry"].hidden, false);
    assert.equal(elements["pair-status"].textContent, "CANCELLED");
    assert.equal(sessionStorage.getItem("kiosk.pair"), null);
    assert.equal(elements["pair-cancel"].hidden, true);

    // Already-decided review shows facts but no approval controls.
    queue = [jsonResponse(200, { review: review({ state: "approved" }) })];
    api.begin("EFGHJKLM");
    await settle();
    assert.equal(elements["pair-review"].hidden, false);
    assert.equal(elements["pair-review-state"].textContent, "APPROVED");
    assert.equal(elements["pair-decisions"].hidden, true);
    assert.equal(elements["pair-review-already"].hidden, false);
    assert.equal(elements["pair-review-already"].textContent, "ALREADY");
    api.cancel();

    // Cancel during an unresolved lookup makes its late response inert.
    const pending = deferred();
    requests.length = 0;
    queue = [() => pending.promise];
    api.begin("GHJKLMNP");
    api.cancel();
    pending.resolve(jsonResponse(200, { review: review() }));
    await settle();
    assert.equal(api.state.lookupBusy, false);
    assert.equal(api.state.review, null);
    assert.equal(elements["pair-review"].hidden, true);
    assert.equal(elements["pair-status"].textContent, "CANCELLED");

    console.log("admin_pair.js: all assertions passed");
}

run().catch((error) => { console.error(error); process.exit(1); });
