const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

async function run() {
    let exits = 0;
    let reply = { success: false, error: "Request expired" };
    let lastRequest;
    let status = 200;
    let refreshReply = { csrf_token: "a".repeat(64) };
    let refreshFailure = false;
    let refreshOk = true;
    let refreshRequests = 0;
    let posts = 0;
    let release;
    let waitForPost = false;
    const submit = { disabled: false };
    const error = { hidden: true, textContent: "", dataset: { invalidMessage: "Invalid password", refreshedMessage: "Enter password again", refreshFailedMessage: "Refresh failed" } };
    const password = { value: "test-password", focus() {} };
    const elements = {
        "[data-kiosk-home]": { dataset: { versionPollInterval: "1000", updateDelayMax: "10" } },
        "[data-kiosk-unlock-modal]": { hidden: false },
        "[data-kiosk-unlock-form]": { addEventListener() {}, reset() {}, querySelector() { return submit; } },
        "[data-kiosk-unlock-error]": error,
        "[data-kiosk-unlock-username]": { value: "admin" },
        "[data-kiosk-unlock-password]": password,
        "[data-kiosk-unlock-return]": { addEventListener() {} },
        'meta[name="csrf-token"]': { content: "page-token" },
    };
    const context = vm.createContext({
        document: {
            querySelector(selector) { return elements[selector] || null; },
            addEventListener() {},
            fullscreenElement: {},
            exitFullscreen() { exits += 1; },
        },
        window: { setInterval() {}, setTimeout() {}, location: { reload() {} } },
        fetch: async (url, options) => {
            if (url === "/api/version") return { json: async () => ({ content_version: 1 }) };
            if (url === "/admin/fullscreen/csrf") {
                refreshRequests += 1;
                assert.equal(password.value, "");
                assert.equal(options.cache, "no-store");
                assert.equal(options.credentials, "same-origin");
                if (refreshFailure) throw new Error("offline");
                return { ok: refreshOk, json: async () => refreshReply };
            }
            posts += 1;
            lastRequest = { url, options };
            if (waitForPost) await new Promise(resolve => { release = resolve; });
            return { status, ok: status >= 200 && status < 300, json: async () => reply };
        },
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../kiosk/static/js/kiosk_home.js"), "utf8"), context);
    for (const message of ["Request expired", "Too many password checks"]) {
        reply = { success: false, error: message };
        assert.equal(await vm.runInContext("requestKioskFullscreenExit()", context), false);
        assert.equal(error.textContent, message);
        assert.equal(error.hidden, false);
        assert.equal(password.value, "");
        assert.equal(exits, 0);
    }
    assert.equal(lastRequest.url, "/admin/fullscreen/validate");
    assert.equal(lastRequest.options.method, "POST");
    assert.equal(lastRequest.options.headers["X-CSRF-Token"], "page-token");
    reply = { success: false };
    await vm.runInContext("requestKioskFullscreenExit()", context);
    assert.equal(error.textContent, "Invalid password");
    for (const failure of [false, true, false]) {
        status = 403;
        reply = { success: false, code: "csrf_expired" };
        refreshFailure = failure;
        password.value = "must-not-replay";
        const before = posts;
        assert.equal(await vm.runInContext("requestKioskFullscreenExit()", context), false);
        assert.equal(posts, before + 1);
        assert.equal(error.textContent, failure ? "Refresh failed" : "Enter password again");
        assert.equal(password.value, "");
        assert.equal(exits, 0);
        assert.equal(submit.disabled, false);
    }
    assert.equal(refreshRequests, 3);
    assert.equal(elements['meta[name="csrf-token"]'].content, "a".repeat(64));
    refreshReply = { csrf_token: "invalid" };
    await vm.runInContext("requestKioskFullscreenExit()", context);
    assert.equal(error.textContent, "Refresh failed");
    assert.equal(elements['meta[name="csrf-token"]'].content, "a".repeat(64));
    refreshOk = false;
    await vm.runInContext("requestKioskFullscreenExit()", context);
    assert.equal(error.textContent, "Refresh failed");
    refreshOk = true;
    status = 429;
    reply = { success: false, code: "csrf_expired", error: "Rate limited" };
    const beforeRefresh = refreshRequests;
    await vm.runInContext("requestKioskFullscreenExit()", context);
    assert.equal(refreshRequests, beforeRefresh);
    assert.equal(error.textContent, "Rate limited");
    status = 200;
    reply = { success: false };
    waitForPost = true;
    const pending = vm.runInContext("requestKioskFullscreenExit()", context);
    assert.equal(submit.disabled, true);
    const beforeDuplicate = posts;
    assert.equal(await vm.runInContext("requestKioskFullscreenExit()", context), false);
    assert.equal(posts, beforeDuplicate);
    release();
    await pending;
    waitForPost = false;
    assert.equal(submit.disabled, false);
    reply = { success: true };
    assert.equal(await vm.runInContext("requestKioskFullscreenExit()", context), true);
    assert.equal(exits, 1);
    console.log("Kiosk CSRF header, error handling, and fullscreen authorization checks passed.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
