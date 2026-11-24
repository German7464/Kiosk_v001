"use strict";

const assert = require("node:assert/strict");
const {mount} = require("../kiosk/static/js/page_display.js");

class FakeStyle {
    constructor() {
        this.properties = new Map();
    }

    setProperty(name, value) {
        this.properties.set(String(name), String(value));
    }

    getPropertyValue(name) {
        return this.properties.get(String(name)) || "";
    }
}

class FakeNode {
    constructor(documentObject, tagName) {
        this.ownerDocument = documentObject;
        this.tagName = String(tagName).toUpperCase();
        this.className = "";
        this.children = [];
        this.childNodes = this.children;
        this.attributes = new Map();
        this.style = new FakeStyle();
        this.parentNode = null;
        this.listeners = [];
        this.scrollHeight = 0;
        this.clientHeight = 0;
        this.scrollWidth = 0;
        this.clientWidth = 0;
        this.text = "";
    }

    set innerHTML(value) {
        throw new Error("HTML injection is forbidden");
    }

    get innerHTML() {
        throw new Error("HTML injection is forbidden");
    }

    set textContent(value) {
        this.text = String(value);
        this.children.forEach((child) => {
            child.parentNode = null;
        });
        this.children.length = 0;
    }

    get textContent() {
        return this.text + this.children.map((child) => child.textContent).join("");
    }

    set hidden(value) {
        if (value) {
            this.setAttribute("hidden", "");
        } else {
            this.removeAttribute("hidden");
        }
    }

    get hidden() {
        return this.attributes.has("hidden");
    }

    appendChild(node) {
        if (node.parentNode) {
            node.parentNode.removeChild(node);
        }
        node.parentNode = this;
        this.children.push(node);
        return node;
    }

    replaceChildren(...nodes) {
        this.children.forEach((child) => {
            child.parentNode = null;
        });
        this.children.length = 0;
        nodes.forEach((node) => this.appendChild(node));
    }

    removeChild(node) {
        const index = this.children.indexOf(node);
        if (index < 0) {
            throw new Error("Node is not a child");
        }
        this.children.splice(index, 1);
        node.parentNode = null;
        return node;
    }

    remove() {
        if (this.parentNode) {
            this.parentNode.removeChild(this);
        }
    }

    replaceWith(node) {
        if (!this.parentNode) {
            return;
        }
        const parent = this.parentNode;
        const index = parent.children.indexOf(this);
        parent.children[index] = node;
        node.parentNode = parent;
        this.parentNode = null;
    }

    setAttribute(name, value) {
        this.attributes.set(String(name), String(value));
    }

    getAttribute(name) {
        return this.attributes.has(String(name)) ? this.attributes.get(String(name)) : null;
    }

    removeAttribute(name) {
        this.attributes.delete(String(name));
    }

    addEventListener(type, handler, options) {
        this.listeners.push({
            type,
            handler,
            capture: Boolean(options === true || (options && options.capture)),
            once: Boolean(options && options.once),
        });
    }

    removeEventListener(type, handler, capture) {
        const normalizedCapture = Boolean(capture);
        const index = this.listeners.findIndex((entry) => entry.type === type
            && entry.handler === handler && entry.capture === normalizedCapture);
        if (index >= 0) {
            this.listeners.splice(index, 1);
        }
    }

    dispatchEvent(event) {
        const entries = this.listeners.filter((entry) => entry.type === (event.type || "click"));
        entries.forEach((entry) => {
            entry.handler(event);
            if (entry.once) {
                const index = this.listeners.indexOf(entry);
                if (index >= 0) {
                    this.listeners.splice(index, 1);
                }
            }
        });
        return true;
    }

    click() {
        return this.dispatchEvent({type: "click"});
    }
}

class FakeWindow {
    constructor() {
        this.timers = new Map();
        this.listeners = [];
        this.sequence = 0;
        this.fetchCalls = 0;
    }

    setTimeout(callback, delay) {
        const id = ++this.sequence;
        this.timers.set(id, {callback, delay});
        return id;
    }

    clearTimeout(id) {
        this.timers.delete(id);
    }

    addEventListener(type, handler, options) {
        this.listeners.push({type, handler, capture: Boolean(options === true || (options && options.capture))});
    }

    removeEventListener(type, handler, capture) {
        const normalizedCapture = Boolean(capture);
        const index = this.listeners.findIndex((entry) => entry.type === type
            && entry.handler === handler && entry.capture === normalizedCapture);
        if (index >= 0) {
            this.listeners.splice(index, 1);
        }
    }

    fetch() {
        this.fetchCalls += 1;
        throw new Error("Network is forbidden");
    }
}

class FakeDocument {
    constructor(windowObject) {
        this.defaultView = windowObject;
        this.hidden = false;
        this.listeners = [];
    }

    createElement(tagName) {
        return new FakeNode(this, tagName);
    }

    addEventListener(type, handler, options) {
        this.listeners.push({type, handler, capture: Boolean(options === true || (options && options.capture))});
    }

    removeEventListener(type, handler, capture) {
        const normalizedCapture = Boolean(capture);
        const index = this.listeners.findIndex((entry) => entry.type === type
            && entry.handler === handler && entry.capture === normalizedCapture);
        if (index >= 0) {
            this.listeners.splice(index, 1);
        }
    }
}

function harness() {
    const windowObject = new FakeWindow();
    const documentObject = new FakeDocument(windowObject);
    windowObject.document = documentObject;
    return {
        window: windowObject,
        document: documentObject,
        container: documentObject.createElement("div"),
    };
}

function hasClass(node, name) {
    return typeof node.className === "string" && node.className.split(/\s+/).includes(name);
}

function findAll(node, predicate, result = []) {
    node.children.forEach((child) => {
        if (predicate(child)) {
            result.push(child);
        }
        findAll(child, predicate, result);
    });
    return result;
}

function oneByClass(node, className) {
    const matches = findAll(node, (child) => hasClass(child, className));
    assert.equal(matches.length, 1, `expected one ${className}`);
    return matches[0];
}

function blockById(root, blockId) {
    const matches = findAll(root, (node) => node.getAttribute("data-block-id") === blockId);
    assert.equal(matches.length, 1, `expected one block ${blockId}`);
    return matches[0];
}

function eventIds(block) {
    return findAll(block, (node) => node.getAttribute("data-event-id") !== null)
        .map((node) => node.getAttribute("data-event-id"));
}

const events = [
    {
        id: 1,
        title: "<img src=x onerror=attack>",
        short_description: "First\nline",
        full_description: "Full first",
        place: "Hall",
        event_date: "2026-11-25",
        image_kiosk: "/static/uploads/kiosk-a.jpg",
        image_tv: "/static/uploads/tv-a.jpg",
        image_thumb: null,
        sort_order: 1,
        tag_ids: [1],
    },
    {
        id: 2,
        title: "Second",
        short_description: "",
        full_description: "Second details",
        place: "",
        event_date: null,
        image_kiosk: "/static/uploads/bad.jpg",
        image_tv: "/static/uploads/remote.jpg",
        image_thumb: null,
        sort_order: 2,
        tag_ids: [2],
    },
    {
        id: 3,
        title: "Third",
        short_description: "Third card",
        full_description: "Third details",
        place: "Stage",
        event_date: "2026-12-01",
        image_kiosk: "/static/uploads/kiosk-3.jpg",
        image_tv: null,
        image_thumb: null,
        sort_order: 3,
        tag_ids: [1, 2],
    },
];

const tags = [{id: 1, name: "News"}, {id: 2, name: "Family"}];
const media = {
    "/static/uploads/tv-a.jpg": "media/tv-a.jpg",
    "/static/uploads/kiosk-a.jpg": "media/kiosk-a.jpg",
    "/static/uploads/bad.jpg": "data:image/png;base64,AAAA",
    "/static/uploads/remote.jpg": "https://example.invalid/remote.jpg",
    "/static/uploads/kiosk-3.jpg": "media/kiosk-3.jpg",
};

const page = {
    schema: 1,
    target: "tv-landscape",
    pages: [
        {
            id: "main",
            version: 1,
            name: "Main",
            columns: 12,
            rows: 8,
            placements: [
                {block: "cards", x: 0, y: 0, w: 8, h: 5},
                {block: "filtered", x: 8, y: 0, w: 4, h: 3},
                {block: "unknown-module", x: 8, y: 3, w: 4, h: 2},
                {block: "missing-dataset", x: 0, y: 5, w: 4, h: 3},
                {block: "missing-events", x: 10, y: 7, w: 5, h: 5},
                {block: "empty-filter", x: 4, y: 5, w: 4, h: 3},
            ],
        },
        {
            id: "secondary",
            version: 1,
            name: "Secondary",
            columns: 4,
            rows: 3,
            placements: [{block: "cards", x: 0, y: 0, w: 4, h: 3}],
        },
    ],
    blocks: {
        cards: {schema: 1, version: 1, name: "All events", dataset: "all-events", tags: [], limit: 3, appearance: "cards"},
        filtered: {schema: 1, version: 1, name: "News list", dataset: "all-events", tags: ["News"], limit: 2, appearance: "list"},
        "unknown-module": {schema: 1, version: 1, name: "Legacy", dataset: "legacy", tags: [], limit: 0, appearance: "cards"},
        "missing-dataset": {schema: 1, version: 1, name: "Missing", dataset: "absent", tags: [], limit: 1, appearance: "cards"},
        "missing-events": {schema: 1, version: 1, name: "Missing events", dataset: "missing-events", tags: [], limit: 1, appearance: "list"},
        "empty-filter": {schema: 1, version: 1, name: "No matches", dataset: "all-events", tags: ["Not present"], limit: 1, appearance: "cards"},
    },
    datasets: {
        "all-events": {schema: 1, version: 1, name: "All events", module: "events", events: ["1", "2", "3", "999"]},
        legacy: {schema: 1, version: 1, name: "Legacy data", module: "legacy", events: ["1"]},
        "missing-events": {schema: 1, version: 1, name: "Missing events", module: "events", events: ["999"]},
    },
    start_page: "main",
    transition_seconds: 5,
};

function eventById(block, id) {
    const matches = findAll(block, (node) => node.getAttribute("data-event-id") === id);
    assert.equal(matches.length, 1, `expected one event ${id}`);
    return matches[0];
}

assert.equal(typeof mount, "function");
assert.equal(globalThis.KioskPageDisplay.mount, mount);
const css = require("node:fs").readFileSync(
    require("node:path").join(__dirname, "..", "kiosk", "static", "css", "page_display.css"),
    "utf8",
);
assert.ok(css.includes("repeat(var(--kpd-columns, 12), minmax(0, 1fr))"));
assert.ok(!/@import|url\s*\(/i.test(css));

const tvHarness = harness();
const tvController = mount(tvHarness.container, {page, events, tags, media, mode: "tv"});
assert.equal(tvHarness.container.children.length, 1);
const tvRoot = tvHarness.container.children[0];
assert.equal(tvRoot.getAttribute("data-mode"), "tv");
assert.equal(tvRoot.getAttribute("data-target"), "tv-landscape");
assert.equal(tvRoot.getAttribute("data-orientation"), "landscape");
assert.equal(oneByClass(tvRoot, "kpd__nav").hidden, true);
assert.equal(tvHarness.window.timers.size, 1);
assert.equal([...tvHarness.window.timers.values()][0].delay, 5000);
assert.equal(tvHarness.window.fetchCalls, 0);

const tvGrid = oneByClass(tvRoot, "kpd-grid");
assert.equal(tvGrid.style.getPropertyValue("--kpd-columns"), "12");
assert.equal(tvGrid.style.getPropertyValue("--kpd-rows"), "8");

const cardBlock = blockById(tvRoot, "cards");
assert.ok(hasClass(cardBlock, "kpd-block--cards"));
assert.equal(cardBlock.getAttribute("data-state"), "ready");
assert.deepEqual(eventIds(cardBlock), ["1", "2", "3"]);
const injectedTitle = oneByClass(eventById(cardBlock, "1"), "kpd-event__title");
assert.equal(injectedTitle.textContent, "<img src=x onerror=attack>");
assert.equal(injectedTitle.children.length, 0);
const safeImage = oneByClass(eventById(cardBlock, "1"), "kpd-event__image");
assert.equal(safeImage.getAttribute("src"), "media/tv-a.jpg");
const firstEvent = eventById(cardBlock, "1");
safeImage.dispatchEvent({type: "error"});
assert.equal(oneByClass(firstEvent, "kpd-event__media-placeholder").textContent, "Image unavailable");
assert.equal(oneByClass(eventById(cardBlock, "2"), "kpd-event__media-placeholder").textContent, "Image unavailable");
assert.equal(
    oneByClass(eventById(cardBlock, "3"), "kpd-event__image").getAttribute("src"),
    "media/kiosk-3.jpg",
);

const filteredBlock = blockById(tvRoot, "filtered");
assert.ok(hasClass(filteredBlock, "kpd-block--list"));
assert.deepEqual(eventIds(filteredBlock), ["1", "3"]);
assert.equal(filteredBlock.getAttribute("data-state"), "ready");

const unknownBlock = blockById(tvRoot, "unknown-module");
assert.equal(unknownBlock.getAttribute("data-state"), "unavailable");
assert.equal(oneByClass(unknownBlock, "kpd-block__fallback").textContent, "Content unavailable");
assert.equal(blockById(tvRoot, "missing-dataset").getAttribute("data-state"), "unavailable");
assert.equal(blockById(tvRoot, "missing-events").getAttribute("data-state"), "unavailable");
assert.equal(blockById(tvRoot, "empty-filter").getAttribute("data-state"), "empty");
assert.equal(oneByClass(blockById(tvRoot, "empty-filter"), "kpd-block__fallback").textContent, "No content");

const clampedBlock = blockById(tvRoot, "missing-events");
assert.equal(clampedBlock.getAttribute("data-grid-width"), "2");
assert.equal(clampedBlock.getAttribute("data-grid-height"), "1");
assert.equal(clampedBlock.style.getPropertyValue("grid-column"), "11 / span 2");
assert.equal(clampedBlock.style.getPropertyValue("grid-row"), "8 / span 1");

const [firstTimerId, firstAutoTimer] = [...tvHarness.window.timers.entries()][0];
tvHarness.window.timers.delete(firstTimerId);
firstAutoTimer.callback();
assert.equal(tvHarness.window.timers.size, 1);
assert.equal(oneByClass(tvRoot, "kpd-page").getAttribute("data-page-id"), "secondary");
assert.equal(oneByClass(tvRoot, "kpd__counter").textContent, "2 / 2");
assert.equal(oneByClass(tvRoot, "kpd-grid").style.getPropertyValue("--kpd-columns"), "4");

assert.ok(tvHarness.window.listeners.length > 0);
assert.ok(tvHarness.document.listeners.length > 0);
tvController.destroy();
tvController.destroy();
assert.equal(tvHarness.window.timers.size, 0);
assert.equal(tvHarness.window.listeners.length, 0);
assert.equal(tvHarness.document.listeners.length, 0);
assert.equal(tvHarness.container.children.length, 0);
assert.equal(findAll(tvRoot, (node) => node.listeners.length > 0).length, 0);

const kioskHarness = harness();
const kioskController = mount(kioskHarness.container, {page, events, tags, media, mode: "kiosk"});
const kioskRoot = kioskHarness.container.children[0];
assert.equal(kioskRoot.getAttribute("data-mode"), "kiosk");
assert.equal(oneByClass(kioskRoot, "kpd__nav").hidden, false);
assert.equal(kioskHarness.window.timers.size, 0);
const nextButton = findAll(kioskRoot, (node) => node.getAttribute("aria-label") === "Next page")[0];
nextButton.click();
assert.equal(oneByClass(kioskRoot, "kpd__counter").textContent, "2 / 2");
assert.equal(kioskHarness.window.timers.size, 0);

const stage = oneByClass(kioskRoot, "kpd__stage");
stage.dispatchEvent({type: "pointerdown", button: 0, clientX: 300, clientY: 100, pointerId: 4});
stage.dispatchEvent({type: "pointerup", button: 0, clientX: 80, clientY: 110, pointerId: 4});
assert.equal(oneByClass(kioskRoot, "kpd__counter").textContent, "1 / 2");

let prevented = 0;
kioskRoot.dispatchEvent({type: "keydown", key: "ArrowRight", preventDefault() { prevented += 1; }});
assert.equal(oneByClass(kioskRoot, "kpd__counter").textContent, "2 / 2");
assert.equal(prevented, 1);
assert.equal(kioskHarness.window.fetchCalls, 0);
kioskController.destroy();
assert.equal(kioskHarness.window.timers.size, 0);
assert.equal(kioskHarness.window.listeners.length, 0);
assert.equal(kioskHarness.document.listeners.length, 0);

const startHarness = harness();
const startController = mount(startHarness.container, {
    page: {...page, start_page: "secondary"},
    events,
    tags,
    media,
    mode: "kiosk",
});
assert.equal(
    oneByClass(startHarness.container, "kpd-page").getAttribute("data-page-id"),
    "secondary",
);
assert.equal(oneByClass(startHarness.container, "kpd__counter").textContent, "2 / 2");
startController.destroy();

const invalidHarness = harness();
const invalidController = mount(invalidHarness.container, {
    page: {schema: 2, pages: []},
    events,
    tags,
    media,
    mode: "tv",
});
assert.equal(oneByClass(invalidHarness.container, "kpd-page__fallback").textContent, "Content unavailable");
assert.equal(invalidHarness.window.timers.size, 0);
invalidController.destroy();
assert.equal(invalidHarness.container.children.length, 0);

console.log("Page display fixture rendering, fallback, media, navigation and teardown checks PASS");
