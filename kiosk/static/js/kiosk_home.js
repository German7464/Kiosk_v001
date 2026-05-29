const kioskHome = document.querySelector("[data-kiosk-home]");
const kioskFullscreenButton = document.querySelector("[data-kiosk-fullscreen]");
const kioskHomeVersionPollInterval = Number(kioskHome.dataset.versionPollInterval);
const kioskHomeUpdateDelayMax = Number(kioskHome.dataset.updateDelayMax);

let kioskHomeContentVersion = null;
let kioskHomeUpdatePending = false;

function kioskHomeRandomUpdateDelay() {
    return Math.floor(Math.random() * (kioskHomeUpdateDelayMax + 1));
}

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

function handleFullscreenResult(result) {
    if (result && typeof result.catch === "function") {
        result.catch(() => {});
    }
}

function toggleKioskFullscreen() {
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

    handleFullscreenResult(fullscreenRequestHandler().call(fullscreenTarget()));
}

function setupKioskFullscreenButton() {
    if (!kioskFullscreenButton) {
        return;
    }

    if (!fullscreenSupported()) {
        kioskFullscreenButton.hidden = true;
        return;
    }

    kioskFullscreenButton.addEventListener("click", toggleKioskFullscreen);
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

setupKioskFullscreenButton();

loadKioskHomeVersion().catch(() => {});
window.setInterval(() => {
    pollKioskHomeVersion().catch(() => {});
}, kioskHomeVersionPollInterval);
