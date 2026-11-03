"use strict";

function createEventsModel(data) {
    let tag = null;
    let index = 0;
    const filtered = () => tag === null ? data.events : data.events.filter(event => event.tag_ids.includes(tag));
    return {
        events: filtered,
        current: () => filtered()[index] || null,
        index: () => index,
        tag: () => tag,
        select(value) {
            tag = data.tags.some(item => item.id === value) ? value : null;
            index = 0;
        },
        move(direction) {
            const count = filtered().length;
            index = count ? (index + direction + count) % count : 0;
        },
        reset() { tag = null; index = 0; }
    };
}

function eventsSlideDuration(event, seconds) {
    const duration = Number(seconds);
    const base = Number.isFinite(duration) && duration > 0 ? duration * 1000 : 8000;
    const text = [event.title, event.short_description, event.place].filter(Boolean).join(" ");
    return Math.min(24000, Math.max(8000, base + text.length * 70));
}

// Measure only the next page: large publications must not build an unbounded page list.
function createEventsTextPager(fields, makeNode, fits) {
    let field = 0;
    let offset = 0;
    const segmenter = typeof Intl.Segmenter === "function" ? new Intl.Segmenter(undefined, {granularity: "grapheme"}) : null;
    function boundary(value, end) {
        if (end <= 0) return 0;
        if (end >= value.length) return value.length;
        if (segmenter) {
            const item = segmenter.segment(value).containing(end - 1);
            return item.index + item.segment.length <= end ? end : item.index;
        }
        // Older engines still must not split a UTF-16 surrogate pair.
        return /[\uD800-\uDBFF]/.test(value[end - 1]) ? end - 1 : end;
    }
    return {
        more: () => field < fields.length,
        next(container) {
            container.replaceChildren();
            let visible = "";
            let progressed = false;
            while (field < fields.length) {
                const item = fields[field];
                if (offset === item.value.length) { field++; offset = 0; continue; }
                // Limit each layout probe, rather than laying out the entire remaining description.
                const limit = boundary(item.value, Math.min(item.value.length, offset + 16384));
                const remaining = item.value.slice(offset, limit);
                const node = makeNode(item.tag, item.className, "");
                container.appendChild(node);
                let low = 0, high = remaining.length;
                while (low < high) {
                    const middle = Math.ceil((low + high) / 2);
                    node.textContent = remaining.slice(0, boundary(remaining, middle));
                    if (fits()) low = middle; else high = middle - 1;
                }
                let end = boundary(remaining, low);
                // Prefer a nearby word boundary, retaining every whitespace/code unit.
                if (end < remaining.length || offset + end < item.value.length) {
                    const prefix = remaining.slice(0, end);
                    const word = Math.max(prefix.lastIndexOf(" "), prefix.lastIndexOf("\n"));
                    if (word >= end * .75) end = boundary(remaining, word + 1);
                }
                node.textContent = remaining.slice(0, end);
                if (!end) { node.remove(); break; }
                progressed = true;
                visible += node.textContent;
                offset += end;
                if (offset < item.value.length) break;
                field++; offset = 0;
            }
            return {visible, progressed, more: field < fields.length};
        }
    };
}

function mountEventsView(document, window, bootstrap) {
    const {data, labels, media, mode} = bootstrap;
    const model = createEventsModel(data);
    const element = id => document.getElementById(id);
    const t = key => labels[key] || key;
    const card = element("card");
    const home = element("home");
    const events = element("events");
    const warning = element("inactivity");
    let slideTimer = null;
    let idleTimer = null;
    let countdownTimer = null;
    let idleDeadline = 0;
    let resizeTimer = null;
    let advanceSlide = null;
    let currentDuration = 0;

    function armSlide() {
        window.clearTimeout(slideTimer);
        if (advanceSlide && !document.hidden) slideTimer = window.setTimeout(advanceSlide, currentDuration);
    }

    function text(tag, className, value) {
        const node = document.createElement(tag);
        node.className = className;
        node.textContent = value;
        return node;
    }

    function resetIdle() {
        window.clearTimeout(idleTimer);
        window.clearInterval(countdownTimer);
        warning.hidden = true;
        if (mode === "tv" || !home.hidden) return;
        idleTimer = window.setTimeout(() => {
            idleDeadline = Date.now() + 30000;
            function tick() {
                const remaining = Math.max(0, Math.ceil((idleDeadline - Date.now()) / 1000));
                warning.textContent = `${t("kiosk.inactivity_warning_text")} ${remaining}`;
                warning.hidden = false;
                if (remaining === 0) showHome();
            }
            tick();
            countdownTimer = window.setInterval(tick, 1000);
        }, 90000);
    }

    function showHome() {
        model.reset();
        home.hidden = false;
        events.hidden = true;
        resetIdle();
    }

    function render() {
        window.clearTimeout(slideTimer);
        advanceSlide = null;
        card.replaceChildren();
        card.setAttribute("data-tv-layout", "single");
        const event = model.current();
        const count = model.events().length;
        element("counter").textContent = `${count ? model.index() + 1 : 0} / ${count}`;
        element("previous").disabled = count < 2;
        element("next").disabled = count < 2;
        for (const button of element("tags").children) {
            button.setAttribute("aria-pressed", String(button.tagId === model.tag()));
        }
        if (!event) {
            card.appendChild(text("h2", "empty", t("tv.no_active_events")));
            return;
        }
        const reference = mode === "tv" ? event.image_tv || event.image_kiosk : event.image_kiosk;
        const placeholder = () => text("span", "image-placeholder", t("common.image_area"));
        if (reference && Object.prototype.hasOwnProperty.call(media, reference)) {
            const image = document.createElement("img");
            image.className = "event-image";
            image.alt = event.title;
            image.addEventListener("error", () => image.replaceWith(placeholder()), {once: true});
            image.src = media[reference];
            card.appendChild(image);
        } else card.appendChild(placeholder());
        const fields = [
            {tag: "p", className: "event-date", value: event.event_date || t("common.date_to_be_announced")},
            {tag: "h2", className: "event-title", value: event.title},
            {tag: "p", className: "event-description", value: event.short_description || event.full_description || t("common.no_description")},
            {tag: "p", className: "event-place", value: event.place || t("common.place_to_be_announced")}
        ];
        if (mode !== "tv") {
            for (const item of fields) card.appendChild(text(item.tag, item.className, item.value));
            return;
        }
        const copy = text("div", "tv-copy", "");
        const content = text("div", "tv-text", "");
        const part = text("span", "tv-part", "");
        copy.appendChild(content);
        copy.appendChild(part);
        card.appendChild(copy);
        for (const item of fields) content.appendChild(text(item.tag, item.className, item.value));
        const fits = () => content.scrollHeight <= content.clientHeight + 1 && content.scrollWidth <= content.clientWidth + 1;
        const nextEvent = () => { model.move(1); render(); };
        // A collapsed viewport cannot advance unread content. A later resize retries layout.
        if (typeof content.clientHeight === "number" && content.clientHeight <= 0) {
            content.replaceChildren(text("p", "tv-layout-error", t("tv.layout_unavailable")));
            card.setAttribute("data-tv-layout", "unavailable");
            return;
        }
        if (fits()) {
            currentDuration = eventsSlideDuration(event, data.settings.tv_slide_duration);
            advanceSlide = count > 1 ? nextEvent : null;
            armSlide();
            return;
        }
        const context = text("div", "tv-context", "");
        for (const index of [0, 1, 3]) {
            const item = fields[index];
            context.appendChild(text(item.tag, item.className, item.value));
        }
        copy.insertBefore(context, content);
        // Keep metadata only when it leaves a useful reading area. Otherwise paginate it too.
        const fixedContext = context.scrollHeight <= copy.clientHeight * .45 && content.clientHeight >= 64;
        if (!fixedContext) context.remove();
        const pager = createEventsTextPager(fixedContext ? [fields[2]] : fields, text, fits);
        let page = 0;
        function showPart() {
            const result = pager.next(content);
            if (!result.progressed) {
                content.replaceChildren(text("p", "tv-layout-error", t("tv.layout_unavailable")));
                part.textContent = "";
                part.style.visibility = "hidden";
                advanceSlide = null;
                card.setAttribute("data-tv-layout", "unavailable");
                return;
            }
            page++;
            card.setAttribute("data-tv-layout", "paginated");
            part.style.visibility = "visible";
            part.textContent = `${t("tv.part")} ${page}`;
            const visible = (fixedContext ? context.textContent : "") + result.visible;
            currentDuration = eventsSlideDuration({short_description: visible}, data.settings.tv_slide_duration);
            advanceSlide = result.more ? showPart : nextEvent;
            armSlide();
        }
        showPart();
    }

    document.body.classList.toggle("tv", mode === "tv");
    element("heading").textContent = t("kiosk.current_events");
    element("version").textContent = `${t("common.version")} ${data.content_version}`;
    element("home-button").textContent = t("common.back_to_home");
    element("open-events").textContent = t("kiosk.open_events");
    for (const field of ["label", "heading", "description"]) {
        element(`home-${field}`).textContent = data.settings[`kiosk_${field}`] || t(`kiosk.home_${field}`);
    }
    element("tags").setAttribute("aria-label", t("admin.tags"));
    for (const tag of [{id: null, name: t("common.all_events")}, ...data.tags]) {
        const button = text("button", "tag", tag.name);
        button.type = "button";
        button.tagId = tag.id;
        button.addEventListener("click", () => { model.select(tag.id); render(); resetIdle(); });
        element("tags").appendChild(button);
    }
    for (const [id, direction, label] of [["previous", -1, "common.previous"], ["next", 1, "common.next"]]) {
        element(id).textContent = t(label);
        element(id).addEventListener("click", () => { model.move(direction); render(); resetIdle(); });
    }
    element("home-button").addEventListener("click", showHome);
    element("open-events").addEventListener("click", () => {
        home.hidden = true;
        events.hidden = false;
        render();
        resetIdle();
    });
    document.addEventListener("pointerdown", resetIdle);
    document.addEventListener("keydown", event => {
        resetIdle();
        if (!home.hidden || mode === "tv") return;
        if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
            event.preventDefault();
            model.move(event.key === "ArrowRight" ? 1 : -1);
            render();
        }
    });
    if (mode === "tv") {
        window.addEventListener("resize", () => {
            window.clearTimeout(slideTimer);
            window.clearTimeout(resizeTimer);
            resizeTimer = window.setTimeout(render, 150);
        });
        document.addEventListener("visibilitychange", armSlide);
        window.addEventListener("pagehide", () => {
            window.clearTimeout(slideTimer);
            window.clearTimeout(resizeTimer);
        });
        window.addEventListener("pageshow", render);
    }
    render();
    resetIdle();
}

if (typeof module !== "undefined") module.exports = {createEventsModel, eventsSlideDuration, createEventsTextPager, mountEventsView};
if (typeof document !== "undefined") {
    mountEventsView(document, window, JSON.parse(document.getElementById("bootstrap").textContent));
}
