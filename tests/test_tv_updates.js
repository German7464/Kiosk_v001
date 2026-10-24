const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function event(id, title, image = "") {
    return { id, title, image_tv: image, event_date: "2026-11-01", place: "Hall", short_description: "Description" };
}

async function display(initialEvents, options = {}) {
    let version = 1;
    let events = initialEvents;
    let timerId = 0;
    const timers = new Map();
    const requests = [];
    let respond = options.respond;
    let pollCallback;
    const classes = () => ({ add() {}, remove() {}, toggle() {} });
    const elements = Object.fromEntries(["card", "image", "date", "title", "place", "description", "version", "empty-state"].map(name => [
        `[data-tv-${name}]`, { textContent: "", hidden: false, innerHTML: "", style: {}, classList: classes() },
    ]));
    elements[".tv-screen"] = {
        classList: classes(),
        dataset: { slideDuration: "10000", versionPollInterval: "10000", updateDelayMax: "0", versionLabel: "Version", versionUnavailable: "Version unavailable", imageArea: "Image area" },
    };
    const context = vm.createContext({
        document: { querySelector: selector => elements[selector] || null, addEventListener() {} },
        window: {
            setInterval(callback, delay) { assert.equal(delay, 10000); pollCallback = callback; },
            setTimeout(callback, delay) { timers.set(++timerId, { callback, delay }); return timerId; },
            clearTimeout(id) { timers.delete(id); },
        },
        Image: class {
            set src(value) { this.onload(); }
        },
        fetch: async url => {
            requests.push(url);
            const response = respond ? await respond(url) : undefined;
            return response || { ok: true, json: async () => url === "/api/version" ? { content_version: version } : { events } };
        },
    });
    async function settle() {
        for (let index = 0; index < 40; index += 1) await Promise.resolve();
    }
    async function advance(delay) {
        const ready = [...timers.entries()].filter(([, timer]) => timer.delay === delay);
        for (const [id, timer] of ready) {
            timers.delete(id);
            timer.callback();
        }
        await settle();
    }
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../kiosk/static/js/tv.js"), "utf8"), context);
    await settle();
    await advance(220);
    return {
        elements,
        timers,
        requests,
        advance,
        respond(callback) { respond = callback; },
        setVersion(value) { version = value; },
        async tick() { pollCallback(); await settle(); },
        async poll() { pollCallback(); await settle(); await advance(0); await advance(220); },
        async update(nextEvents) {
            events = nextEvents;
            version += 1;
            await vm.runInContext("pollTvVersion()", context);
            await advance(0);
            await advance(220);
        },
        async nextSlide() {
            const timer = [...timers.values()].find(value => value.delay >= 8000);
            assert.ok(timer, "A slideshow timer must be scheduled");
            await advance(timer.delay);
            await advance(220);
        },
    };
}

async function run() {
    const single = await display([event(1, "Original", "/old.jpg")]);
    await single.update([event(1, "Edited", "/new.jpg")]);
    assert.equal(single.elements["[data-tv-title]"].textContent, "Edited");
    assert.equal(single.elements["[data-tv-image]"].style.backgroundImage, 'url("/new.jpg")');
    assert.equal(single.elements["[data-tv-version]"].textContent, "Version 2");
    await single.update([event(1, "Edited"), event(2, "Second")]);
    assert.equal(single.elements["[data-tv-title]"].textContent, "Edited");
    await single.nextSlide();
    assert.equal(single.elements["[data-tv-title]"].textContent, "Second");

    const multiple = await display([event(1, "First"), event(2, "Second"), event(3, "Third")]);
    await multiple.update([event(3, "Third"), event(1, "First edited"), event(2, "Second")]);
    assert.equal(multiple.elements["[data-tv-title]"].textContent, "First edited");
    await multiple.nextSlide();
    assert.equal(multiple.elements["[data-tv-title]"].textContent, "Second");
    await multiple.update([event(3, "Third"), event(1, "First edited")]);
    assert.equal(multiple.elements["[data-tv-title]"].textContent, "Third");
    await multiple.update([]);
    assert.equal(multiple.elements["[data-tv-card]"].hidden, true);
    assert.equal(multiple.elements["[data-tv-empty-state]"].hidden, false);
    assert.equal([...multiple.timers.values()].filter(timer => timer.delay >= 8000).length, 0);
    await multiple.update([event(4, "Restored")]);
    assert.equal(multiple.elements["[data-tv-title]"].textContent, "Restored");
    assert.equal(multiple.elements["[data-tv-card]"].hidden, false);
    assert.equal(multiple.elements["[data-tv-empty-state]"].hidden, true);

    const initiallyOffline = await display([event(1, "Recovered startup")], { respond: async () => { throw new Error("Offline"); } });
    assert.equal(initiallyOffline.elements["[data-tv-version]"].textContent, "Version unavailable");
    initiallyOffline.respond(null);
    await initiallyOffline.poll();
    assert.equal(initiallyOffline.elements["[data-tv-title]"].textContent, "Recovered startup");
    assert.equal(initiallyOffline.elements["[data-tv-version]"].textContent, "Version 1");
    assert.equal(initiallyOffline.elements["[data-tv-card]"].hidden, false);

    const initiallyUnavailableEvents = await display([event(1, "Recovered events")], {
        respond: async url => url === "/api/events" ? { ok: false } : undefined,
    });
    initiallyUnavailableEvents.respond(null);
    await initiallyUnavailableEvents.poll();
    assert.equal(initiallyUnavailableEvents.elements["[data-tv-title]"].textContent, "Recovered events");

    const reconnecting = await display([event(1, "Keep showing"), event(2, "Keep rotating")]);
    reconnecting.respond(async () => { throw new Error("Offline"); });
    await reconnecting.poll();
    assert.equal(reconnecting.elements["[data-tv-version]"].textContent, "Version unavailable");
    await reconnecting.nextSlide();
    assert.equal(reconnecting.elements["[data-tv-title]"].textContent, "Keep rotating");
    const beforeReconnect = reconnecting.requests.filter(url => url === "/api/events").length;
    reconnecting.respond(null);
    await reconnecting.poll();
    assert.equal(reconnecting.elements["[data-tv-version]"].textContent, "Version 1");
    assert.equal(reconnecting.elements["[data-tv-title]"].textContent, "Keep rotating");
    assert.equal(reconnecting.requests.filter(url => url === "/api/events").length, beforeReconnect);

    const damagedResponses = [
        { ok: false, json: async () => ({ events: [] }) },
        { ok: true, json: async () => { throw new SyntaxError("Invalid JSON"); } },
        { ok: true, json: async () => ({}) },
        { ok: true, json: async () => ({ events: [null] }) },
        { ok: true, json: async () => ({ events: [event(1, "Bad fields"), { id: 2, title: "Bad", short_description: {} }] }) },
    ];
    for (const response of damagedResponses) {
        const recovering = await display([event(1, "Preserved")]);
        recovering.respond(async url => url === "/api/events" ? response : undefined);
        await recovering.update([event(1, "After recovery")]);
        assert.equal(recovering.elements["[data-tv-title]"].textContent, "Preserved");
        assert.equal(recovering.elements["[data-tv-card]"].hidden, false);
        assert.equal(recovering.elements["[data-tv-version]"].textContent, "Version unavailable");
        recovering.respond(null);
        await recovering.poll();
        assert.equal(recovering.elements["[data-tv-title]"].textContent, "After recovery");
        assert.equal(recovering.elements["[data-tv-version]"].textContent, "Version 2");
    }

    for (const response of [{ ok: false }, { ok: true, json: async () => ({ content_version: "1" }) }, { ok: true, json: async () => ({ content_version: -1 }) }]) {
        const recovering = await display([event(1, "Stable")]);
        recovering.respond(async url => url === "/api/version" ? response : undefined);
        await recovering.poll();
        assert.equal(recovering.elements["[data-tv-version]"].textContent, "Version unavailable");
        assert.equal(recovering.elements["[data-tv-title]"].textContent, "Stable");
        recovering.respond(null);
        await recovering.poll();
        assert.equal(recovering.elements["[data-tv-version]"].textContent, "Version 1");
    }

    const delayed = await display([event(1, "Before delay")]);
    delayed.setVersion(2);
    let resolveVersion;
    delayed.respond(url => url === "/api/version" ? new Promise(resolve => { resolveVersion = resolve; }) : undefined);
    const requestsBefore = delayed.requests.length;
    await delayed.tick();
    await delayed.tick();
    assert.equal(delayed.requests.length, requestsBefore + 1);
    resolveVersion({ ok: true, json: async () => ({ content_version: 2 }) });
    await delayed.tick();
    delayed.respond(null);
    await delayed.tick();
    assert.equal([...delayed.timers.values()].filter(timer => timer.delay === 0).length, 1);
    await delayed.advance(0);
    await delayed.advance(220);
    await delayed.poll();
    assert.equal(delayed.elements["[data-tv-version]"].textContent, "Version 2");
    console.log("TV updates, preserved slides, initial/unchanged-version recovery, invalid responses and duplicate-poll protection passed.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
