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
const inactivitySeconds = Number(eventsScreen.dataset.inactivitySeconds);
const labels = eventsScreen.dataset;

let events = [];
let currentEventIndex = 0;
let inactivityTimer = null;

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
        eventBody.appendChild(image);
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

function renderTags(tags) {
    tagList.innerHTML = "";
    allTags.innerHTML = "";

    if (tags.length === 0) {
        allTags.appendChild(createTextElement("p", "modal-empty", labels.noTags));
        return;
    }

    tags.slice(0, 4).forEach((tag) => {
        const button = document.createElement("button");
        button.className = "tag-button";
        button.type = "button";
        button.textContent = tag.name;
        tagList.appendChild(button);
    });

    tags.forEach((tag) => {
        const tagItem = createTextElement("span", "modal-tag", tag.name);
        allTags.appendChild(tagItem);
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

async function loadKioskEventsPage() {
    const [versionResponse, eventsResponse, tagsResponse] = await Promise.all([
        fetch("/api/version"),
        fetch("/api/events"),
        fetch("/api/tags"),
    ]);

    const versionData = await versionResponse.json();
    const eventsData = await eventsResponse.json();
    const tagsData = await tagsResponse.json();

    contentVersion.textContent = `${labels.versionLabel} ${versionData.content_version}`;
    events = eventsData.events || [];
    currentEventIndex = 0;
    renderTags(tagsData.tags || []);
    renderEvent();
}

previousButton.addEventListener("click", () => moveEvent(-1));
nextButton.addEventListener("click", () => moveEvent(1));
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
resetInactivityTimer();
