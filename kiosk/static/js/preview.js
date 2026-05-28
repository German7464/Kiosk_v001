const previewScreen = document.querySelector("[data-preview-screen]");
const previewVersion = document.querySelector("[data-preview-version]");
const previewPollInterval = Number(previewScreen.dataset.versionPollInterval);
const previewUpdateDelayMax = Number(previewScreen.dataset.updateDelayMax);
const previewLabels = previewScreen.dataset;

let previewContentVersion = null;
let previewUpdatePending = false;

function previewRandomUpdateDelay() {
    return Math.floor(Math.random() * (previewUpdateDelayMax + 1));
}

function applyPreviewVersion(versionData) {
    previewContentVersion = versionData.content_version;
    previewVersion.textContent = `${previewLabels.versionLabel} ${previewContentVersion}`;
}

async function loadPreviewVersion() {
    const versionResponse = await fetch("/api/version");
    const versionData = await versionResponse.json();
    applyPreviewVersion(versionData);
}

async function pollPreviewVersion() {
    if (previewUpdatePending) {
        return;
    }

    const versionResponse = await fetch("/api/version");
    const versionData = await versionResponse.json();

    if (previewContentVersion !== null && versionData.content_version !== previewContentVersion) {
        previewUpdatePending = true;
        window.setTimeout(() => {
            applyPreviewVersion(versionData);
            previewUpdatePending = false;
        }, previewRandomUpdateDelay());
    }
}

loadPreviewVersion().catch(() => {
    previewVersion.textContent = previewLabels.versionUnavailable;
});
window.setInterval(() => {
    pollPreviewVersion().catch(() => {
        previewVersion.textContent = previewLabels.versionUnavailable;
    });
}, previewPollInterval);
