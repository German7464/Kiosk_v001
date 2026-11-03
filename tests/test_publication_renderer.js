"use strict";
const assert = require("node:assert/strict");
const {createEventsModel, eventsSlideDuration, createEventsTextPager, mountEventsView} = require("../kiosk/publication/renderer_assets/events.js");

const data = {
    content_version: 7, settings: {tv_slide_duration: "8"},
    tags: [{id: 1, name: "Tag one"}, {id: 2, name: "Empty tag"}],
    events: [
        {id: 1, title: "<img onerror=attack>", short_description: "First", full_description: "Full", place: "", event_date: null,
            image_kiosk: "/static/uploads/a.jpg", image_tv: null, tag_ids: [1]},
        {id: 2, title: "Second", short_description: "", full_description: "Details", place: "Hall", tag_ids: []}
    ]
};
const model = createEventsModel(data);
model.move(-1); assert.equal(model.current().id, 2);
model.move(1); assert.equal(model.current().id, 1);
model.select(1); assert.equal(model.events().length, 1);
model.select(2); assert.equal(model.current(), null);
model.move(1); assert.equal(model.index(), 0);
model.select(999); assert.equal(model.events().length, 2);
assert.equal(eventsSlideDuration({title: "x".repeat(1000)}, "8"), 24000);
assert.equal(eventsSlideDuration({title: ""}, "invalid"), 8000);

class Node {
    constructor() {
        this.children = []; this.listeners = {}; this.hidden = false;
        this.clientHeight = 1000; this.scrollHeight = 0; this.clientWidth = 1000; this.scrollWidth = 0;
        this.classList = {toggle() {}};
    }
    set innerHTML(value) { throw new Error("HTML injection is forbidden"); }
    appendChild(node) { node.parent = this; this.children.push(node); return node; }
    replaceChildren() { this.children = []; }
    replaceWith(node) { const parent = this.parent; parent.children[parent.children.indexOf(this)] = node; node.parent = parent; }
    setAttribute(name, value) { this[name] = value; }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    click() { this.listeners.click(); }
}
function mount(mode, fixture = data) {
    const ids = ["card", "home", "events", "inactivity", "counter", "previous", "next", "tags", "heading", "version", "home-button", "open-events", "home-label", "home-heading", "home-description"];
    const nodes = Object.fromEntries(ids.map(id => [id, new Node()]));
    nodes.home.hidden = true;
    const listeners = {};
    const document = {body: new Node(), createElement: () => new Node(), getElementById: id => nodes[id],
        addEventListener(name, callback) { listeners[name] = callback; }};
    const timers = new Map(); let sequence = 0;
    const window = {
        setTimeout(callback, delay) { const id = ++sequence; timers.set(id, {callback, delay}); return id; },
        clearTimeout(id) { timers.delete(id); },
        setInterval(callback, delay) { const id = ++sequence; timers.set(id, {callback, delay}); return id; },
        clearInterval(id) { timers.delete(id); },
        addEventListener() {},
        fetch() { throw new Error("Network is forbidden"); }
    };
    mountEventsView(document, window, {data: fixture, mode, labels: {}, media: {"/static/uploads/a.jpg": "static/uploads/a.jpg"}});
    return {nodes, timers, listeners};
}
const kiosk = mount("kiosk");
assert.equal(kiosk.nodes.card.children[2].textContent, data.events[0].title);
const image = kiosk.nodes.card.children[0];
assert.equal(image.src, "static/uploads/a.jpg");
image.listeners.error();
assert.equal(kiosk.nodes.card.children[0].className, "image-placeholder");
kiosk.nodes.next.click(); assert.equal(kiosk.nodes.counter.textContent, "2 / 2");
kiosk.nodes.tags.children[2].click(); assert.equal(kiosk.nodes.counter.textContent, "0 / 0");
assert.equal(kiosk.nodes.next.disabled, true);
kiosk.nodes["home-button"].click(); assert.equal(kiosk.nodes.home.hidden, false);
kiosk.nodes["open-events"].click(); assert.equal(kiosk.nodes.counter.textContent, "1 / 2");
const idle = [...kiosk.timers.values()].find(timer => timer.delay === 90000);
idle.callback(); assert.equal(kiosk.nodes.inactivity.hidden, false);
const now = Date.now;
try {
    Date.now = () => now() + 31000;
    [...kiosk.timers.values()].find(timer => timer.delay === 1000).callback();
    assert.equal(kiosk.nodes.home.hidden, false);
} finally { Date.now = now; }
const tv = mount("tv");
assert.equal(tv.timers.size, 1);
[...tv.timers.values()][0].callback();
assert.equal(tv.nodes.counter.textContent, "2 / 2");
assert.equal(tv.timers.size, 1);
const empty = mount("tv", {...data, events: []});
assert.equal(empty.nodes.counter.textContent, "0 / 0");
assert.equal(empty.timers.size, 0);
console.log("Offline Events renderer model/DOM/timer/security checks PASS");

// Consecutive pages preserve every code unit, field order and whole graphemes.
function paginate(values, capacity) {
    const nodes = [];
    const container = {replaceChildren() { nodes.length = 0; }, appendChild(node) { nodes.push(node); }};
    const make = (tag, className, value) => ({tag, className, textContent: value,
        remove() { nodes.splice(nodes.indexOf(this), 1); }});
    const fields = values.map(value => ({tag: "p", className: "test", value}));
    const pager = createEventsTextPager(fields, make, () => nodes.reduce((n, x) => n + x.textContent.length, 0) <= capacity);
    const pages = [];
    for (let guard = 0; pager.more() && guard < 10000; guard++) {
        const page = pager.next(container);
        if (!page.progressed) return {pages, blocked: true};
        assert.ok(page.visible.length <= capacity);
        pages.push(page.visible);
    }
    assert.equal(pager.more(), false);
    return {pages, blocked: false};
}
for (const values of [
    ["title", "word ".repeat(30), "place"],
    ["", "a".repeat(33000), ""],
    ["line1\n\nline2 ", "\u0422\u0435\u043a\u0441\u0442"],
    ["x👩‍👩‍👧‍👦e\u0301🇩🇪".repeat(8)]
]) {
    const {pages, blocked} = paginate(values, 40);
    assert.equal(blocked, false);
    assert.equal(pages.join(""), values.join(""));
    const boundaries = new Set(); let length = 0;
    for (const item of new Intl.Segmenter(undefined, {granularity: "grapheme"}).segment(values.join(""))) {
        length += item.segment.length; boundaries.add(length);
    }
    let position = 0;
    for (const page of pages) { position += page.length; assert.ok(boundaries.has(position)); }
}
assert.equal(paginate(["👩‍👩‍👧‍👦"], 1).blocked, true);
assert.equal(paginate(["abc"], 0).blocked, true);
console.log("TV bounded text pagination/lossless/grapheme checks PASS");
