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
        showAdminPreviewPlaceholder();
        return;
    }

    const image = new Image();
    image.onload = () => {
        adminPreviewImage.innerHTML = "";
        adminPreviewImage.style.backgroundImage = `url("${imageUrl}")`;
    };
    image.onerror = showAdminPreviewPlaceholder;
    image.src = imageUrl;
}

function showAdminPreviewPlaceholder() {
    const placeholder = document.createElement("span");
    adminPreviewImage.innerHTML = "";
    adminPreviewImage.style.backgroundImage = "";
    placeholder.textContent = adminPreviewImage.dataset.placeholder || "Image area";
    adminPreviewImage.appendChild(placeholder);
}

function replaceMissingAdminThumb(image) {
    const wrapper = image.closest(".admin-preview-media");
    const placeholder = document.createElement("span");

    if (!wrapper) {
        return;
    }

    placeholder.textContent = wrapper.dataset.placeholder || "Image area";
    image.replaceWith(placeholder);
}

function openAdminPreview(button) {
    adminPreviewMode.textContent = button.dataset.previewMode === "tv" ? adminPreviewModal.dataset.tvPreviewLabel : adminPreviewModal.dataset.kioskPreviewLabel;
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

document.querySelectorAll(".admin-preview-media img").forEach((image) => {
    image.addEventListener("error", () => replaceMissingAdminThumb(image), { once: true });
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
