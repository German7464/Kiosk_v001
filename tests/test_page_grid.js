"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "kiosk", "static", "js", "page_grid.js"), "utf8");
const sandbox = {window: {}, console};
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
const api = sandbox.window.KioskPageGrid;
assert.ok(api && typeof api.mount === "function", "window.KioskPageGrid.mount must be exposed");

class FakeClassList {
    constructor(element) {
        this.element = element;
        this.values = new Set();
    }

    add(...names) {
        for (const name of names) this.values.add(String(name));
    }

    remove(...names) {
        for (const name of names) this.values.delete(String(name));
    }

    toggle(name, force) {
        const enabled = force === undefined ? !this.values.has(String(name)) : Boolean(force);
        if (enabled) this.values.add(String(name));
        else this.values.delete(String(name));
        return enabled;
    }

    contains(name) {
        return this.values.has(String(name));
    }
}

class FakeStyle {
    constructor() {
        this.properties = new Map();
    }

    setProperty(name, value) {
        this.properties.set(name, String(value));
        this[name] = String(value);
    }

    removeProperty(name) {
        this.properties.delete(name);
        delete this[name];
    }
}

class FakeElement {
    constructor(tagName, ownerDocument) {
        this.tagName = String(tagName).toUpperCase();
        this.ownerDocument = ownerDocument;
        this.children = [];
        this.parentNode = null;
        this.attributes = new Map();
        this.listeners = new Map();
        this.classList = new FakeClassList(this);
        this.style = new FakeStyle();
        this.textContent = "";
        this.disabled = false;
        this.type = "";
        this.capturedPointer = null;
        this.rect = {left: 0, top: 0, width: 0, height: 0};
    }

    get className() {
        return Array.from(this.classList.values).join(" ");
    }

    set className(value) {
        this.classList.values.clear();
        for (const name of String(value).split(/\s+/).filter(Boolean)) this.classList.values.add(name);
    }

    get innerHTML() {
        throw new Error("HTML rendering is forbidden");
    }

    set innerHTML(value) {
        throw new Error("HTML rendering is forbidden");
    }

    setAttribute(name, value) {
        this.attributes.set(String(name), String(value));
    }

    getAttribute(name) {
        return this.attributes.has(String(name)) ? this.attributes.get(String(name)) : null;
    }

    appendChild(child) {
        if (child.parentNode) child.parentNode.removeChild(child);
        this.children.push(child);
        child.parentNode = this;
        return child;
    }

    removeChild(child) {
        const index = this.children.indexOf(child);
        if (index < 0) throw new Error("child not found");
        this.children.splice(index, 1);
        child.parentNode = null;
        return child;
    }

    remove() {
        if (this.parentNode) this.parentNode.removeChild(this);
    }

    contains(node) {
        let current = node;
        while (current) {
            if (current === this) return true;
            current = current.parentNode;
        }
        return false;
    }

    addEventListener(type, listener) {
        if (!this.listeners.has(type)) this.listeners.set(type, []);
        this.listeners.get(type).push(listener);
    }

    removeEventListener(type, listener) {
        const listeners = this.listeners.get(type);
        if (!listeners) return;
        const index = listeners.indexOf(listener);
        if (index >= 0) listeners.splice(index, 1);
    }

    dispatch(type, event) {
        const value = event || {};
        value.type = type;
        if (!value.target) value.target = this;
        if (!value.preventDefault) {
            value.preventDefault = () => {
                value.defaultPrevented = true;
            };
        }
        for (const listener of Array.from(this.listeners.get(type) || [])) listener(value);
        return value;
    }

    focus() {
        this.ownerDocument.activeElement = this;
    }

    setPointerCapture(pointerId) {
        this.capturedPointer = pointerId;
    }

    hasPointerCapture(pointerId) {
        return this.capturedPointer === pointerId;
    }

    releasePointerCapture(pointerId) {
        if (this.capturedPointer === pointerId) this.capturedPointer = null;
    }

    getBoundingClientRect() {
        return {...this.rect};
    }

    setRect(left, top, width, height) {
        this.rect = {left, top, width, height};
        return this;
    }
}

class FakeDocument {
    constructor() {
        this.activeElement = null;
        this.listeners = new Map();
    }

    createElement(tagName) {
        return new FakeElement(tagName, this);
    }

    addEventListener(type, listener) {
        if (!this.listeners.has(type)) this.listeners.set(type, []);
        this.listeners.get(type).push(listener);
    }

    removeEventListener(type, listener) {
        const listeners = this.listeners.get(type);
        if (!listeners) return;
        const index = listeners.indexOf(listener);
        if (index >= 0) listeners.splice(index, 1);
    }

    dispatch(type, event) {
        const value = event || {};
        value.type = type;
        if (!value.preventDefault) {
            value.preventDefault = () => {
                value.defaultPrevented = true;
            };
        }
        for (const listener of Array.from(this.listeners.get(type) || [])) listener(value);
        return value;
    }

    listenerCount(type) {
        return (this.listeners.get(type) || []).length;
    }
}

function descendants(node) {
    const result = [];
    for (const child of node.children) {
        result.push(child);
        result.push(...descendants(child));
    }
    return result;
}

function findByClass(node, className) {
    return descendants(node).find((item) => item.classList.contains(className)) || null;
}

function card(container, block) {
    return descendants(container).find((item) => item.classList.contains("kpg-item")
        && item.getAttribute("data-block-id") === String(block)) || null;
}

function control(cardElement, className) {
    return findByClass(cardElement, className);
}

function cardIds(container) {
    return findByClass(container, "kpg-surface").children
        .filter((item) => item.classList.contains("kpg-item"))
        .map((item) => item.getAttribute("data-block-id"));
}

function statusText(container) {
    return findByClass(container, "kpg-status").textContent;
}

function pointerEvent(clientX, clientY, extra) {
    return Object.assign({
        clientX,
        clientY,
        pointerId: 7,
        pointerType: "mouse",
        button: 0,
        isPrimary: true,
        cancelable: true,
    }, extra || {});
}

function keyEvent(key, extra) {
    return Object.assign({key, cancelable: true}, extra || {});
}

function fixture(layout, labels, rect) {
    const document = new FakeDocument();
    const container = document.createElement("div");
    const changes = [];
    const widget = api.mount(container, {layout, labels, onChange: (value) => changes.push(value)});
    const surface = findByClass(container, "kpg-surface");
    const box = rect || {left: 100, top: 50, width: 1200, height: 600};
    surface.setRect(box.left, box.top, box.width, box.height);
    return {document, container, changes, widget, surface};
}

function plainLayout(columns, rows, placements) {
    return {columns, rows, placements};
}

function copy(value) {
    return JSON.parse(JSON.stringify(value));
}

{
    const layout = plainLayout(12, 8, [
        {block: "a", x: 0, y: 0, w: 2, h: 2},
        {block: "b", x: 5, y: 2, w: 3, h: 2},
    ]);
    const {container, changes, widget} = fixture(layout, {a: "<b>Title</b>", b: "Second"});
    assert.deepEqual(cardIds(container), ["a", "b"]);
    const first = card(container, "a");
    assert.equal(first.style.gridColumn, "1 / span 2");
    assert.equal(first.style.gridRow, "1 / span 2");
    assert.equal(control(first, "kpg-label").textContent, "<b>Title</b>");
    assert.equal(control(first, "kpg-label").children.length, 0);
    const earlier = control(first, "kpg-earlier");
    const later = control(first, "kpg-later");
    assert.equal(earlier.tagName, "BUTTON");
    assert.equal(earlier.type, "button");
    assert.equal(earlier.disabled, true);
    assert.match(earlier.getAttribute("aria-label"), /earlier in navigation order/);
    assert.match(later.getAttribute("aria-label"), /later in navigation order/);
    assert.equal(later.disabled, false);

    widget.setLayout(plainLayout(10, 6, [
        {block: "b", x: 1, y: 1, w: 2, h: 2},
        {block: "c", x: 5, y: 1, w: 2, h: 3},
    ]), {b: "Bee", c: "Cee"});
    assert.deepEqual(cardIds(container), ["b", "c"]);
    assert.equal(card(container, "a"), null);
    assert.equal(control(card(container, "b"), "kpg-label").textContent, "Bee");
    assert.equal(control(card(container, "c"), "kpg-label").textContent, "Cee");
    assert.equal(card(container, "c").style.gridRow, "2 / span 3");
    assert.equal(changes.length, 0);

    assert.throws(() => widget.setLayout(plainLayout(8, 5, [
        {block: "b", x: 0, y: 0, w: 3, h: 2},
        {block: "c", x: 2, y: 1, w: 2, h: 2},
    ])), /overlaps/);
    assert.deepEqual(cardIds(container), ["b", "c"]);
    assert.equal(card(container, "b").style.gridColumn, "2 / span 2");
}

{
    const {document, container, changes} = fixture(plainLayout(12, 6, [
        {block: "a", x: 0, y: 0, w: 2, h: 2},
        {block: "b", x: 6, y: 2, w: 3, h: 2},
    ]), {a: "Alpha", b: "Beta"});
    const first = card(container, "a");
    const handle = control(first, "kpg-drag-handle");
    handle.dispatch("pointerdown", pointerEvent(150, 75));
    document.dispatch("pointermove", pointerEvent(450, 175));
    document.dispatch("pointerup", pointerEvent(450, 175));
    assert.equal(changes.length, 1);
    assert.deepEqual(copy(changes[0].placements.map((item) => item.block)), ["a", "b"]);
    assert.deepEqual(copy(changes[0].placements[0]), {block: "a", x: 3, y: 1, w: 2, h: 2});
    assert.equal(first.style.gridColumn, "4 / span 2");
    assert.equal(first.style.gridRow, "2 / span 2");
    assert.equal(document.listenerCount("pointermove"), 0);
    changes[0].placements[0].x = 11;
    assert.equal(first.style.gridColumn, "4 / span 2");

    handle.dispatch("pointerdown", pointerEvent(450, 175, {pointerType: "touch"}));
    document.dispatch("pointerup", pointerEvent(450, 175, {pointerType: "touch"}));
    assert.equal(changes.length, 1);

    handle.dispatch("pointerdown", pointerEvent(450, 175));
    document.dispatch("pointerup", pointerEvent(undefined, undefined));
    assert.equal(changes.length, 1);
    assert.equal(first.style.gridColumn, "4 / span 2");
}

{
    const {document, container, changes} = fixture(plainLayout(6, 4, [
        {block: "a", x: 0, y: 0, w: 2, h: 2},
    ]), {a: "Only"}, {left: 100, top: 50, width: 600, height: 400});
    const first = card(container, "a");
    const handle = control(first, "kpg-drag-handle");
    handle.dispatch("pointerdown", pointerEvent(150, 150, {pointerType: "touch", button: 0}));
    document.dispatch("pointermove", pointerEvent(-5000, -5000, {pointerType: "touch"}));
    document.dispatch("pointerup", pointerEvent(5000, 5000, {pointerType: "touch"}));
    assert.equal(changes.length, 1);
    assert.deepEqual(copy(changes[0].placements[0]), {block: "a", x: 4, y: 2, w: 2, h: 2});
    assert.equal(first.style.gridColumn, "5 / span 2");
    assert.equal(first.style.gridRow, "3 / span 2");

    handle.dispatch("pointerdown", pointerEvent(200, 200, {button: 2}));
    document.dispatch("pointermove", pointerEvent(300, 300));
    assert.equal(document.listenerCount("pointermove"), 0);
    assert.equal(changes.length, 1);
}

{
    const {document, container, changes} = fixture(plainLayout(4, 4, [
        {block: 7, x: 0, y: 0, w: 2, h: 2},
    ]), {"7": "Numeric"}, {left: 0, top: 0, width: 400, height: 400});
    assert.equal(control(card(container, "7"), "kpg-label").textContent, "Numeric");
    const handle = control(card(container, "7"), "kpg-drag-handle");
    handle.setPointerCapture = () => {
        throw new Error("capture unavailable");
    };
    handle.dispatch("pointerdown", pointerEvent(50, 50));
    document.dispatch("pointermove", pointerEvent(150, 50));
    document.dispatch("pointerup", pointerEvent(150, 50));
    assert.equal(changes.length, 1);
    assert.equal(changes[0].placements[0].block, 7);
    assert.equal(changes[0].placements[0].x, 1);
    assert.equal(handle.classList.contains("is-grabbed"), false);
}

{
    const {document, container, changes} = fixture(plainLayout(8, 4, [
        {block: "a", x: 0, y: 0, w: 2, h: 2},
        {block: "b", x: 4, y: 0, w: 2, h: 2},
    ]), {a: "Alpha", b: "Beta"}, {left: 100, top: 50, width: 800, height: 400});
    const first = card(container, "a");
    const handle = control(first, "kpg-drag-handle");
    handle.dispatch("pointerdown", pointerEvent(150, 75));
    document.dispatch("pointermove", pointerEvent(550, 75));
    assert.equal(first.classList.contains("is-invalid"), true);
    document.dispatch("pointerup", pointerEvent(550, 75));
    assert.equal(changes.length, 0);
    assert.equal(first.style.gridColumn, "1 / span 2");
    assert.match(statusText(container), /overlaps another block/);

    handle.dispatch("pointerdown", pointerEvent(150, 75));
    document.dispatch("pointermove", pointerEvent(350, 75));
    document.dispatch("pointerup", pointerEvent(350, 75));
    assert.equal(changes.length, 1);
    assert.equal(changes[0].placements[0].x, 2);
    assert.equal(first.style.gridColumn, "3 / span 2");
}

{
    const {document, container, changes, surface} = fixture(plainLayout(12, 6, [
        {block: "a", x: 1, y: 1, w: 2, h: 2},
    ]), {a: "Zoom"});
    const first = card(container, "a");
    const handle = control(first, "kpg-drag-handle");
    handle.dispatch("pointerdown", pointerEvent(300, 200));
    surface.setRect(100, 50, 600, 300);
    document.dispatch("pointermove", pointerEvent(300, 225));
    document.dispatch("pointerup", pointerEvent(300, 225));
    assert.equal(changes.length, 1);
    assert.deepEqual(copy(changes[0].placements[0]), {block: "a", x: 3, y: 3, w: 2, h: 2});
}

{
    const {document, container, changes} = fixture(plainLayout(8, 5, [
        {block: "a", x: 0, y: 0, w: 2, h: 2},
    ]), {a: "Cancel"}, {left: 100, top: 50, width: 800, height: 500});
    const first = card(container, "a");
    const handle = control(first, "kpg-drag-handle");
    handle.dispatch("pointerdown", pointerEvent(150, 75));
    document.dispatch("pointermove", pointerEvent(450, 275));
    assert.equal(first.style.gridColumn, "4 / span 2");
    document.dispatch("keydown", keyEvent("Escape"));
    assert.equal(first.style.gridColumn, "1 / span 2");
    assert.equal(changes.length, 0);
    assert.match(statusText(container), /cancelled/);
    assert.equal(document.listenerCount("pointerup"), 0);
    document.dispatch("pointerup", pointerEvent(450, 275));
    assert.equal(changes.length, 0);

    handle.dispatch("pointerdown", pointerEvent(150, 75));
    document.dispatch("pointermove", pointerEvent(350, 75));
    document.dispatch("pointercancel", pointerEvent(350, 75));
    assert.equal(first.style.gridColumn, "1 / span 2");
    assert.equal(changes.length, 0);
}

{
    const {document, container, changes} = fixture(plainLayout(12, 6, [
        {block: "a", x: 1, y: 1, w: 2, h: 2},
        {block: "b", x: 8, y: 0, w: 2, h: 2},
    ]), {a: "Resizable", b: "Other"});
    const first = card(container, "a");
    const resize = control(first, "kpg-resize");
    resize.dispatch("pointerdown", pointerEvent(300, 250));
    document.dispatch("pointermove", pointerEvent(500, 350));
    document.dispatch("pointerup", pointerEvent(500, 350));
    assert.equal(changes.length, 1);
    assert.deepEqual(copy(changes[0].placements[0]), {block: "a", x: 1, y: 1, w: 4, h: 3});
    assert.equal(first.style.gridColumn, "2 / span 4");
    assert.equal(first.style.gridRow, "2 / span 3");

    resize.dispatch("keydown", keyEvent("ArrowRight"));
    assert.equal(changes.length, 2);
    assert.equal(changes[1].placements[0].w, 5);
}

{
    const {document, container, changes} = fixture(plainLayout(8, 4, [
        {block: "a", x: 0, y: 1, w: 2, h: 2},
        {block: "b", x: 3, y: 1, w: 2, h: 2},
    ]), {a: "Resize", b: "Blocked"}, {left: 100, top: 50, width: 800, height: 400});
    const first = card(container, "a");
    const resize = control(first, "kpg-resize");
    resize.dispatch("pointerdown", pointerEvent(300, 200));
    document.dispatch("pointermove", pointerEvent(500, 200));
    document.dispatch("pointerup", pointerEvent(500, 200));
    assert.equal(changes.length, 0);
    assert.equal(first.style.gridColumn, "1 / span 2");
    assert.match(statusText(container), /overlaps another block/);
}

{
    const {document, container, changes} = fixture(plainLayout(12, 6, [
        {block: "a", x: 0, y: 0, w: 2, h: 2},
        {block: "b", x: 3, y: 0, w: 2, h: 2},
        {block: "c", x: 6, y: 0, w: 2, h: 2},
    ]), {a: "First", b: "Middle", c: "Last"});
    const middle = card(container, "b");
    const later = control(middle, "kpg-later");
    later.focus();
    later.dispatch("click", {});
    assert.equal(changes.length, 1);
    assert.deepEqual(copy(changes[0].placements.map((item) => item.block)), ["a", "c", "b"]);
    assert.deepEqual(cardIds(container), ["a", "c", "b"]);
    assert.equal(changes[0].placements[2].x, 3);
    assert.equal(document.activeElement, control(card(container, "b"), "kpg-drag-handle"));

    const firstEarlier = control(card(container, "a"), "kpg-earlier");
    firstEarlier.dispatch("click", {});
    assert.equal(changes.length, 1);

    const firstHandle = control(card(container, "a"), "kpg-drag-handle");
    firstHandle.dispatch("keydown", keyEvent("ArrowRight"));
    assert.equal(changes.length, 2);
    assert.deepEqual(copy(changes[1].placements[0]), {block: "a", x: 1, y: 0, w: 2, h: 2});
}

{
    const {document, container, changes, widget} = fixture(plainLayout(10, 5, [
        {block: "a", x: 0, y: 0, w: 2, h: 2},
        {block: "b", x: 4, y: 0, w: 2, h: 2},
    ]), {a: "Alpha", b: "Beta"});
    const first = card(container, "a");
    const handle = control(first, "kpg-drag-handle");
    handle.dispatch("pointerdown", pointerEvent(150, 75));
    document.dispatch("pointermove", pointerEvent(350, 75));
    widget.setLayout(plainLayout(10, 5, [
        {block: "b", x: 0, y: 0, w: 2, h: 2},
        {block: "c", x: 4, y: 0, w: 2, h: 2},
    ]), {b: "Bee", c: "Cee"});
    assert.equal(changes.length, 0);
    assert.deepEqual(cardIds(container), ["b", "c"]);
    assert.equal(document.listenerCount("pointermove"), 0);
    assert.equal(control(card(container, "c"), "kpg-label").textContent, "Cee");
}

{
    const document = new FakeDocument();
    const container = document.createElement("div");
    const existing = document.createElement("p");
    existing.textContent = "Preserved";
    container.appendChild(existing);
    const widget = api.mount(container, {
        layout: plainLayout(6, 4, [{block: "a", x: 0, y: 0, w: 2, h: 2}]),
        labels: {a: "Alpha"},
        onChange: () => {
            throw new Error("destroyed widget must not notify");
        },
    });
    const surface = findByClass(container, "kpg-surface");
    surface.setRect(100, 50, 600, 400);
    const handle = control(card(container, "a"), "kpg-drag-handle");
    handle.dispatch("pointerdown", pointerEvent(150, 75));
    document.dispatch("pointermove", pointerEvent(350, 75));
    widget.destroy();
    assert.deepEqual(container.children, [existing]);
    assert.equal(existing.textContent, "Preserved");
    assert.equal(document.listenerCount("pointermove"), 0);
    assert.equal(document.listenerCount("pointerup"), 0);
    document.dispatch("pointerup", pointerEvent(350, 75));
    widget.destroy();
    widget.setLayout(plainLayout(2, 2, []));
}

assert.throws(() => api.mount(new FakeDocument().createElement("div"), {
    layout: plainLayout(4, 4, [{block: "a", x: 3, y: 0, w: 2, h: 1}]),
}), /exceeds layout.columns/);
assert.throws(() => api.mount(new FakeDocument().createElement("div"), {
    layout: plainLayout(4, 4, [
        {block: "a", x: 0, y: 0, w: 2, h: 2},
        {block: "b", x: 1, y: 1, w: 2, h: 2},
    ]),
}), /overlaps/);
assert.throws(() => api.mount(new FakeDocument().createElement("div"), {
    layout: plainLayout(0, 4, []),
}), /layout.columns/);

console.log("PASS page_grid: validated geometry, bounds, zoom-scaled drag, overlap refusal, resize, reorder, cancel, setLayout reconciliation and destroy");
