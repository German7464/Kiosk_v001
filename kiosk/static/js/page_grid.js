"use strict";
(function (root) {
    const hasOwn = Object.prototype.hasOwnProperty;

    function fail(message) {
        throw new TypeError("KioskPageGrid: " + message);
    }

    function integer(value, name, minimum) {
        if (typeof value !== "number" || !Number.isInteger(value) || value < minimum) {
            fail(name + " must be an integer greater than or equal to " + minimum);
        }
        return value;
    }

    function blockId(value, index) {
        if (typeof value === "string" && value.length > 0) return value;
        if (typeof value === "number" && Number.isSafeInteger(value)) return value;
        fail("placements[" + index + "].block must be a non-empty string or a safe integer");
    }

    function blockKey(value) {
        return (typeof value === "number" ? "n" : "s") + ":" + String(value);
    }

    function overlaps(left, right) {
        return left.x < right.x + right.w
            && right.x < left.x + left.w
            && left.y < right.y + right.h
            && right.y < left.y + left.h;
    }

    function samePlacement(left, right) {
        return left.block === right.block
            && left.x === right.x
            && left.y === right.y
            && left.w === right.w
            && left.h === right.h;
    }

    function normalizeLayout(layout) {
        if (!layout || typeof layout !== "object" || Array.isArray(layout)) {
            fail("layout must be an object");
        }
        const columns = integer(layout.columns, "layout.columns", 1);
        const rows = integer(layout.rows, "layout.rows", 1);
        if (!Array.isArray(layout.placements)) fail("layout.placements must be an array");
        const seen = new Set();
        const placements = layout.placements.map((item, index) => {
            if (!item || typeof item !== "object" || Array.isArray(item)) {
                fail("placements[" + index + "] must be an object");
            }
            const block = blockId(item.block, index);
            const key = blockKey(block);
            if (seen.has(key)) fail("duplicate block ID at placements[" + index + "]");
            seen.add(key);
            const x = integer(item.x, "placements[" + index + "].x", 0);
            const y = integer(item.y, "placements[" + index + "].y", 0);
            const w = integer(item.w, "placements[" + index + "].w", 1);
            const h = integer(item.h, "placements[" + index + "].h", 1);
            if (x + w > columns) fail("placements[" + index + "] exceeds layout.columns");
            if (y + h > rows) fail("placements[" + index + "] exceeds layout.rows");
            return {block, x, y, w, h};
        });
        for (let left = 0; left < placements.length; left += 1) {
            for (let right = left + 1; right < placements.length; right += 1) {
                if (overlaps(placements[left], placements[right])) {
                    fail("placements[" + left + "] overlaps placements[" + right + "]");
                }
            }
        }
        return {columns, rows, placements};
    }

    function snapshot(layout) {
        return {
            columns: layout.columns,
            rows: layout.rows,
            placements: layout.placements.map((item) => ({
                block: item.block, x: item.x, y: item.y, w: item.w, h: item.h,
            })),
        };
    }

    function readLabels(source, previous) {
        const labels = new Map(previous || []);
        if (source === undefined) return labels;
        labels.clear();
        if (source === null) return labels;
        const add = (key, value) => {
            if (typeof value === "string") labels.set(String(key), value);
        };
        if (source instanceof Map) {
            source.forEach((value, key) => add(key, value));
            return labels;
        }
        if (typeof source !== "object") fail("labels must be a plain object or Map");
        for (const key of Object.keys(source)) {
            if (hasOwn.call(source, key)) add(key, source[key]);
        }
        return labels;
    }

    function labelFor(labels, block) {
        const value = labels.get(String(block));
        return typeof value === "string" && value.length ? value : "Block " + String(block);
    }

    function clamp(value, minimum, maximum) {
        return Math.min(maximum, Math.max(minimum, value));
    }

    let instanceSequence = 0;

    function mount(container, options) {
        if (!container || typeof container.appendChild !== "function") {
            fail("container must be a DOM element");
        }
        const document = container.ownerDocument
            || (typeof window !== "undefined" && window.document)
            || (typeof globalThis !== "undefined" && globalThis.document);
        if (!document || typeof document.createElement !== "function") {
            fail("container must belong to a document");
        }
        if (!options || typeof options !== "object") fail("options are required");
        let state = normalizeLayout(options.layout);
        let labels = readLabels(options.labels);
        if (options.onChange !== undefined && options.onChange !== null && typeof options.onChange !== "function") {
            fail("options.onChange must be a function");
        }
        const onChange = options.onChange || null;
        const cards = new Map();
        const instance = ++instanceSequence;
        let interaction = null;
        let destroyed = false;

        const rootElement = document.createElement("section");
        rootElement.className = "kpg";
        rootElement.setAttribute("role", "region");
        rootElement.setAttribute("aria-label", "Page grid editor");

        const instructions = document.createElement("p");
        instructions.className = "kpg-instructions";
        instructions.id = "kpg-instructions-" + instance;
        instructions.textContent = "Drag a block by its Move button, use the arrow keys for precise movement, and use Earlier or Later to change navigation order.";

        const status = document.createElement("p");
        status.className = "kpg-status";
        status.setAttribute("role", "status");
        status.setAttribute("aria-live", "polite");
        status.setAttribute("aria-atomic", "true");

        const surface = document.createElement("div");
        surface.className = "kpg-surface";
        surface.setAttribute("role", "group");
        surface.setAttribute("aria-describedby", instructions.id);

        rootElement.appendChild(instructions);
        rootElement.appendChild(status);
        rootElement.appendChild(surface);
        container.appendChild(rootElement);

        function setStatus(message) {
            status.textContent = message || "";
        }

        function emitChange() {
            if (onChange && !destroyed) onChange(snapshot(state));
        }

        function currentIndex(key) {
            return state.placements.findIndex((item) => blockKey(item.block) === key);
        }

        function overlapsAnother(candidate, key) {
            return state.placements.some((item) => blockKey(item.block) !== key && overlaps(candidate, item));
        }

        function paint(card, placement) {
            card.item.style.gridColumn = String(placement.x + 1) + " / span " + String(placement.w);
            card.item.style.gridRow = String(placement.y + 1) + " / span " + String(placement.h);
        }

        function updateCard(card, placement, index) {
            const label = labelFor(labels, placement.block);
            card.label.textContent = label;
            card.order.textContent = String(index + 1);
            card.item.setAttribute("data-block-id", String(placement.block));
            card.item.setAttribute(
                "aria-label",
                label + ", navigation position " + String(index + 1)
                    + ", column " + String(placement.x + 1)
                    + ", row " + String(placement.y + 1)
                    + ", " + String(placement.w) + " by " + String(placement.h) + " cells",
            );
            card.handle.setAttribute("aria-label", "Move " + label + ". Use pointer drag or arrow keys.");
            card.resize.setAttribute("aria-label", "Resize " + label + ". Use pointer drag or arrow keys.");
            card.earlier.setAttribute("aria-label", "Move " + label + " earlier in navigation order");
            card.later.setAttribute("aria-label", "Move " + label + " later in navigation order");
            card.earlier.disabled = index === 0;
            card.later.disabled = index === state.placements.length - 1;
            card.item.classList.remove("is-active", "is-preview", "is-invalid");
            paint(card, placement);
        }

        function createCard(placement) {
            const item = document.createElement("article");
            item.className = "kpg-item";
            item.setAttribute("role", "group");
            item.setAttribute("aria-roledescription", "layout block");

            const header = document.createElement("header");
            header.className = "kpg-item-header";

            const handle = document.createElement("button");
            handle.type = "button";
            handle.className = "kpg-drag-handle";
            handle.textContent = "Move";
            handle.setAttribute("aria-keyshortcuts", "ArrowUp ArrowDown ArrowLeft ArrowRight");

            const order = document.createElement("span");
            order.className = "kpg-order";
            order.setAttribute("aria-hidden", "true");

            const label = document.createElement("span");
            label.className = "kpg-label";

            const actions = document.createElement("span");
            actions.className = "kpg-actions";

            const earlier = document.createElement("button");
            earlier.type = "button";
            earlier.className = "kpg-action kpg-earlier";
            earlier.textContent = "Earlier";

            const later = document.createElement("button");
            later.type = "button";
            later.className = "kpg-action kpg-later";
            later.textContent = "Later";

            const preview = document.createElement("div");
            preview.className = "kpg-preview";
            preview.setAttribute("aria-hidden", "true");

            const resize = document.createElement("button");
            resize.type = "button";
            resize.className = "kpg-resize";
            resize.textContent = "◢";
            resize.setAttribute("aria-keyshortcuts", "ArrowUp ArrowDown ArrowLeft ArrowRight");

            actions.appendChild(earlier);
            actions.appendChild(later);
            header.appendChild(handle);
            header.appendChild(order);
            header.appendChild(label);
            header.appendChild(actions);
            item.appendChild(header);
            item.appendChild(preview);
            item.appendChild(resize);

            const key = blockKey(placement.block);
            const card = {item, handle, order, label, earlier, later, resize};
            handle.addEventListener("pointerdown", (event) => beginInteraction(card, key, "move", event));
            resize.addEventListener("pointerdown", (event) => beginInteraction(card, key, "resize", event));
            handle.addEventListener("keydown", (event) => keyboardMove(key, event));
            resize.addEventListener("keydown", (event) => keyboardResize(key, event));
            earlier.addEventListener("click", (event) => {
                event.preventDefault();
                if (!earlier.disabled) reorder(key, -1);
            });
            later.addEventListener("click", (event) => {
                event.preventDefault();
                if (!later.disabled) reorder(key, 1);
            });
            return card;
        }

        function renderLayout() {
            const active = document.activeElement;
            const restore = active && rootElement.contains(active) ? active : null;
            surface.style.setProperty("--kpg-columns", String(state.columns));
            surface.style.setProperty("--kpg-rows", String(state.rows));
            surface.style.gridTemplateColumns = "repeat(" + String(state.columns) + ", minmax(0, 1fr))";
            surface.style.gridTemplateRows = "repeat(" + String(state.rows) + ", minmax(0, 1fr))";
            surface.setAttribute("aria-label", "Grid: " + String(state.columns) + " columns by " + String(state.rows) + " rows");

            const live = new Set();
            state.placements.forEach((placement, index) => {
                const key = blockKey(placement.block);
                live.add(key);
                let card = cards.get(key);
                if (!card) {
                    card = createCard(placement);
                    cards.set(key, card);
                }
                updateCard(card, placement, index);
                surface.appendChild(card.item);
            });
            for (const [key, card] of Array.from(cards.entries())) {
                if (!live.has(key)) {
                    surface.removeChild(card.item);
                    cards.delete(key);
                }
            }
            if (restore && rootElement.contains(restore) && typeof restore.focus === "function") {
                try {
                    restore.focus({preventScroll: true});
                } catch (error) {
                    restore.focus();
                }
            }
        }

        function surfacePoint(event) {
            if (!surface.getBoundingClientRect) return null;
            const rect = surface.getBoundingClientRect();
            if (!rect || !Number.isFinite(rect.width) || !Number.isFinite(rect.height)
                || rect.width <= 0 || rect.height <= 0) return null;
            if (!Number.isFinite(event.clientX) || !Number.isFinite(event.clientY)) return null;
            return {
                x: (event.clientX - rect.left) / rect.width * state.columns,
                y: (event.clientY - rect.top) / rect.height * state.rows,
            };
        }

        function candidateFor(event) {
            if (!interaction) return null;
            const point = surfacePoint(event);
            if (!point) return null;
            const start = interaction.start;
            if (interaction.type === "move") {
                return {
                    block: start.block,
                    x: clamp(Math.round(start.x + point.x - interaction.startPoint.x), 0, state.columns - start.w),
                    y: clamp(Math.round(start.y + point.y - interaction.startPoint.y), 0, state.rows - start.h),
                    w: start.w,
                    h: start.h,
                };
            }
            return {
                block: start.block,
                x: start.x,
                y: start.y,
                w: clamp(Math.round(start.w + point.x - interaction.startPoint.x), 1, state.columns - start.x),
                h: clamp(Math.round(start.h + point.y - interaction.startPoint.y), 1, state.rows - start.y),
            };
        }

        function preview(event) {
            if (!interaction) return false;
            const candidate = candidateFor(event);
            if (!candidate) return false;
            interaction.candidate = candidate;
            const card = cards.get(interaction.key);
            if (!card) return false;
            paint(card, candidate);
            card.item.classList.add("is-active", "is-preview");
            card.item.classList.toggle("is-invalid", overlapsAnother(candidate, interaction.key));
            return true;
        }

        function onPointerMove(event) {
            if (!interaction || (event.pointerId !== undefined && event.pointerId !== interaction.pointerId)) return;
            if (preview(event) && event.cancelable !== false && event.preventDefault) event.preventDefault();
        }

        function releaseCapture() {
            if (!interaction || !interaction.handle || interaction.pointerId === undefined) return;
            const handle = interaction.handle;
            if (typeof handle.releasePointerCapture !== "function") return;
            try {
                if (typeof handle.hasPointerCapture === "function"
                    && !handle.hasPointerCapture(interaction.pointerId)) return;
                handle.releasePointerCapture(interaction.pointerId);
            } catch (error) {
                return;
            }
        }

        function stopInteraction() {
            if (!interaction) return;
            releaseCapture();
            document.removeEventListener("pointermove", onPointerMove);
            document.removeEventListener("pointerup", onPointerUp);
            document.removeEventListener("pointercancel", onPointerCancel);
            document.removeEventListener("keydown", onInteractionKey);
            const card = cards.get(interaction.key);
            if (card) {
                card.item.classList.remove("is-active", "is-preview");
                if (interaction.handle) interaction.handle.classList.remove("is-grabbed");
            }
            interaction = null;
        }

        function cancelInteraction(message) {
            if (!interaction) return;
            const card = cards.get(interaction.key);
            stopInteraction();
            renderLayout();
            if (card) card.item.classList.remove("is-invalid");
            setStatus(message || "");
        }

        function finishInteraction() {
            if (!interaction) return;
            const candidate = interaction.candidate;
            const key = interaction.key;
            const start = interaction.start;
            const verb = interaction.type;
            const card = cards.get(key);
            if (!candidate || samePlacement(candidate, start)) {
                stopInteraction();
                renderLayout();
                return;
            }
            if (overlapsAnother(candidate, key)) {
                stopInteraction();
                renderLayout();
                if (card) card.item.classList.add("is-invalid");
                setStatus(labelFor(labels, candidate.block) + " overlaps another block; the " + verb + " was refused.");
                return;
            }
            const index = currentIndex(key);
            if (index < 0) {
                stopInteraction();
                renderLayout();
                return;
            }
            state.placements[index] = candidate;
            stopInteraction();
            renderLayout();
            emitChange();
            if (verb === "move") {
                setStatus("Moved " + labelFor(labels, candidate.block) + " to column " + String(candidate.x + 1) + ", row " + String(candidate.y + 1) + ".");
            } else {
                setStatus("Resized " + labelFor(labels, candidate.block) + " to " + String(candidate.w) + " by " + String(candidate.h) + " cells.");
            }
        }

        function onPointerUp(event) {
            if (!interaction || (event.pointerId !== undefined && event.pointerId !== interaction.pointerId)) return;
            preview(event);
            finishInteraction();
        }

        function onPointerCancel(event) {
            if (!interaction || (event.pointerId !== undefined && event.pointerId !== interaction.pointerId)) return;
            cancelInteraction("Change cancelled.");
        }

        function onInteractionKey(event) {
            if (event.key !== "Escape") return;
            if (event.preventDefault) event.preventDefault();
            cancelInteraction("Change cancelled.");
        }

        function beginInteraction(card, key, type, event) {
            if (destroyed || interaction) return;
            if (event.button !== undefined && event.button !== 0) return;
            if (event.isPrimary === false) return;
            const index = currentIndex(key);
            if (index < 0) return;
            const startPoint = surfacePoint(event);
            if (!startPoint) return;
            if (event.preventDefault) event.preventDefault();
            const start = state.placements[index];
            interaction = {
                key, type, start: {block: start.block, x: start.x, y: start.y, w: start.w, h: start.h},
                startPoint, pointerId: event.pointerId, candidate: null, handle: card.handle,
            };
            if (event.pointerId !== undefined && typeof card.handle.setPointerCapture === "function") {
                try {
                    card.handle.setPointerCapture(event.pointerId);
                } catch {}
            }
            card.item.classList.remove("is-invalid");
            card.item.classList.add("is-active");
            card.handle.classList.add("is-grabbed");
            setStatus("");
            document.addEventListener("pointermove", onPointerMove);
            document.addEventListener("pointerup", onPointerUp);
            document.addEventListener("pointercancel", onPointerCancel);
            document.addEventListener("keydown", onInteractionKey);
        }

        function acceptedGeometry(candidate, key, message) {
            const index = currentIndex(key);
            if (index < 0) return;
            const card = cards.get(key);
            if (samePlacement(candidate, state.placements[index])) return;
            if (overlapsAnother(candidate, key)) {
                if (card) card.item.classList.add("is-invalid");
                setStatus(labelFor(labels, candidate.block) + " overlaps another block; the change was refused.");
                return;
            }
            state.placements[index] = candidate;
            renderLayout();
            emitChange();
            setStatus(message);
        }

        function keyboardMove(key, event) {
            if (destroyed || interaction) return;
            const index = currentIndex(key);
            if (index < 0) return;
            let dx = 0;
            let dy = 0;
            if (event.key === "ArrowLeft") dx = -1;
            else if (event.key === "ArrowRight") dx = 1;
            else if (event.key === "ArrowUp") dy = -1;
            else if (event.key === "ArrowDown") dy = 1;
            else return;
            if (event.altKey || event.ctrlKey || event.metaKey) return;
            if (event.preventDefault) event.preventDefault();
            const start = state.placements[index];
            const candidate = {
                block: start.block,
                x: clamp(start.x + dx, 0, state.columns - start.w),
                y: clamp(start.y + dy, 0, state.rows - start.h),
                w: start.w,
                h: start.h,
            };
            acceptedGeometry(
                candidate,
                key,
                "Moved " + labelFor(labels, start.block) + " to column " + String(candidate.x + 1) + ", row " + String(candidate.y + 1) + ".",
            );
        }

        function keyboardResize(key, event) {
            if (destroyed || interaction) return;
            const index = currentIndex(key);
            if (index < 0) return;
            let dw = 0;
            let dh = 0;
            if (event.key === "ArrowLeft") dw = -1;
            else if (event.key === "ArrowRight") dw = 1;
            else if (event.key === "ArrowUp") dh = -1;
            else if (event.key === "ArrowDown") dh = 1;
            else return;
            if (event.altKey || event.ctrlKey || event.metaKey) return;
            if (event.preventDefault) event.preventDefault();
            const start = state.placements[index];
            const candidate = {
                block: start.block,
                x: start.x,
                y: start.y,
                w: clamp(start.w + dw, 1, state.columns - start.x),
                h: clamp(start.h + dh, 1, state.rows - start.y),
            };
            acceptedGeometry(
                candidate,
                key,
                "Resized " + labelFor(labels, start.block) + " to " + String(candidate.w) + " by " + String(candidate.h) + " cells.",
            );
        }

        function reorder(key, direction) {
            if (destroyed || interaction) return;
            const index = currentIndex(key);
            const target = index + direction;
            if (index < 0 || target < 0 || target >= state.placements.length) return;
            const placement = state.placements[index];
            state.placements.splice(index, 1);
            state.placements.splice(target, 0, placement);
            renderLayout();
            const card = cards.get(key);
            const action = direction < 0 ? card.earlier : card.later;
            if (action.disabled) card.handle.focus(); else action.focus();
            emitChange();
            setStatus("Moved " + labelFor(labels, placement.block) + " to navigation position " + String(target + 1) + ".");
        }

        function setLayout(layout, nextLabels) {
            if (destroyed) return;
            const next = normalizeLayout(layout);
            if (arguments.length > 1) labels = readLabels(nextLabels);
            if (interaction) {
                stopInteraction();
            }
            state = next;
            setStatus("");
            renderLayout();
        }

        function destroy() {
            if (destroyed) return;
            destroyed = true;
            stopInteraction();
            if (rootElement.parentNode) rootElement.parentNode.removeChild(rootElement);
            cards.clear();
        }

        renderLayout();
        return {setLayout, destroy};
    }

    const api = {mount};
    if (typeof window !== "undefined") window.KioskPageGrid = api;
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
