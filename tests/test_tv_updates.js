const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function event(id, title, image = "") {
    return { id, title, image_tv: image, event_date: "2026-11-01", place: "Hall", short_description: "Description" };
}

async function display(initialEvents) {
    let version = 1;
    let events = initialEvents;
    let timerId = 0;
    const timers = new Map();
    const classes = () => ({ add() {}, remove() {}, toggle() {} });
    const elements = Object.fromEntries(["card", "image", "date", "title", "place", "description", "version", "empty-state"].map(name => [
        `[data-tv-${name}]`, { textContent: "", hidden: false, innerHTML: "", style: {}, classList: classes() },
    ]));
    elements[".tv-screen"] = {
        classList: classes(),
        dataset: { slideDuration: "10000", versionPollInterval: "10000", updateDelayMax: "0", versionLabel: "Version", imageArea: "Image area" },
    };
    const context = vm.createContext({
        document: { querySelector: selector => elements[selector] || null, addEventListener() {} },
        window: {
            setInterval() {},
            setTimeout(callback, delay) { timers.set(++timerId, { callback, delay }); return timerId; },
            clearTimeout(id) { timers.delete(id); },
        },
        Image: class {
            set src(value) { this.onload(); }
        },
        fetch: async url => ({ json: async () => url === "/api/version" ? { content_version: version } : { events } }),
    });
    async function settle() {
        for (let index = 0; index < 20; index += 1) await Promise.resolve();
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
        advance,
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
    console.log("TV edits, image updates, slideshow transitions, hidden events, and empty-state recovery passed.");
}

run().catch(error => { console.error(error); process.exitCode = 1; });
