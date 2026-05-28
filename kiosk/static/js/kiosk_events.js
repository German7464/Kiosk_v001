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
const inactivitySeconds = Number(eventsScreen.dataset.inactivitySeconds);
const versionPollInterval = Number(eventsScreen.dataset.versionPollInterval);
const updateDelayMax = Number(eventsScreen.dataset.updateDelayMax);
const labels = eventsScreen.dataset;

let allEvents = [];
let events = [];
let tags = [];
let currentEventIndex = 0;
let inactivityTimer = null;
let currentContentVersion = null;
let updatePending = false;
let selectedTagId = "all";

function resetInactivityTimer() {
    window.clearTimeout(inactivityTimer);
    inactivityTimer = window.setTimeout(() => {
        window.location.href = "/kiosk";
    }, inactivitySeconds * 1000);
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

async function loadKioskEventsPage() {
    const [versionResponse, eventsResponse, tagsResponse] = await Promise.all([
        fetch("/api/version"),
        fetch("/api/events"),
        fetch("/api/tags"),
    ]);

    const versionData = await versionResponse.json();
    const eventsData = await eventsResponse.json();
    const tagsData = await tagsResponse.json();

    applyEventsData(versionData, eventsData, tagsData);
}

async function pollKioskVersion() {
    if (updatePending) {
        return;
    }

    const versionResponse = await fetch("/api/version");
    const versionData = await versionResponse.json();

    if (currentContentVersion !== null && versionData.content_version !== currentContentVersion) {
        updatePending = true;
        window.setTimeout(() => {
            loadKioskEventsPage()
                .catch(() => {
                    contentVersion.textContent = labels.versionUnavailable;
                })
                .finally(() => {
                    updatePending = false;
                });
        }, randomUpdateDelay());
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
