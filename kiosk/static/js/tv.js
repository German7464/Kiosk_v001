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
    return Boolean(fullscreenRequestHandler() && fullscreenExitHandler());
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
    const wasEmpty = tvEvents.length === 0;
    tvEvents = eventsData.events || [];
    currentContentVersion = versionData.content_version;
    tvVersion.textContent = `${labels.versionLabel} ${currentContentVersion}`;

    if (tvEvents.length === 0) {
        window.clearTimeout(slideTimer);
        tvCard.hidden = true;
        tvEmptyState.hidden = false;
        return;
    }

    tvCard.hidden = false;
    tvEmptyState.hidden = true;

    if (currentEvent) {
        const nextIndex = tvEvents.findIndex((event) => event.id === currentEvent.id);
        tvEventIndex = nextIndex >= 0 ? (nextIndex + 1) % tvEvents.length : 0;
    } else {
        tvEventIndex = 0;
    }

    if (showCurrentEvent || wasEmpty) {
        showNextTvEvent();
    }
}

async function loadTvData(showCurrentEvent) {
    const [versionResponse, eventsResponse] = await Promise.all([
        fetch("/api/version"),
        fetch("/api/events"),
    ]);

    const versionData = await versionResponse.json();
    const eventsData = await eventsResponse.json();

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
    if (updatePending) {
        return;
    }

    const versionResponse = await fetch("/api/version");
    const versionData = await versionResponse.json();

    if (currentContentVersion !== null && versionData.content_version !== currentContentVersion) {
        updatePending = true;
        window.setTimeout(refreshTvWhenSafe, randomUpdateDelay());
    }
}

async function loadTvDisplay() {
    await loadTvData(true);
}

setupTvFullscreenButton();

loadTvDisplay().catch(() => {
    tvVersion.textContent = labels.versionUnavailable;
    tvCard.hidden = true;
    tvEmptyState.hidden = false;
});
window.setInterval(() => {
    pollTvVersion().catch(() => {
        tvVersion.textContent = labels.versionUnavailable;
    });
}, versionPollInterval);
