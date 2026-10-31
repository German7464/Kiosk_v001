const eventsScreen = document.querySelector(".events-screen");
const eventCard = document.querySelector("[data-event-card]");
const emptyState = document.querySelector("[data-empty-state]");
const cardCounter = document.querySelector("[data-card-counter]");
const previousButton = document.querySelector("[data-previous-event]");
const nextButton = document.querySelector("[data-next-event]");
const tagList = document.querySelector("[data-tag-list]");
const allTags = document.querySelector("[data-all-tags]");
const tagsModal = document.querySelector("[data-tags-modal]");
const openTagsButton = document.querySelector("[data-open-tags]");
const closeTagsButton = document.querySelector("[data-close-tags]");
const contentVersion = document.querySelector("[data-content-version]");
const allEventsButton = document.querySelector("[data-tag-filter='all']");
const inactivityWarning = document.querySelector("[data-inactivity-warning]");
const inactivityWarningCountdown = document.querySelector("[data-inactivity-warning-countdown]");
const inactivityWarningMessage = document.querySelector("[data-inactivity-warning-message]");
const inactivityWarningDelaySeconds = 120;
const inactivityWarningCountdownSeconds = 30;
const versionPollInterval = Number(eventsScreen.dataset.versionPollInterval);
const updateDelayMax = Number(eventsScreen.dataset.updateDelayMax);
const labels = eventsScreen.dataset;

let allEvents = [];
let events = [];
let tags = [];
let currentEventIndex = 0;
let inactivityTimer = null;
let inactivityWarningTimer = null;
let inactivityCountdownTimer = null;
let inactivityWarningDeadline = null;
let currentContentVersion = null;
let updatePending = false;
let selectedTagId = "all";

function hideInactivityWarning() {
    if (!inactivityWarning) {
        return;
    }

    inactivityWarning.hidden = true;
    inactivityWarningDeadline = null;
    window.clearInterval(inactivityCountdownTimer);
    inactivityCountdownTimer = null;
}

function updateInactivityWarningCountdown() {
    if (inactivityWarningDeadline === null) {
        return;
    }

    const secondsLeft = Math.max(0, Math.ceil((inactivityWarningDeadline - Date.now()) / 1000));
    if (inactivityWarningCountdown) {
        inactivityWarningCountdown.textContent = String(secondsLeft);
    }

    if (inactivityWarningMessage) {
        inactivityWarningMessage.textContent = inactivityWarningMessage.dataset.warningTemplate;
    }

    if (secondsLeft <= 0) {
        window.location.href = "/kiosk";
    }
}

function showInactivityWarning() {
    if (!inactivityWarning) {
        return;
    }

    inactivityWarning.hidden = false;
    inactivityWarningDeadline = Date.now() + (inactivityWarningCountdownSeconds * 1000);
    if (inactivityWarningCountdown) {
        inactivityWarningCountdown.textContent = String(inactivityWarningCountdownSeconds);
    }
    updateInactivityWarningCountdown();
    window.clearInterval(inactivityCountdownTimer);
    inactivityCountdownTimer = window.setInterval(updateInactivityWarningCountdown, 1000);
}

function resetInactivityTimer() {
    window.clearTimeout(inactivityTimer);
    window.clearTimeout(inactivityWarningTimer);
    hideInactivityWarning();
    inactivityTimer = window.setTimeout(() => {
        showInactivityWarning();
        inactivityWarningTimer = window.setTimeout(() => {
            window.location.href = "/kiosk";
        }, inactivityWarningCountdownSeconds * 1000);
    }, inactivityWarningDelaySeconds * 1000);
}

function createTextElement(tagName, className, text) {
    const element = document.createElement(tagName);
    element.className = className;
    element.textContent = text;
    return element;
}

function replaceMissingKioskImage(image) {
    const placeholder = createTextElement("span", "event-image-placeholder", labels.imageArea);
    image.replaceWith(placeholder);
}

function renderEvent() {
    eventCard.innerHTML = "";

    if (events.length === 0) {
        eventCard.appendChild(emptyState);
        previousButton.disabled = true;
        nextButton.disabled = true;
        cardCounter.textContent = "0 / 0";
        return;
    }

    const event = events[currentEventIndex];
    const eventBody = document.createElement("div");
    eventBody.className = "event-card-body";

    if (event.image_kiosk) {
        const image = document.createElement("img");
        image.className = "event-card-image";
        image.src = event.image_kiosk;
        image.alt = event.title;
        image.addEventListener("error", () => replaceMissingKioskImage(image), { once: true });
        eventBody.appendChild(image);
    } else {
        eventBody.appendChild(createTextElement("span", "event-image-placeholder", labels.imageArea));
    }

    eventBody.appendChild(createTextElement("p", "event-date", event.event_date || labels.datePlaceholder));
    eventBody.appendChild(createTextElement("h2", "event-title", event.title));
    eventBody.appendChild(createTextElement("p", "event-description", event.short_description || event.full_description || labels.descriptionPlaceholder));
    eventBody.appendChild(createTextElement("p", "event-place", event.place || labels.placePlaceholder));

    eventCard.appendChild(eventBody);
    previousButton.disabled = events.length < 2;
    nextButton.disabled = events.length < 2;
    cardCounter.textContent = `${currentEventIndex + 1} / ${events.length}`;
}

function eventHasTag(event, tagId) {
    return (event.tags || []).some((tag) => String(tag.id) === String(tagId));
}

function tagExists(tagId) {
    return tagId === "all" || tags.some((tag) => String(tag.id) === String(tagId));
}

function filteredEvents() {
    if (selectedTagId === "all") {
        return allEvents;
    }

    return allEvents.filter((event) => eventHasTag(event, selectedTagId));
}

function updateActiveTagButtons() {
    document.querySelectorAll("[data-tag-filter]").forEach((button) => {
        button.classList.toggle("active", button.dataset.tagFilter === String(selectedTagId));
    });
}

function applySelectedFilter(resetIndex) {
    const currentEvent = events[currentEventIndex];
    events = filteredEvents();

    if (resetIndex) {
        currentEventIndex = 0;
    } else if (currentEvent) {
        const nextIndex = events.findIndex((event) => event.id === currentEvent.id);
        currentEventIndex = nextIndex >= 0 ? nextIndex : 0;
    } else {
        currentEventIndex = 0;
    }

    updateActiveTagButtons();
    renderEvent();
}

function selectTag(tagId) {
    selectedTagId = String(tagId);
    applySelectedFilter(true);
    tagsModal.hidden = true;
    resetInactivityTimer();
}

function createTagButton(tag, className) {
    const button = document.createElement("button");
    button.className = className;
    button.type = "button";
    button.dataset.tagFilter = String(tag.id);
    button.textContent = tag.name;
    button.addEventListener("click", () => selectTag(tag.id));
    return button;
}

function renderTags(nextTags) {
    tagList.innerHTML = "";
    allTags.innerHTML = "";

    if (nextTags.length === 0) {
        allTags.appendChild(createTextElement("p", "modal-empty", labels.noTags));
        return;
    }

    nextTags.slice(0, 4).forEach((tag) => {
        tagList.appendChild(createTagButton(tag, "tag-button"));
    });

    nextTags.forEach((tag) => {
        allTags.appendChild(createTagButton(tag, "modal-tag"));
    });
}

function moveEvent(direction) {
    if (events.length < 2) {
        return;
    }

    currentEventIndex = (currentEventIndex + direction + events.length) % events.length;
    renderEvent();
    resetInactivityTimer();
}

function randomUpdateDelay() {
    return Math.floor(Math.random() * (updateDelayMax + 1));
}

function applyEventsData(versionData, eventsData, tagsData) {
    allEvents = eventsData.events || [];
    tags = tagsData.tags || [];
    currentContentVersion = versionData.content_version;
    contentVersion.textContent = `${labels.versionLabel} ${currentContentVersion}`;

    if (!tagExists(selectedTagId)) {
        selectedTagId = "all";
    }

    renderTags(tags);
    applySelectedFilter(false);
}

let loadInProgress = false;
let pollInProgress = false;

async function requestKioskJson(url) {
    const controller = new AbortController();
    let timer;
    try {
        // Keep the deadline active through body decoding, not only response headers.
        return await Promise.race([
            (async () => {
                const response = await fetch(url, { signal: controller.signal });
                if (!response.ok) throw new Error("Kiosk request failed");
                return await response.json();
            })(),
            new Promise((resolve, reject) => {
                timer = window.setTimeout(() => {
                    controller.abort();
                    reject(new Error("Kiosk request timed out"));
                }, 10000);
            }),
        ]);
    } finally {
        window.clearTimeout(timer);
        controller.abort();
    }
}

function validateKioskVersion(data) {
    if (!data || !Number.isSafeInteger(data.content_version) || data.content_version < 1) {
        throw new Error("Invalid kiosk version");
    }
}

function validateKioskData(eventsData, tagsData) {
    const validTag = tag => tag && Number.isSafeInteger(tag.id) && tag.id > 0 && typeof tag.name === "string";
    if (!eventsData || !Array.isArray(eventsData.events) || !tagsData || !Array.isArray(tagsData.tags)
        || !tagsData.tags.every(validTag) || !eventsData.events.every(event => event
            && Number.isSafeInteger(event.id) && event.id > 0 && typeof event.title === "string"
            && ["event_date", "short_description", "full_description", "place", "image_kiosk"]
                .every(field => event[field] == null || typeof event[field] === "string")
            && Array.isArray(event.tags) && event.tags.every(validTag))) {
        throw new Error("Invalid kiosk content");
    }
}

async function loadKioskEventsPage() {
    if (loadInProgress) return;
    loadInProgress = true;
    try {
        const [versionData, eventsData, tagsData] = await Promise.all([
            requestKioskJson("/api/version"), requestKioskJson("/api/events"), requestKioskJson("/api/tags"),
        ]);
        validateKioskVersion(versionData);
        validateKioskData(eventsData, tagsData);
        // Concurrent API requests are not a transactional snapshot: discard a changing generation.
        const after = await requestKioskJson("/api/version");
        validateKioskVersion(after);
        if (after.content_version !== versionData.content_version
            || (currentContentVersion !== null && versionData.content_version < currentContentVersion)) {
            throw new Error("Kiosk content changed during loading");
        }
        applyEventsData(versionData, eventsData, tagsData);
    } finally {
        loadInProgress = false;
    }
}

async function pollKioskVersion() {
    if (updatePending || loadInProgress || pollInProgress) return;
    pollInProgress = true;
    try {
        const versionData = await requestKioskJson("/api/version");
        validateKioskVersion(versionData);
        if (currentContentVersion === null || versionData.content_version > currentContentVersion) {
            updatePending = true;
            window.setTimeout(() => {
                loadKioskEventsPage()
                    .catch(() => { contentVersion.textContent = labels.versionUnavailable; })
                    .finally(() => { updatePending = false; });
            }, randomUpdateDelay());
        } else if (versionData.content_version === currentContentVersion) {
            contentVersion.textContent = `${labels.versionLabel} ${currentContentVersion}`;
        }
    } finally {
        pollInProgress = false;
    }
}

previousButton.addEventListener("click", () => moveEvent(-1));
nextButton.addEventListener("click", () => moveEvent(1));
allEventsButton.addEventListener("click", () => selectTag("all"));
openTagsButton.addEventListener("click", () => {
    tagsModal.hidden = false;
    resetInactivityTimer();
});
closeTagsButton.addEventListener("click", () => {
    tagsModal.hidden = true;
    resetInactivityTimer();
});

["click", "pointerdown", "keydown", "touchstart"].forEach((eventName) => {
    window.addEventListener(eventName, resetInactivityTimer, { passive: true });
});

loadKioskEventsPage().catch(() => {
    contentVersion.textContent = labels.versionUnavailable;
    renderEvent();
});
window.setInterval(() => {
    pollKioskVersion().catch(() => {
        contentVersion.textContent = labels.versionUnavailable;
    });
}, versionPollInterval);
resetInactivityTimer();
