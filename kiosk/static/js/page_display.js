"use strict";

(function (global) {
    const PAGE_SCHEMA = 1;
    const MAX_GRID_SIZE = 128;
    const MAX_PLACEMENTS = 256;
    const MAX_TRANSITION_MS = 86400000;
    const UNAVAILABLE = "Content unavailable";
    const EMPTY = "No content";

    function isRecord(value) {
        return Boolean(value) && typeof value === "object" && !Array.isArray(value);
    }

    function own(object, key) {
        return Object.prototype.hasOwnProperty.call(object, key);
    }

    function asText(value, fallback) {
        return typeof value === "string" ? value : (fallback || "");
    }

    function asIdentifier(value) {
        if (typeof value === "string" && value.length > 0 && value.length <= 200) {
            return value;
        }
        if (Number.isSafeInteger(value) && value >= 0) {
            return String(value);
        }
        return "";
    }

    function eventIdentifier(value) {
        if (Number.isSafeInteger(value) && value > 0) {
            return String(value);
        }
        if (typeof value === "string" && /^[1-9]\d*$/.test(value)) {
            return value;
        }
        return "";
    }

    function boundedInteger(value, minimum, maximum, fallback) {
        if (!Number.isInteger(value)) {
            return fallback;
        }
        return Math.min(maximum, Math.max(minimum, value));
    }

    function normalizeMode(value, target) {
        const requested = asText(value).trim().toLowerCase();
        if (requested === "tv" || requested === "kiosk") {
            return requested;
        }
        return asText(target).toLowerCase().startsWith("tv-") ? "tv" : "kiosk";
    }

    function normalizePage(rawPage, index) {
        if (!isRecord(rawPage)) {
            return null;
        }
        const columns = boundedInteger(rawPage.columns, 1, MAX_GRID_SIZE, 12);
        const rows = boundedInteger(rawPage.rows, 1, MAX_GRID_SIZE, 8);
        const placements = [];
        const rawPlacements = Array.isArray(rawPage.placements) ? rawPage.placements : [];
        rawPlacements.slice(0, MAX_PLACEMENTS).forEach((rawPlacement) => {
            if (!isRecord(rawPlacement)) {
                return;
            }
            const blockId = asIdentifier(rawPlacement.block);
            if (!blockId) {
                return;
            }
            const x = boundedInteger(rawPlacement.x, 0, columns - 1, 0);
            const y = boundedInteger(rawPlacement.y, 0, rows - 1, 0);
            const width = boundedInteger(rawPlacement.w, 1, columns - x, 1);
            const height = boundedInteger(rawPlacement.h, 1, rows - y, 1);
            placements.push({blockId, x, y, width, height});
        });
        return {
            id: asIdentifier(rawPage.id) || `page-${index + 1}`,
            name: asText(rawPage.name, `Page ${index + 1}`),
            columns,
            rows,
            placements,
        };
    }

    function indexRecords(value) {
        const result = new Map();
        if (!isRecord(value)) {
            return result;
        }
        Object.keys(value).forEach((key) => {
            const id = asIdentifier(key);
            if (id && isRecord(value[key])) {
                result.set(id, value[key]);
            }
        });
        return result;
    }

    function eventLookup(events) {
        const result = new Map();
        if (!Array.isArray(events)) {
            return result;
        }
        events.forEach((event) => {
            if (!isRecord(event)) {
                return;
            }
            const id = eventIdentifier(event.id);
            if (id && !result.has(id)) {
                result.set(id, event);
            }
        });
        return result;
    }

    function tagLookup(tags) {
        const result = new Map();
        if (!Array.isArray(tags)) {
            return result;
        }
        tags.forEach((tag) => {
            if (!isRecord(tag) || typeof tag.name !== "string") {
                return;
            }
            const id = eventIdentifier(tag.id);
            if (id && !result.has(tag.name)) {
                result.set(tag.name, id);
            }
        });
        return result;
    }

    function transitionDelay(value) {
        const seconds = typeof value === "number" ? value : Number(value);
        if (!Number.isFinite(seconds) || seconds <= 0) {
            return 0;
        }
        return Math.min(MAX_TRANSITION_MS, seconds * 1000);
    }

    function create(documentObject, tagName, className, text) {
        const node = documentObject.createElement(tagName);
        if (className) {
            node.className = className;
        }
        if (typeof text === "string") {
            node.textContent = text;
        }
        return node;
    }

    function setHidden(node, hidden) {
        if (hidden) {
            node.setAttribute("hidden", "");
        } else if (typeof node.removeAttribute === "function") {
            node.removeAttribute("hidden");
        } else {
            node.hidden = false;
        }
    }

    function safeMediaPath(value) {
        if (typeof value !== "string" || value.length === 0 || value.length > 2048) {
            return null;
        }
        if (value !== value.trim() || /[\u0000-\u001f\u007f\\?#]/.test(value)) {
            return null;
        }
        if (value.startsWith("//") || value.startsWith("#") || /^[a-z][a-z0-9+.-]*:/i.test(value)) {
            return null;
        }
        return value;
    }

    function mediaPath(media, reference) {
        if (!media || typeof reference !== "string" || !reference) {
            return null;
        }
        let value = null;
        if (typeof media.get === "function") {
            value = media.get(reference);
        } else if (isRecord(media) && own(media, reference)) {
            value = media[reference];
        }
        return safeMediaPath(value);
    }

    function displayMediaAvailability(event, mode, media) {
        const fields = mode === "tv"
            ? ["image_tv", "image_kiosk", "image_thumb"]
            : ["image_kiosk", "image_thumb", "image_tv"];
        let referenced = false;
        for (const field of fields) {
            const reference = event[field];
            if (typeof reference !== "string" || !reference) {
                continue;
            }
            referenced = true;
            const path = mediaPath(media, reference);
            if (path) {
                return {available: true, path};
            }
        }
        return referenced ? {available: false, path: null} : null;
    }

    function mount(container, options) {
        if (!container || typeof container.replaceChildren !== "function") {
            throw new TypeError("KioskPageDisplay requires a container element");
        }
        const documentObject = container.ownerDocument || (typeof document !== "undefined" ? document : null);
        if (!documentObject || typeof documentObject.createElement !== "function") {
            throw new TypeError("KioskPageDisplay requires a document");
        }
        const windowObject = documentObject.defaultView || (typeof window !== "undefined" ? window : null);
        const bootstrap = isRecord(options) ? options : {};
        const page = isRecord(bootstrap.page) ? bootstrap.page : null;
        const mode = normalizeMode(bootstrap.mode, page && page.target);
        const target = asText(page && page.target, "display").slice(0, 200);
        const orientation = /(?:^|-)portrait(?:-|$)/i.test(target) ? "portrait" : "landscape";
        const root = create(documentObject, "div", "kpd");
        const stage = create(documentObject, "div", "kpd__stage");
        const navigation = create(documentObject, "nav", "kpd__nav");
        const listeners = [];
        const blockBodies = [];
        let selectedIndex = 0;
        let autoTimer = null;
        let destroyed = false;
        let resizeObserver = null;
        let pointerStart = null;
        let pages = [];
        let blocks = new Map();
        let datasets = new Map();
        let eventsById = new Map();
        let tagsByName = new Map();
        const media = bootstrap.media;
        let transitionMilliseconds = 0;
        let pageNameNode = null;
        let pageCounterNode = null;

        root.setAttribute("data-mode", mode);
        root.setAttribute("data-target", target || "display");
        root.setAttribute("data-orientation", orientation);
        root.setAttribute("role", "region");
        root.setAttribute("aria-label", target ? `${target} display` : "Display");
        if (mode === "kiosk") {
            root.setAttribute("tabindex", "0");
        }
        navigation.setAttribute("aria-label", "Pages");
        setHidden(navigation, true);
        root.appendChild(stage);
        root.appendChild(navigation);
        container.replaceChildren(root);

        function listen(targetNode, type, handler, listenerOptions) {
            if (!targetNode || typeof targetNode.addEventListener !== "function") {
                return;
            }
            targetNode.addEventListener(type, handler, listenerOptions);
            listeners.push({
                target: targetNode,
                type,
                handler,
                capture: Boolean(listenerOptions && listenerOptions.capture),
            });
        }

        function clearAutoTimer() {
            if (autoTimer !== null && windowObject && typeof windowObject.clearTimeout === "function") {
                windowObject.clearTimeout(autoTimer);
            }
            autoTimer = null;
        }

        function documentHidden() {
            return Boolean(documentObject.hidden);
        }

        function scheduleAutoTransition() {
            clearAutoTimer();
            if (destroyed || mode !== "tv" || pages.length < 2 || transitionMilliseconds <= 0
                || documentHidden() || !windowObject || typeof windowObject.setTimeout !== "function") {
                return;
            }
            autoTimer = windowObject.setTimeout(() => {
                autoTimer = null;
                if (!destroyed) {
                    showPage(selectedIndex + 1);
                }
            }, transitionMilliseconds);
        }

        function refreshOverflow() {
            blockBodies.forEach((entry) => {
                const body = entry.body;
                const overflowing = Number(body.scrollHeight) > Number(body.clientHeight) + 1
                    || Number(body.scrollWidth) > Number(body.clientWidth) + 1;
                entry.element.setAttribute("data-overflow", overflowing ? "true" : "false");
            });
        }

        function fallbackNode(message) {
            return create(documentObject, "p", "kpd-block__fallback", message);
        }

        function buildMedia(event, title) {
            const availability = displayMediaAvailability(event, mode, media);
            if (!availability) {
                return null;
            }
            const mediaNode = create(documentObject, "div", "kpd-event__media");
            if (!availability.available) {
                mediaNode.appendChild(create(documentObject, "span", "kpd-event__media-placeholder", "Image unavailable"));
                return mediaNode;
            }
            const image = create(documentObject, "img", "kpd-event__image");
            image.setAttribute("src", availability.path);
            image.setAttribute("alt", title);
            image.setAttribute("loading", "lazy");
            image.setAttribute("decoding", "async");
            image.setAttribute("referrerpolicy", "no-referrer");
            const replaceImage = () => {
                if (image.parentNode && typeof image.replaceWith === "function") {
                    image.replaceWith(create(documentObject, "span", "kpd-event__media-placeholder", "Image unavailable"));
                }
            };
            listen(image, "error", replaceImage, {once: true});
            mediaNode.appendChild(image);
            return mediaNode;
        }

        function buildEvent(event) {
            const item = create(documentObject, "li", "kpd-event");
            const id = eventIdentifier(event.id);
            if (id) {
                item.setAttribute("data-event-id", id);
            }
            const titleText = asText(event.title, "Untitled event");
            const mediaNode = buildMedia(event, titleText);
            if (mediaNode) {
                item.appendChild(mediaNode);
            }
            const copy = create(documentObject, "div", "kpd-event__copy");
            const meta = create(documentObject, "div", "kpd-event__meta");
            const dateText = asText(event.event_date);
            const placeText = asText(event.place);
            if (dateText) {
                meta.appendChild(create(documentObject, "span", "kpd-event__date", dateText));
            }
            if (placeText) {
                meta.appendChild(create(documentObject, "span", "kpd-event__place", placeText));
            }
            if (meta.childNodes.length > 0) {
                copy.appendChild(meta);
            }
            copy.appendChild(create(documentObject, "h3", "kpd-event__title", titleText));
            const descriptionText = asText(event.short_description) || asText(event.full_description);
            if (descriptionText) {
                copy.appendChild(create(documentObject, "p", "kpd-event__description", descriptionText));
            }
            item.appendChild(copy);
            return item;
        }

        function resolveBlockEvents(block, dataset) {
            if (!Array.isArray(dataset.events)) {
                return {state: "unavailable", events: []};
            }
            const ids = [];
            for (const value of dataset.events) {
                const id = eventIdentifier(value);
                if (!id) {
                    return {state: "unavailable", events: []};
                }
                ids.push(id);
            }
            const loaded = ids.map((id) => eventsById.get(id)).filter(Boolean);
            if (ids.length > 0 && loaded.length === 0) {
                return {state: "unavailable", events: []};
            }
            const requestedTags = Array.isArray(block.tags) ? block.tags : [];
            let filtered = loaded;
            if (requestedTags.length > 0) {
                if (!requestedTags.every((name) => typeof name === "string")) {
                    return {state: "unavailable", events: []};
                }
                const selectedTags = new Set();
                requestedTags.forEach((name) => {
                    const tagId = tagsByName.get(name);
                    if (tagId) {
                        selectedTags.add(tagId);
                    }
                });
                if (selectedTags.size === 0) {
                    filtered = [];
                } else {
                    filtered = loaded.filter((event) => Array.isArray(event.tag_ids)
                        && event.tag_ids.some((tagId) => selectedTags.has(eventIdentifier(tagId))));
                }
            }
            if (Number.isInteger(block.limit) && block.limit >= 0) {
                filtered = filtered.slice(0, block.limit);
            }
            return {state: filtered.length > 0 ? "ready" : "empty", events: filtered};
        }

        function buildBlock(blockId, placement) {
            const block = blocks.get(blockId);
            const blockNode = create(documentObject, "article", "kpd-block");
            blockNode.setAttribute("data-block-id", blockId);
            blockNode.setAttribute("data-grid-x", String(placement.x));
            blockNode.setAttribute("data-grid-y", String(placement.y));
            blockNode.setAttribute("data-grid-width", String(placement.width));
            blockNode.setAttribute("data-grid-height", String(placement.height));
            blockNode.style.setProperty("grid-column", `${placement.x + 1} / span ${placement.width}`);
            blockNode.style.setProperty("grid-row", `${placement.y + 1} / span ${placement.height}`);
            if (!block) {
                blockNode.setAttribute("data-state", "unavailable");
                blockNode.appendChild(fallbackNode(UNAVAILABLE));
                return blockNode;
            }
            const appearance = block.appearance === "list" ? "list" : "cards";
            blockNode.className = `kpd-block kpd-block--${appearance}`;
            blockNode.setAttribute("data-appearance", appearance);
            if (block.schema !== undefined && block.schema !== PAGE_SCHEMA) {
                blockNode.setAttribute("data-state", "unavailable");
                blockNode.appendChild(fallbackNode(UNAVAILABLE));
                return blockNode;
            }
            const header = create(documentObject, "header", "kpd-block__header");
            header.appendChild(create(documentObject, "h2", "kpd-block__title", asText(block.name, "Content")));
            blockNode.appendChild(header);
            const body = create(documentObject, "div", "kpd-block__body");
            blockNode.appendChild(body);
            const datasetId = asIdentifier(block.dataset);
            const dataset = datasetId ? datasets.get(datasetId) : null;
            if (!datasetId || !dataset || (dataset.schema !== undefined && dataset.schema !== PAGE_SCHEMA)
                || dataset.module !== "events") {
                blockNode.setAttribute("data-state", "unavailable");
                body.appendChild(fallbackNode(UNAVAILABLE));
                return blockNode;
            }
            const resolved = resolveBlockEvents(block, dataset);
            if (resolved.state === "unavailable") {
                blockNode.setAttribute("data-state", "unavailable");
                body.appendChild(fallbackNode(UNAVAILABLE));
                return blockNode;
            }
            if (resolved.state === "empty") {
                blockNode.setAttribute("data-state", "empty");
                body.appendChild(fallbackNode(EMPTY));
                return blockNode;
            }
            blockNode.setAttribute("data-state", "ready");
            const list = create(documentObject, "ul", "kpd-events");
            resolved.events.forEach((event) => list.appendChild(buildEvent(event)));
            body.appendChild(list);
            blockBodies.push({element: blockNode, body});
            return blockNode;
        }

        function buildPage(pageData) {
            const section = create(documentObject, "section", "kpd-page");
            section.setAttribute("data-page-id", pageData.id);
            section.setAttribute("data-page-name", pageData.name);
            const grid = create(documentObject, "div", "kpd-grid");
            grid.setAttribute("data-columns", String(pageData.columns));
            grid.setAttribute("data-rows", String(pageData.rows));
            grid.style.setProperty("--kpd-columns", String(pageData.columns));
            grid.style.setProperty("--kpd-rows", String(pageData.rows));
            if (pageData.placements.length === 0) {
                const emptyNode = create(documentObject, "p", "kpd-page__fallback", UNAVAILABLE);
                emptyNode.style.setProperty("grid-column", "1 / -1");
                emptyNode.style.setProperty("grid-row", "1 / -1");
                grid.appendChild(emptyNode);
            } else {
                pageData.placements.forEach((placement) => {
                    grid.appendChild(buildBlock(placement.blockId, placement));
                });
            }
            section.appendChild(grid);
            return section;
        }

        function updateNavigation() {
            if (!pageNameNode || !pageCounterNode || pages.length === 0) {
                return;
            }
            const current = pages[selectedIndex];
            pageNameNode.textContent = current.name;
            pageCounterNode.textContent = `${selectedIndex + 1} / ${pages.length}`;
        }

        function showPage(index) {
            if (destroyed || pages.length === 0) {
                return false;
            }
            selectedIndex = ((Math.trunc(index) % pages.length) + pages.length) % pages.length;
            blockBodies.length = 0;
            stage.replaceChildren(buildPage(pages[selectedIndex]));
            updateNavigation();
            refreshOverflow();
            scheduleAutoTransition();
            return true;
        }

        function bindNavigation() {
            if (pages.length < 2) {
                return;
            }
            const previousButton = create(documentObject, "button", "kpd__nav-button");
            previousButton.setAttribute("type", "button");
            previousButton.setAttribute("aria-label", "Previous page");
            previousButton.textContent = "Previous";
            const position = create(documentObject, "div", "kpd__position");
            pageNameNode = create(documentObject, "span", "kpd__page-name");
            pageCounterNode = create(documentObject, "span", "kpd__counter");
            pageCounterNode.setAttribute("aria-live", "polite");
            position.appendChild(pageNameNode);
            position.appendChild(pageCounterNode);
            const nextButton = create(documentObject, "button", "kpd__nav-button");
            nextButton.setAttribute("type", "button");
            nextButton.setAttribute("aria-label", "Next page");
            nextButton.textContent = "Next";
            navigation.appendChild(previousButton);
            navigation.appendChild(position);
            navigation.appendChild(nextButton);
            setHidden(navigation, mode !== "kiosk");
            listen(previousButton, "click", () => showPage(selectedIndex - 1));
            listen(nextButton, "click", () => showPage(selectedIndex + 1));
        }

        function bindKioskGestures() {
            if (mode !== "kiosk") {
                return;
            }
            listen(stage, "pointerdown", (event) => {
                if (event.button !== undefined && event.button !== 0) {
                    return;
                }
                pointerStart = {x: event.clientX, y: event.clientY, id: event.pointerId};
            }, {passive: true});
            listen(stage, "pointerup", (event) => {
                if (!pointerStart || (pointerStart.id !== undefined && event.pointerId !== undefined
                    && pointerStart.id !== event.pointerId)) {
                    pointerStart = null;
                    return;
                }
                const deltaX = Number(event.clientX) - Number(pointerStart.x);
                const deltaY = Number(event.clientY) - Number(pointerStart.y);
                pointerStart = null;
                if (Math.abs(deltaX) >= 48 && Math.abs(deltaX) > Math.abs(deltaY) * 1.25) {
                    showPage(selectedIndex + (deltaX < 0 ? 1 : -1));
                }
            }, {passive: true});
            listen(stage, "pointercancel", () => {
                pointerStart = null;
            }, {passive: true});
            listen(root, "keydown", (event) => {
                if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
                    return;
                }
                if (typeof event.preventDefault === "function") {
                    event.preventDefault();
                }
                showPage(selectedIndex + (event.key === "ArrowRight" ? 1 : -1));
            });
        }

        function bindRuntimeObservers() {
            if (!windowObject || typeof windowObject.addEventListener !== "function") {
                return;
            }
            listen(windowObject, "resize", refreshOverflow, {passive: true});
            listen(windowObject, "pagehide", clearAutoTimer);
            listen(windowObject, "pageshow", scheduleAutoTransition);
            listen(documentObject, "visibilitychange", () => {
                if (documentHidden()) {
                    clearAutoTimer();
                } else {
                    scheduleAutoTransition();
                }
            });
            if (typeof windowObject.ResizeObserver === "function") {
                resizeObserver = new windowObject.ResizeObserver(refreshOverflow);
                resizeObserver.observe(stage);
            }
        }

        function destroy() {
            if (destroyed) {
                return;
            }
            destroyed = true;
            clearAutoTimer();
            if (resizeObserver && typeof resizeObserver.disconnect === "function") {
                resizeObserver.disconnect();
            }
            resizeObserver = null;
            while (listeners.length > 0) {
                const entry = listeners.pop();
                if (entry.target && typeof entry.target.removeEventListener === "function") {
                    entry.target.removeEventListener(entry.type, entry.handler, entry.capture);
                }
            }
            blockBodies.length = 0;
            if (root.parentNode && typeof root.parentNode.removeChild === "function") {
                root.parentNode.removeChild(root);
            } else if (typeof root.remove === "function") {
                root.remove();
            }
        }

        const controller = {
            destroy,
            next: () => showPage(selectedIndex + 1),
            previous: () => showPage(selectedIndex - 1),
            showPage: (index) => showPage(index),
        };

        if (!page || page.schema !== PAGE_SCHEMA || !Array.isArray(page.pages)) {
            stage.appendChild(create(documentObject, "p", "kpd-page__fallback", UNAVAILABLE));
            return controller;
        }

        pages = page.pages.map(normalizePage).filter(Boolean);
        blocks = indexRecords(page.blocks);
        datasets = indexRecords(page.datasets);
        eventsById = eventLookup(bootstrap.events);
        tagsByName = tagLookup(bootstrap.tags);
        transitionMilliseconds = transitionDelay(page.transition_seconds);

        if (pages.length === 0) {
            stage.appendChild(create(documentObject, "p", "kpd-page__fallback", UNAVAILABLE));
            return controller;
        }

        const requestedPage = asIdentifier(page.start_page);
        let initialIndex = pages.findIndex((entry) => entry.id === requestedPage);
        if (initialIndex < 0 && Number.isInteger(page.start_page)
            && page.start_page >= 0 && page.start_page < pages.length) {
            initialIndex = page.start_page;
        }
        selectedIndex = initialIndex >= 0 ? initialIndex : 0;

        bindNavigation();
        bindKioskGestures();
        bindRuntimeObservers();
        showPage(selectedIndex);
        return controller;
    }

    const api = {mount};
    if (typeof module !== "undefined" && module.exports) {
        module.exports = api;
    }
    if (global) {
        global.KioskPageDisplay = api;
    }
})(typeof window !== "undefined" ? window : (typeof globalThis !== "undefined" ? globalThis : null));
