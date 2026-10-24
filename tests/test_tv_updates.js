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
    const signals = [];
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
        fetch: async (url, settings) => {
            requests.push(url);
            signals.push(settings && settings.signal);
            const response = respond ? await respond(url, settings) : undefined;
            return response || { ok: true, json: async () => url === "/api/version" ? { content_version: version } : { events } };
        },
    });
    if (options.abortController) context.AbortController = AbortController;
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
        signals,
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

    for (const abortController of [false, true]) {
        for (const bodyPending of [false, true]) {
            let release;
            const startup = await display([event(1, "Recovered timeout")], {
                abortController,
                respond: url => {
                    if (url !== "/api/events") return undefined;
                    const pending = new Promise(resolve => { release = resolve; });
                    return bodyPending ? { ok: true, json: () => pending } : pending;
                },
            });
            assert.equal(startup.elements["[data-tv-title]"].textContent, "");
            const initialRequests = startup.requests.length;
            await startup.tick();
            assert.equal(startup.requests.length, initialRequests);
            await startup.advance(10000);
            assert.equal(startup.elements["[data-tv-version]"].textContent, "Version unavailable");
            if (abortController) assert.equal(startup.signals[1].aborted, true);
            startup.respond(null);
            await startup.poll();
            assert.equal(startup.elements["[data-tv-title]"].textContent, "Recovered timeout");
            const lateEvents = { events: [event(9, "Late startup")] };
            release(bodyPending ? lateEvents : { ok: true, json: async () => lateEvents });
            await startup.tick();
            assert.equal(startup.elements["[data-tv-title]"].textContent, "Recovered timeout");
            assert.equal(startup.timers.size, 0);
        }

        const polling = await display([event(1, "Still rotating"), event(2, "Second slide")], { abortController });
        assert.equal([...polling.timers.values()].filter(timer => timer.delay === 10000).length, 0);
        if (abortController) assert.ok(polling.signals.every(signal => !signal.aborted));
        let releasePoll;
        polling.respond(() => new Promise(resolve => { releasePoll = resolve; }));
        await polling.tick();
        const pendingRequests = polling.requests.length;
        await polling.tick();
        assert.equal(polling.requests.length, pendingRequests);
        await polling.advance(10000);
        assert.equal(polling.elements["[data-tv-version]"].textContent, "Version unavailable");
        await polling.nextSlide();
        assert.equal(polling.elements["[data-tv-title]"].textContent, "Second slide");
        polling.respond(null);
        await polling.poll();
        assert.equal(polling.elements["[data-tv-version]"].textContent, "Version 1");
        const beforeLate = polling.requests.length;
        releasePoll({ ok: true, json: async () => ({ content_version: 99 }) });
        await polling.advance(0);
        assert.equal(polling.requests.length, beforeLate);
        assert.equal(polling.elements["[data-tv-version]"].textContent, "Version 1");

        const refreshing = await display([event(1, "Keep card")], { abortController });
        let releaseEvents;
        refreshing.respond(url => url === "/api/events" ? {
            ok: true, json: () => new Promise(resolve => { releaseEvents = resolve; }),
        } : undefined);
        await refreshing.update([event(1, "New card")]);
        assert.equal(refreshing.elements["[data-tv-title]"].textContent, "Keep card");
        await refreshing.advance(10000);
        assert.equal(refreshing.elements["[data-tv-version]"].textContent, "Version unavailable");
        refreshing.respond(null);
        await refreshing.poll();
        assert.equal(refreshing.elements["[data-tv-title]"].textContent, "New card");
        releaseEvents({ events: [event(1, "Late card")] });
        await refreshing.tick();
        assert.equal(refreshing.elements["[data-tv-title]"].textContent, "New card");
        assert.equal(refreshing.timers.size, 0);
    }

    const paired = await display([event(1, "Paired recovery")], {
        respond: url => url === "/api/version" ? { ok: false } : new Promise(() => {}),
    });
    const pairedRequests = paired.requests.length;
    await paired.tick();
    assert.equal(paired.requests.length, pairedRequests);
    await paired.advance(10000);
    assert.equal(paired.elements["[data-tv-version]"].textContent, "Version unavailable");
    paired.respond(null);
    await paired.poll();
    assert.equal(paired.elements["[data-tv-title]"].textContent, "Paired recovery");
    assert.equal(paired.timers.size, 0);

    const rejectedPair = await display([event(1, "Pair stayed busy")]);
    let releasePairedVersion;
    let pairedVersionRequests = 0;
    rejectedPair.respond(url => {
        if (url === "/api/events") return { ok: false };
        pairedVersionRequests += 1;
        return pairedVersionRequests === 1 ? undefined : new Promise(resolve => { releasePairedVersion = resolve; });
    });
    await rejectedPair.update([event(1, "After paired recovery")]);
    const whilePaired = rejectedPair.requests.length;
    await rejectedPair.tick();
    assert.equal(rejectedPair.requests.length, whilePaired);
    await rejectedPair.advance(10000);
    assert.equal(rejectedPair.elements["[data-tv-title]"].textContent, "Pair stayed busy");
    rejectedPair.respond(null);
    await rejectedPair.poll();
    assert.equal(rejectedPair.elements["[data-tv-title]"].textContent, "After paired recovery");
    releasePairedVersion({ ok: true, json: async () => ({ content_version: 50 }) });
    await rejectedPair.advance(0);
    assert.equal(rejectedPair.elements["[data-tv-version]"].textContent, "Version 2");
    assert.equal(rejectedPair.timers.size, 0);
    console.log("TV updates, recovery, request/body deadlines, late responses, timer cleanup and duplicate-poll protection passed.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
