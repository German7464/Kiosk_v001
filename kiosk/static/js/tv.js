const tvScreen = document.querySelector(".tv-screen");
const tvCard = document.querySelector("[data-tv-card]");
const tvImage = document.querySelector("[data-tv-image]");
const tvDate = document.querySelector("[data-tv-date]");
const tvTitle = document.querySelector("[data-tv-title]");
const tvPlace = document.querySelector("[data-tv-place]");
const tvDescription = document.querySelector("[data-tv-description]");
const tvVersion = document.querySelector("[data-tv-version]");
const tvEmptyState = document.querySelector("[data-tv-empty-state]");
const tvFullscreenButton = document.querySelector("[data-tv-fullscreen]");
const baseSlideDuration = Number(tvScreen.dataset.slideDuration);
const minSlideDuration = 8000;
const maxSlideDuration = 24000;
const versionPollInterval = Number(tvScreen.dataset.versionPollInterval);
const updateDelayMax = Number(tvScreen.dataset.updateDelayMax);
const labels = tvScreen.dataset;

let tvEvents = [];
let tvEventIndex = 0;
let currentContentVersion = null;
let updatePending = false;
let versionPollActive = false;
let transitionActive = false;
let slideTimer = null;

function fullscreenElement() {
    return document.fullscreenElement || document.webkitFullscreenElement || document.msFullscreenElement;
}

function fullscreenTarget() {
    return document.documentElement;
}

function fullscreenRequestHandler() {
    const target = fullscreenTarget();
    return target.requestFullscreen || target.webkitRequestFullscreen || target.msRequestFullscreen;
}

function fullscreenExitHandler() {
    return document.exitFullscreen || document.webkitExitFullscreen || document.msExitFullscreen;
}

function fullscreenSupported() {
    return Boolean(fullscreenRequestHandler());
}

function fullscreenCanExit() {
    return Boolean(fullscreenExitHandler());
}

function updateFullscreenButtonState() {
    if (!tvFullscreenButton) {
        return;
    }

    const isFullscreen = Boolean(fullscreenElement());
    const label = isFullscreen
        ? tvFullscreenButton.dataset.fullscreenExit
        : tvFullscreenButton.dataset.fullscreenEnter;

    tvFullscreenButton.setAttribute("aria-label", label);
    tvFullscreenButton.setAttribute("title", label);
    tvFullscreenButton.setAttribute("aria-pressed", String(isFullscreen));
}

function handleFullscreenResult(result) {
    if (result && typeof result.catch === "function") {
        result.catch(() => {});
    }
}

function toggleTvFullscreen() {
    if (!fullscreenSupported()) {
        return;
    }

    if (fullscreenElement()) {
        if (!fullscreenCanExit()) {
            return;
        }

        handleFullscreenResult(fullscreenExitHandler().call(document));
        return;
    }

    const target = fullscreenTarget();
    handleFullscreenResult(fullscreenRequestHandler().call(target));
}

function setupTvFullscreenButton() {
    if (!tvFullscreenButton) {
        return;
    }

    if (!fullscreenSupported()) {
        tvFullscreenButton.hidden = true;
        return;
    }

    tvFullscreenButton.addEventListener("click", toggleTvFullscreen);
    document.addEventListener("fullscreenchange", updateFullscreenButtonState);
    document.addEventListener("webkitfullscreenchange", updateFullscreenButtonState);
    document.addEventListener("msfullscreenchange", updateFullscreenButtonState);
    updateFullscreenButtonState();
}

function setTvEmptyMode(isEmpty) {
    tvScreen.classList.toggle("tv-screen--empty", isEmpty);
}

function eventTextLength(event) {
    return [event.title, event.short_description, event.place]
        .filter(Boolean)
        .join(" ")
        .length;
}

function slideDurationForEvent(event) {
    const readingTime = eventTextLength(event) * 70;
    return Math.min(maxSlideDuration, Math.max(minSlideDuration, baseSlideDuration + readingTime));
}

function scheduleNextTvEvent(event) {
    window.clearTimeout(slideTimer);

    if (tvEvents.length < 2) {
        return;
    }

    slideTimer = window.setTimeout(showNextTvEvent, slideDurationForEvent(event));
}

function applyTvEvent(event) {
    transitionActive = true;
    tvCard.classList.remove("is-visible");

    window.setTimeout(() => {
        tvDate.textContent = event.event_date || labels.datePlaceholder;
        tvTitle.textContent = event.title;
        tvPlace.textContent = event.place || labels.placePlaceholder;
        tvDescription.textContent = event.short_description || labels.descriptionPlaceholder;

        setTvImage(event.image_tv || event.image_kiosk);

        tvCard.classList.add("is-visible");
        transitionActive = false;
        scheduleNextTvEvent(event);
    }, 220);
}

function showTvImagePlaceholder() {
    tvImage.style.backgroundImage = "";
    tvImage.innerHTML = `<span>${labels.imageArea}</span>`;
}

function setTvImage(imageUrl) {
    if (!imageUrl) {
        showTvImagePlaceholder();
        return;
    }

    const image = new Image();
    image.onload = () => {
        tvImage.innerHTML = "";
        tvImage.style.backgroundImage = `url("${imageUrl}")`;
    };
    image.onerror = showTvImagePlaceholder;
    image.src = imageUrl;
}

function showNextTvEvent() {
    if (tvEvents.length === 0) {
        return;
    }

    applyTvEvent(tvEvents[tvEventIndex]);
    tvEventIndex = (tvEventIndex + 1) % tvEvents.length;
}

function randomUpdateDelay() {
    return Math.floor(Math.random() * (updateDelayMax + 1));
}

function applyTvData(versionData, eventsData, showCurrentEvent) {
    const currentEvent = tvEvents[(tvEventIndex + tvEvents.length - 1) % tvEvents.length];
    tvEvents = eventsData.events || [];
    currentContentVersion = versionData.content_version;
    tvVersion.textContent = `${labels.versionLabel} ${currentContentVersion}`;

    if (tvEvents.length === 0) {
        window.clearTimeout(slideTimer);
        tvCard.hidden = true;
        tvEmptyState.hidden = false;
        setTvEmptyMode(true);
        return;
    }

    tvCard.hidden = false;
    tvEmptyState.hidden = true;
    setTvEmptyMode(false);

    const currentIndex = currentEvent ? tvEvents.findIndex((event) => event.id === currentEvent.id) : -1;
    tvEventIndex = currentIndex >= 0 ? (currentIndex + 1) % tvEvents.length : 0;

    if (showCurrentEvent || currentIndex < 0) {
        showNextTvEvent();
    } else {
        applyTvEvent(tvEvents[currentIndex]);
    }
}

async function requestTvJson(path) {
    const response = await fetch(path);
    if (!response.ok) {
        throw new Error("TV request failed");
    }
    return response.json();
}

async function loadTvVersion() {
    const data = await requestTvJson("/api/version");
    if (!data || !Number.isInteger(data.content_version) || data.content_version < 0) {
        throw new Error("Invalid TV version");
    }
    return data;
}

async function loadTvEvents() {
    const data = await requestTvJson("/api/events");
    const textFields = ["event_date", "place", "short_description", "image_tv", "image_kiosk"];
    if (!data || !Array.isArray(data.events) || !data.events.every((event) => (
        event && Number.isInteger(event.id) && event.id > 0 && typeof event.title === "string"
        && textFields.every((name) => event[name] == null || typeof event[name] === "string")
    ))) {
        throw new Error("Invalid TV events");
    }
    return data;
}

async function loadTvData(showCurrentEvent) {
    const [versionData, eventsData] = await Promise.all([loadTvVersion(), loadTvEvents()]);

    applyTvData(versionData, eventsData, showCurrentEvent);
}

function refreshTvWhenSafe() {
    if (transitionActive) {
        window.setTimeout(refreshTvWhenSafe, 250);
        return;
    }

    loadTvData(false)
        .catch(() => {
            tvVersion.textContent = labels.versionUnavailable;
        })
        .finally(() => {
            updatePending = false;
        });
}

async function pollTvVersion() {
    if (updatePending || versionPollActive) {
        return;
    }

    versionPollActive = true;
    try {
        const versionData = await loadTvVersion();
        if (currentContentVersion === null || versionData.content_version !== currentContentVersion) {
            updatePending = true;
            window.setTimeout(refreshTvWhenSafe, randomUpdateDelay());
        } else {
            tvVersion.textContent = `${labels.versionLabel} ${currentContentVersion}`;
        }
    } finally {
        versionPollActive = false;
    }
}

async function loadTvDisplay() {
    updatePending = true;
    try {
        await loadTvData(true);
    } finally {
        updatePending = false;
    }
}

setupTvFullscreenButton();

loadTvDisplay().catch(() => {
    tvVersion.textContent = labels.versionUnavailable;
    tvCard.hidden = true;
    tvEmptyState.hidden = false;
    setTvEmptyMode(true);
});
window.setInterval(() => {
    pollTvVersion().catch(() => {
        tvVersion.textContent = labels.versionUnavailable;
    });
}, versionPollInterval);
