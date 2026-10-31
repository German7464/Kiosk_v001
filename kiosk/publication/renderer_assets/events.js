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
        card.replaceChildren();
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
        card.appendChild(text("p", "event-date", event.event_date || t("common.date_to_be_announced")));
        card.appendChild(text("h2", "event-title", event.title));
        card.appendChild(text("p", "event-description", event.short_description || event.full_description || t("common.no_description")));
        card.appendChild(text("p", "event-place", event.place || t("common.place_to_be_announced")));
        if (mode === "tv" && count > 1) {
            slideTimer = window.setTimeout(() => { model.move(1); render(); },
                eventsSlideDuration(event, data.settings.tv_slide_duration));
        }
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
    render();
    resetIdle();
}

if (typeof module !== "undefined") module.exports = {createEventsModel, eventsSlideDuration, mountEventsView};
if (typeof document !== "undefined") {
    mountEventsView(document, window, JSON.parse(document.getElementById("bootstrap").textContent));
}
