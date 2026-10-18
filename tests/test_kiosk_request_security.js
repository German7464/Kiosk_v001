const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

async function run() {
    let exits = 0;
    let reply = { success: false, error: "Request expired" };
    let lastRequest;
    const error = { hidden: true, textContent: "", dataset: { invalidMessage: "Invalid password" } };
    const password = { value: "test-password", focus() {} };
    const elements = {
        "[data-kiosk-home]": { dataset: { versionPollInterval: "1000", updateDelayMax: "10" } },
        "[data-kiosk-unlock-modal]": { hidden: false },
        "[data-kiosk-unlock-form]": { addEventListener() {}, reset() {} },
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
            lastRequest = { url, options };
            return { json: async () => reply };
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
    reply = { success: true };
    assert.equal(await vm.runInContext("requestKioskFullscreenExit()", context), true);
    assert.equal(exits, 1);
    console.log("Kiosk CSRF header, error handling, and fullscreen authorization checks passed.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
