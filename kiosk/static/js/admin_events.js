const adminPreviewModal = document.querySelector("[data-admin-preview-modal]");
const adminPreviewMode = document.querySelector("[data-admin-preview-mode]");
const adminPreviewImage = document.querySelector("[data-admin-preview-image]");
const adminPreviewTitle = document.querySelector("[data-admin-preview-title]");
const adminPreviewDate = document.querySelector("[data-admin-preview-date]");
const adminPreviewPlace = document.querySelector("[data-admin-preview-place]");
const adminPreviewDescription = document.querySelector("[data-admin-preview-description]");
const closeAdminPreview = document.querySelector("[data-close-admin-preview]");

function setPreviewImage(imageUrl) {
    adminPreviewImage.innerHTML = "";
    adminPreviewImage.style.backgroundImage = "";

    if (!imageUrl) {
        const placeholder = document.createElement("span");
        placeholder.textContent = adminPreviewImage.dataset.placeholder || "Image area";
        adminPreviewImage.appendChild(placeholder);
        return;
    }

    adminPreviewImage.style.backgroundImage = `url("${imageUrl}")`;
}

function openAdminPreview(button) {
    adminPreviewMode.textContent = button.dataset.previewMode === "tv" ? "TV preview" : "Kiosk preview";
    adminPreviewTitle.textContent = button.dataset.previewTitle;
    adminPreviewDate.textContent = button.dataset.previewDate;
    adminPreviewPlace.textContent = button.dataset.previewPlace;
    adminPreviewDescription.textContent = button.dataset.previewDescription;
    setPreviewImage(button.dataset.previewImage);
    adminPreviewModal.hidden = false;
}

function closeAdminPreviewModal() {
    adminPreviewModal.hidden = true;
}

document.querySelectorAll("[data-open-admin-preview]").forEach((button) => {
    button.addEventListener("click", () => openAdminPreview(button));
});

if (closeAdminPreview) {
    closeAdminPreview.addEventListener("click", closeAdminPreviewModal);
}

if (adminPreviewModal) {
    adminPreviewModal.addEventListener("click", (event) => {
        if (event.target === adminPreviewModal) {
            closeAdminPreviewModal();
        }
    });
}

document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && adminPreviewModal && !adminPreviewModal.hidden) {
        closeAdminPreviewModal();
    }
});
