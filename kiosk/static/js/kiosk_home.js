const kioskHome = document.querySelector("[data-kiosk-home]");
const kioskHomeVersionPollInterval = Number(kioskHome.dataset.versionPollInterval);
const kioskHomeUpdateDelayMax = Number(kioskHome.dataset.updateDelayMax);

let kioskHomeContentVersion = null;
let kioskHomeUpdatePending = false;

function kioskHomeRandomUpdateDelay() {
    return Math.floor(Math.random() * (kioskHomeUpdateDelayMax + 1));
}

async function loadKioskHomeVersion() {
    const versionResponse = await fetch("/api/version");
    const versionData = await versionResponse.json();
    kioskHomeContentVersion = versionData.content_version;
}

async function pollKioskHomeVersion() {
    if (kioskHomeUpdatePending) {
        return;
    }

    const versionResponse = await fetch("/api/version");
    const versionData = await versionResponse.json();

    if (kioskHomeContentVersion !== null && versionData.content_version !== kioskHomeContentVersion) {
        kioskHomeUpdatePending = true;
        window.setTimeout(() => {
            window.location.reload();
        }, kioskHomeRandomUpdateDelay());
    }
}

loadKioskHomeVersion().catch(() => {});
window.setInterval(() => {
    pollKioskHomeVersion().catch(() => {});
}, kioskHomeVersionPollInterval);
