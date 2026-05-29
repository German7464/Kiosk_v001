const kioskHome = document.querySelector("[data-kiosk-home]");
const kioskFullscreenButton = document.querySelector("[data-kiosk-fullscreen]");
const kioskUnlockModal = document.querySelector("[data-kiosk-unlock-modal]");
const kioskUnlockForm = document.querySelector("[data-kiosk-unlock-form]");
const kioskUnlockError = document.querySelector("[data-kiosk-unlock-error]");
const kioskUnlockUsername = document.querySelector("[data-kiosk-unlock-username]");
const kioskUnlockPassword = document.querySelector("[data-kiosk-unlock-password]");
const kioskUnlockReturn = document.querySelector("[data-kiosk-unlock-return]");
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

function updateKioskFullscreenButtonState() {
    if (!kioskFullscreenButton) {
        return;
    }

    kioskFullscreenButton.setAttribute("aria-pressed", String(Boolean(fullscreenElement())));
}

function hideKioskUnlockModal() {
    if (!kioskUnlockModal) {
        return;
    }

    kioskUnlockModal.hidden = true;
    kioskUnlockError.hidden = true;
    kioskUnlockError.textContent = "";
    kioskUnlockForm.reset();
}

function showKioskUnlockModal() {
    if (!kioskUnlockModal) {
        return;
    }

    kioskUnlockModal.hidden = false;
    kioskUnlockError.hidden = true;
    kioskUnlockError.textContent = "";
    window.setTimeout(() => {
        kioskUnlockUsername.focus();
        kioskUnlockUsername.select();
    }, 0);
}

function kioskFullscreenExitAllowed() {
    if (!fullscreenElement()) {
        return false;
    }

    return fullscreenCanExit();
}

function enterKioskFullscreen() {
    if (!fullscreenSupported()) {
        return;
    }

    handleFullscreenResult(fullscreenRequestHandler().call(fullscreenTarget()));
}

async function requestKioskFullscreenExit() {
    const response = await fetch("/admin/fullscreen/validate", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({
            username: kioskUnlockUsername.value,
            password: kioskUnlockPassword.value,
        }),
    });

    const data = await response.json();

    if (data.success && kioskFullscreenExitAllowed()) {
        hideKioskUnlockModal();
        handleFullscreenResult(fullscreenExitHandler().call(document));
        return true;
    }

    kioskUnlockError.textContent = kioskUnlockError.dataset.invalidMessage;
    kioskUnlockError.hidden = false;
    kioskUnlockPassword.value = "";
    kioskUnlockPassword.focus();
    return false;
}

function toggleKioskFullscreen() {
    if (!fullscreenSupported()) {
        return;
    }

    if (fullscreenElement()) {
        showKioskUnlockModal();
        return;
    }

    enterKioskFullscreen();
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
    document.addEventListener("fullscreenchange", updateKioskFullscreenButtonState);
    document.addEventListener("webkitfullscreenchange", updateKioskFullscreenButtonState);
    document.addEventListener("msfullscreenchange", updateKioskFullscreenButtonState);
    updateKioskFullscreenButtonState();
}

function setupKioskUnlockModal() {
    if (!kioskUnlockModal) {
        return;
    }

    kioskUnlockReturn.addEventListener("click", hideKioskUnlockModal);
    kioskUnlockForm.addEventListener("submit", (event) => {
        event.preventDefault();
        requestKioskFullscreenExit().catch(() => {
            kioskUnlockError.textContent = kioskUnlockError.dataset.invalidMessage;
            kioskUnlockError.hidden = false;
        });
    });

    document.addEventListener("fullscreenchange", () => {
        if (!fullscreenElement()) {
            hideKioskUnlockModal();
        }
    });
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
setupKioskUnlockModal();

loadKioskHomeVersion().catch(() => {});
window.setInterval(() => {
    pollKioskHomeVersion().catch(() => {});
}, kioskHomeVersionPollInterval);
