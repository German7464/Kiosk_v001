const tvScreen = document.querySelector(".tv-screen");
const tvCard = document.querySelector("[data-tv-card]");
const tvImage = document.querySelector("[data-tv-image]");
const tvDate = document.querySelector("[data-tv-date]");
const tvTitle = document.querySelector("[data-tv-title]");
const tvPlace = document.querySelector("[data-tv-place]");
const tvDescription = document.querySelector("[data-tv-description]");
const tvVersion = document.querySelector("[data-tv-version]");
const tvEmptyState = document.querySelector("[data-tv-empty-state]");
const slideDuration = Number(tvScreen.dataset.slideDuration);

let tvEvents = [];
let tvEventIndex = 0;

function applyTvEvent(event) {
    tvCard.classList.remove("is-visible");

    window.setTimeout(() => {
        tvDate.textContent = event.event_date || "Date to be announced";
        tvTitle.textContent = event.title;
        tvPlace.textContent = event.place || "Place to be announced";
        tvDescription.textContent = event.short_description || "No description yet.";

        if (event.image_tv || event.image_kiosk) {
            const imageUrl = event.image_tv || event.image_kiosk;
            tvImage.innerHTML = "";
            tvImage.style.backgroundImage = `url("${imageUrl}")`;
        } else {
            tvImage.style.backgroundImage = "";
            tvImage.innerHTML = "<span>Image area</span>";
        }

        tvCard.classList.add("is-visible");
    }, 220);
}

function showNextTvEvent() {
    if (tvEvents.length === 0) {
        return;
    }

    applyTvEvent(tvEvents[tvEventIndex]);
    tvEventIndex = (tvEventIndex + 1) % tvEvents.length;
}

async function loadTvDisplay() {
    const [versionResponse, eventsResponse] = await Promise.all([
        fetch("/api/version"),
        fetch("/api/events"),
    ]);

    const versionData = await versionResponse.json();
    const eventsData = await eventsResponse.json();

    tvVersion.textContent = `Version ${versionData.content_version}`;
    tvEvents = eventsData.events || [];

    if (tvEvents.length === 0) {
        tvCard.hidden = true;
        tvEmptyState.hidden = false;
        return;
    }

    tvCard.hidden = false;
    tvEmptyState.hidden = true;
    showNextTvEvent();
    window.setInterval(showNextTvEvent, slideDuration);
}

loadTvDisplay().catch(() => {
    tvVersion.textContent = "Version unavailable";
    tvCard.hidden = true;
    tvEmptyState.hidden = false;
});
